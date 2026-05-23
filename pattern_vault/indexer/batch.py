"""
Pattern Vault — Batch indexer.

Orchestrates: scan directory → chunk files → extract patterns via Claude → store.
Processes incrementally (skips unchanged files via content hash).
"""

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..indexer.chunker import CodeChunk, chunk_file, filter_manifest, scan_directory
from ..indexer.extractor import extract_patterns_sync
from ..indexer.profiles import DEFAULT_INDEXING_PROFILE, get_indexing_profile
from ..store.db import get_connection, init_db, insert_pattern


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_skipped: int = 0
    chunks_extracted: int = 0
    patterns_found: int = 0
    patterns_stored: int = 0
    patterns_rejected: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


BATCH_SIZE = 5  # chunks per Claude API call
EXTRACTION_MAX_ATTEMPTS = 3
EXTRACTION_BACKOFF_SECONDS = 1.0


def index_directory(
    directory: str | Path,
    db_path: Optional[Path] = None,
    repo_name: Optional[str] = None,
    api_key: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
    profile: str = DEFAULT_INDEXING_PROFILE,
    include_languages: Optional[list[str]] = None,
    include_paths: Optional[list[str]] = None,
    exclude_paths: Optional[list[str]] = None,
) -> IndexStats:
    """
    Index a directory: scan files, extract patterns, store them.

    Args:
        directory: Path to scan
        db_path: Custom DB path (default: ~/.pattern-vault/patterns.db)
        repo_name: Name for the source repo (default: directory name)
        api_key: Anthropic API key (default: ANTHROPIC_API_KEY env var)
        on_progress: Callback for progress messages
        dry_run: If True, scan and chunk but don't call Claude or store
        profile: Pattern volume profile: curated, balanced, or comprehensive
        include_languages: Restrict indexing to these languages
        include_paths: Glob patterns to include relative paths
        exclude_paths: Glob patterns to exclude relative paths
    """
    stats = IndexStats()
    directory = Path(directory).resolve()
    repo_name = repo_name or directory.name
    profile_config = get_indexing_profile(profile)

    def log(msg: str):
        if on_progress:
            on_progress(msg)

    # Step 1: Scan
    log(f"Scanning {directory}...")
    log(
        f"Indexing profile: {profile_config.label} "
        f"(min quality {profile_config.min_quality_score:.2f})"
    )
    manifest = scan_directory(directory)
    manifest = filter_manifest(
        manifest,
        include_languages=include_languages,
        include_paths=include_paths,
        exclude_paths=exclude_paths,
    )
    log(f"Found {manifest.total_files} files ({manifest.skipped} skipped)")
    log(f"Languages: {json.dumps(manifest.languages)}")
    if include_languages:
        log(f"Language filter: {json.dumps(include_languages)}")
    if include_paths:
        log(f"Include path filters: {json.dumps(include_paths)}")
    if exclude_paths:
        log(f"Exclude path filters: {json.dumps(exclude_paths)}")

    if manifest.total_files == 0:
        log("No source files found.")
        return stats

    # Step 2: Connect to DB
    conn = get_connection(db_path)
    init_db(conn)

    # Step 3: Chunk all files
    all_chunks: list[tuple[dict, CodeChunk]] = []  # (file_info, chunk)

    for file_info in manifest.files:
        stats.files_scanned += 1
        try:
            chunks = chunk_file(file_info["path"], file_info["language"])
            for chunk in chunks:
                # Check if this chunk's code is already in the DB
                chash = hashlib.sha256(chunk.code.encode()).hexdigest()[:16]
                existing = conn.execute(
                    "SELECT id FROM patterns WHERE content_hash = ?", (chash,)
                ).fetchone()
                if existing:
                    stats.files_skipped += 1
                    continue

                all_chunks.append((file_info, chunk))
                stats.chunks_extracted += 1
        except Exception as e:
            stats.errors.append(f"Error chunking {file_info['relative']}: {e}")

    log(f"Extracted {stats.chunks_extracted} chunks from {stats.files_scanned} files")

    if dry_run:
        log("Dry run — skipping extraction and storage.")
        conn.close()
        return stats

    if not all_chunks:
        log("No new chunks to process.")
        conn.close()
        return stats

    pattern_budget = profile_config.budget_for_chunks(len(all_chunks))
    if pattern_budget is not None:
        log(f"Pattern budget: storing up to {pattern_budget} patterns for this profile.")

    # Step 4: Batch extract patterns via Claude
    for batch_start in range(0, len(all_chunks), BATCH_SIZE):
        if pattern_budget is not None and stats.patterns_stored >= pattern_budget:
            log(f"Pattern budget reached ({pattern_budget}); skipping remaining extraction.")
            break

        batch = all_chunks[batch_start : batch_start + BATCH_SIZE]
        batch_number = (batch_start // BATCH_SIZE) + 1
        chunk_range_start = batch_start + 1
        chunk_range_end = batch_start + len(batch)
        batch_context = (
            f"batch {batch_number} (chunks {chunk_range_start}-{chunk_range_end})"
        )
        log(f"Extracting patterns from chunks {chunk_range_start}-{chunk_range_end}...")

        chunk_dicts = []
        for _fi, chunk in batch:
            chunk_dicts.append({
                "code": chunk.code,
                "file_path": chunk.file_path,
                "language": chunk.language,
                "symbol_name": chunk.symbol_name,
                "symbol_type": chunk.symbol_type,
                "line_start": chunk.line_start,
                "line_end": chunk.line_end,
            })

        results = None
        for attempt in range(1, EXTRACTION_MAX_ATTEMPTS + 1):
            try:
                results = extract_patterns_sync(
                    chunk_dicts,
                    api_key=api_key,
                    db_path=db_path,
                    profile_guidance=profile_config.guidance,
                )
                break
            except Exception as e:
                if attempt >= EXTRACTION_MAX_ATTEMPTS:
                    stats.errors.append(
                        f"Extraction error at {batch_context} after {attempt} attempts: {e}"
                    )
                    break

                log(
                    f"Retrying extraction for {batch_context} after attempt "
                    f"{attempt}/{EXTRACTION_MAX_ATTEMPTS}: {e}"
                )
                time.sleep(EXTRACTION_BACKOFF_SECONDS * attempt)

        if results is None:
            continue

        # Step 5: Store patterns
        for result in results:
            if not result.is_pattern:
                continue

            stats.patterns_found += 1
            if pattern_budget is not None and stats.patterns_stored >= pattern_budget:
                stats.patterns_rejected += 1
                continue

            if not _passes_profile_quality(result.quality_score, profile_config.min_quality_score):
                stats.patterns_rejected += 1
                log(
                    f"  Rejected: [{result.category}] {result.name or 'unnamed pattern'} "
                    f"(quality below {profile_config.min_quality_score:.2f})"
                )
                continue

            idx = result.chunk_index
            if idx >= len(batch):
                continue

            file_info, chunk = batch[idx]
            try:
                insert_pattern(
                    conn,
                    name=result.name,
                    summary=result.summary,
                    code_text=chunk.code,
                    category=result.category,
                    language=chunk.language,
                    tags=result.tags,
                    quality_signal=result.quality_signal,
                    source_repo=repo_name,
                    source_file=file_info["relative"],
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                )
                stats.patterns_stored += 1
                log(f"  Stored: [{result.category}] {result.name}")
            except Exception as e:
                stats.errors.append(f"Storage error for {result.name}: {e}")

    if stats.patterns_rejected:
        log(f"Rejected {stats.patterns_rejected} low-priority patterns by profile controls.")
    log(f"Done. Found {stats.patterns_found} patterns, stored {stats.patterns_stored}.")
    conn.close()
    return stats


def _passes_profile_quality(quality_score: float | None, minimum: float) -> bool:
    return quality_score is not None and quality_score >= minimum
