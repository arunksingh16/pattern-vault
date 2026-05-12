"""
Pattern Vault — Batch indexer.

Orchestrates: scan directory → chunk files → extract patterns via Claude → store.
Processes incrementally (skips unchanged files via content hash).
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from ..indexer.chunker import CodeChunk, chunk_file, scan_directory
from ..indexer.extractor import extract_patterns_sync
from ..store.db import get_connection, init_db, insert_pattern


@dataclass
class IndexStats:
    files_scanned: int = 0
    files_skipped: int = 0
    chunks_extracted: int = 0
    patterns_found: int = 0
    patterns_stored: int = 0
    errors: list[str] = None

    def __post_init__(self):
        if self.errors is None:
            self.errors = []


BATCH_SIZE = 5  # chunks per Claude API call


def index_directory(
    directory: str | Path,
    db_path: Optional[Path] = None,
    repo_name: Optional[str] = None,
    api_key: Optional[str] = None,
    on_progress: Optional[Callable[[str], None]] = None,
    dry_run: bool = False,
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
    """
    stats = IndexStats()
    directory = Path(directory).resolve()
    repo_name = repo_name or directory.name

    def log(msg: str):
        if on_progress:
            on_progress(msg)

    # Step 1: Scan
    log(f"Scanning {directory}...")
    manifest = scan_directory(directory)
    log(f"Found {manifest.total_files} files ({manifest.skipped} skipped)")
    log(f"Languages: {json.dumps(manifest.languages)}")

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

    # Step 4: Batch extract patterns via Claude
    for batch_start in range(0, len(all_chunks), BATCH_SIZE):
        batch = all_chunks[batch_start : batch_start + BATCH_SIZE]
        log(f"Extracting patterns from chunks {batch_start + 1}-{batch_start + len(batch)}...")

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

        try:
            results = extract_patterns_sync(chunk_dicts, api_key=api_key)
        except Exception as e:
            stats.errors.append(f"Extraction error at batch {batch_start}: {e}")
            continue

        # Step 5: Store patterns
        for result in results:
            if not result.is_pattern:
                continue

            stats.patterns_found += 1
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

    log(f"Done. Found {stats.patterns_found} patterns, stored {stats.patterns_stored}.")
    conn.close()
    return stats
