"""
Pattern Vault — Tree-sitter AST chunker.

Parses source files into semantic chunks (functions, classes, methods)
using tree-sitter. Falls back to simple line-based chunking if tree-sitter
grammars aren't available for a language.
"""

import importlib
from fnmatch import fnmatch
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Language extension mapping
LANG_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".java": "java",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".php": "php",
    ".sh": "bash",
    ".bash": "bash",
}

# Tree-sitter node types to extract per language
SYMBOL_TYPES: dict[str, list[str]] = {
    "python": [
        "function_definition",
        "class_definition",
        "decorated_definition",
    ],
    "javascript": [
        "function_declaration",
        "class_declaration",
        "arrow_function",
        "method_definition",
        "export_statement",
    ],
    "typescript": [
        "function_declaration",
        "class_declaration",
        "arrow_function",
        "method_definition",
        "export_statement",
        "interface_declaration",
        "type_alias_declaration",
    ],
    "go": [
        "function_declaration",
        "method_declaration",
        "type_declaration",
    ],
    "rust": [
        "function_item",
        "impl_item",
        "struct_item",
        "enum_item",
        "trait_item",
    ],
}

# Default for languages not explicitly listed
DEFAULT_SYMBOL_TYPES = [
    "function_definition",
    "function_declaration",
    "class_definition",
    "class_declaration",
    "method_definition",
    "method_declaration",
]


@dataclass
class CodeChunk:
    """A semantic chunk of code extracted from a source file."""
    symbol_name: str
    symbol_type: str  # function, class, method, etc.
    code: str
    file_path: str
    language: str
    line_start: int
    line_end: int
    context: str = ""  # imports, decorators, or surrounding context


@dataclass
class FileManifest:
    """Manifest of files discovered in a directory."""
    files: list[dict] = field(default_factory=list)
    total_files: int = 0
    languages: dict[str, int] = field(default_factory=dict)
    skipped: int = 0


# Directories and files to always skip
SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "env",
    ".env", "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".tox", ".mypy_cache", ".pytest_cache", "coverage", ".coverage",
    ".idea", ".vscode", "egg-info", ".eggs",
}

SKIP_EXTENSIONS = {
    ".pyc", ".pyo", ".o", ".so", ".dylib", ".dll", ".exe",
    ".jpg", ".jpeg", ".png", ".gif", ".svg", ".ico", ".webp",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".7z",
    ".lock", ".min.js", ".min.css", ".map",
}

MAX_FILE_SIZE = 500_000  # 500KB — skip huge generated files


def scan_directory(root: str | Path) -> FileManifest:
    """Walk a directory and build a manifest of source files."""
    root = Path(root).resolve()
    manifest = FileManifest()

    if not root.exists():
        return manifest

    for path in sorted(root.rglob("*")):
        # Skip directories in SKIP_DIRS
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        if path.suffix in SKIP_EXTENSIONS:
            manifest.skipped += 1
            continue
        if path.stat().st_size > MAX_FILE_SIZE:
            manifest.skipped += 1
            continue
        if path.suffix not in LANG_MAP:
            manifest.skipped += 1
            continue

        lang = LANG_MAP[path.suffix]
        rel = str(path.relative_to(root))
        manifest.files.append({
            "path": str(path),
            "relative": rel,
            "language": lang,
            "size": path.stat().st_size,
        })
        manifest.languages[lang] = manifest.languages.get(lang, 0) + 1

    manifest.total_files = len(manifest.files)
    return manifest


def filter_manifest(
    manifest: FileManifest,
    include_languages: list[str] | None = None,
    include_paths: list[str] | None = None,
    exclude_paths: list[str] | None = None,
) -> FileManifest:
    include_language_set = {
        language.strip().lower()
        for language in (include_languages or [])
        if language.strip()
    }
    include_patterns = [pattern.strip() for pattern in (include_paths or []) if pattern.strip()]
    exclude_patterns = [pattern.strip() for pattern in (exclude_paths or []) if pattern.strip()]

    if not include_language_set and not include_patterns and not exclude_patterns:
        return manifest

    filtered_files: list[dict] = []
    filtered_languages: dict[str, int] = {}
    filtered_out = 0

    for file_info in manifest.files:
        relative_path = file_info["relative"].replace("\\", "/")
        language = str(file_info["language"]).lower()

        if include_language_set and language not in include_language_set:
            filtered_out += 1
            continue

        if include_patterns and not any(fnmatch(relative_path, pattern) for pattern in include_patterns):
            filtered_out += 1
            continue

        if exclude_patterns and any(fnmatch(relative_path, pattern) for pattern in exclude_patterns):
            filtered_out += 1
            continue

        filtered_files.append(file_info)
        filtered_languages[file_info["language"]] = filtered_languages.get(file_info["language"], 0) + 1

    return FileManifest(
        files=filtered_files,
        total_files=len(filtered_files),
        languages=filtered_languages,
        skipped=manifest.skipped + filtered_out,
    )


def _get_symbol_name(node, source_bytes: bytes) -> str:
    """Extract the name of a symbol from a tree-sitter node."""
    # Look for a 'name' child or 'identifier' child
    for child in node.children:
        if child.type in ("identifier", "name", "property_identifier"):
            return source_bytes[child.start_byte:child.end_byte].decode("utf-8", errors="replace")
        # For decorated definitions, recurse into the definition
        if child.type in SYMBOL_TYPES.get("python", []):
            return _get_symbol_name(child, source_bytes)
    return f"anonymous_{node.start_point[0]}"


def _try_load_parser(language: str):
    """Try to load a tree-sitter parser for the given language. Returns (Parser, Language) or (None, None)."""
    try:
        from tree_sitter import Language, Parser
        # Try the individual language package first
        lang_module = importlib.import_module(f"tree_sitter_{language}")
        lang_obj = Language(lang_module.language())
        parser = Parser(lang_obj)
        return parser, lang_obj
    except (ImportError, AttributeError, Exception):
        pass

    # Try tree_sitter_languages package (older)
    try:
        from tree_sitter_languages import get_parser
        parser = get_parser(language)
        return parser, None
    except (ImportError, Exception):
        pass

    return None, None


def chunk_file_treesitter(file_path: str | Path, language: str) -> list[CodeChunk]:
    """Chunk a file using tree-sitter AST parsing."""
    file_path = Path(file_path)
    source = file_path.read_bytes()
    source_text = source.decode("utf-8", errors="replace")

    parser, _lang = _try_load_parser(language)
    if parser is None:
        return chunk_file_simple(file_path, language)

    tree = parser.parse(source)
    symbol_types = SYMBOL_TYPES.get(language, DEFAULT_SYMBOL_TYPES)

    chunks: list[CodeChunk] = []
    _extract_nodes(tree.root_node, source, source_text, str(file_path), language, symbol_types, chunks)
    return chunks


def _extract_nodes(
    node, source_bytes: bytes, source_text: str,
    file_path: str, language: str, symbol_types: list[str],
    chunks: list[CodeChunk], depth: int = 0,
):
    """Recursively extract symbol nodes from the AST."""
    if node.type in symbol_types:
        code = source_bytes[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
        name = _get_symbol_name(node, source_bytes)
        symbol_type = node.type.replace("_definition", "").replace("_declaration", "").replace("_item", "")

        chunks.append(CodeChunk(
            symbol_name=name,
            symbol_type=symbol_type,
            code=code,
            file_path=file_path,
            language=language,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
        ))
        # Don't recurse deeper for nested — we capture top-level symbols
        # and their full body (which includes nested defs)
        return

    for child in node.children:
        _extract_nodes(child, source_bytes, source_text, file_path, language, symbol_types, chunks, depth + 1)


def chunk_file_simple(file_path: str | Path, language: str) -> list[CodeChunk]:
    """Fallback: chunk by blank-line-separated blocks."""
    file_path = Path(file_path)
    source = file_path.read_text(errors="replace")
    lines = source.split("\n")

    chunks: list[CodeChunk] = []
    block_lines: list[str] = []
    block_start = 1

    for i, line in enumerate(lines, start=1):
        if line.strip() == "" and block_lines:
            code = "\n".join(block_lines)
            if len(code.strip()) > 20:  # Skip trivial blocks
                chunks.append(CodeChunk(
                    symbol_name=f"block_{block_start}",
                    symbol_type="block",
                    code=code,
                    file_path=str(file_path),
                    language=language,
                    line_start=block_start,
                    line_end=i - 1,
                ))
            block_lines = []
            block_start = i + 1
        else:
            block_lines.append(line)

    # Don't forget the last block
    if block_lines:
        code = "\n".join(block_lines)
        if len(code.strip()) > 20:
            chunks.append(CodeChunk(
                symbol_name=f"block_{block_start}",
                symbol_type="block",
                code=code,
                file_path=str(file_path),
                language=language,
                line_start=block_start,
                line_end=len(lines),
            ))

    return chunks


def chunk_file(file_path: str | Path, language: Optional[str] = None) -> list[CodeChunk]:
    """Main entry point: chunk a file, auto-detecting language if needed."""
    file_path = Path(file_path)
    if language is None:
        language = LANG_MAP.get(file_path.suffix, "unknown")
    if language == "unknown":
        return chunk_file_simple(file_path, language)
    return chunk_file_treesitter(file_path, language)
