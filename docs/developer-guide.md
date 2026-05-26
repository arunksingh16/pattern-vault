# Developer & Contribution Guide

This guide is for developers looking to extend Pattern Vault, add new features, support more programming languages, or contribute back to the codebase.

---

## Code Quality Philosophy

Pattern Vault follows strict guidelines to maintain software quality and avoid bloat:
1.  **Simplicity First**: Write the minimum amount of code that fully solves the problem. No speculative features or pre-mature abstractions.
2.  **Surgical Changes**: Modify only what you must. Follow matching conventions and styles of existing files.
3.  **Local First**: Ensure features default to local, private, and lightweight configurations (e.g., SQLite FTS5 over external vector servers).

---

## 1. Database Schema & Migrations

The SQLite database initialization and schema logic reside inside `pattern_vault/store/db.py`.

### Migration Strategy
-   **Schema Version**: Managed by the `DB_VERSION` integer constant.
-   **Upgrades**: When modifying table schemas (e.g., adding a column or trigger), increment `DB_VERSION` and implement the corresponding SQL migration commands inside the `init_db()` function:

```python
# pattern_vault/store/db.py snippet
def init_db(db_path: str) -> None:
    # 1. Open connection
    # 2. Check user_version pragma
    # 3. Apply schema patches sequentially
    # 4. Update user_version pragma
```

---

## 2. Adding a New MCP Tool

Model Context Protocol (MCP) tools are exposed to external LLM clients via standard decorators in `pattern_vault/server/mcp_server.py`.

### Walkthrough
To add a new tool, define a Python function decorated with `@mcp.tool`:

```python
# pattern_vault/server/mcp_server.py
@mcp.tool()
def delete_pattern(pattern_id: str) -> str:
    """Delete a pattern from the vault by its ID.

    Args:
        pattern_id: The unique identifier of the pattern to remove.
    """
    with get_db_conn() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM patterns WHERE id = ?", (pattern_id,))
        if cursor.rowcount == 0:
            return f"Pattern {pattern_id} not found."
        conn.commit()
    return f"Pattern {pattern_id} successfully deleted."
```

*Note: The docstring and typing annotations are extremely important. MkDocs and the FastMCP compiler use them to construct JSON Schema definitions sent to the LLM agent.*

---

## 3. Adding a New Agent Tool

Agent tools are interactive modules executed by the orchestrator chat agent inside `pattern_vault/agent/orchestrator.py`. They are defined in `pattern_vault/agent/tools.py`.

### Step A: Define the Tool Schema
Add the JSON schema of your parameters to the `TOOL_DEFINITIONS` list:

```python
# pattern_vault/agent/tools.py
TOOL_DEFINITIONS = [
    # Existing tools...
    {
        "name": "delete_pattern",
        "description": "Delete a pattern from the vault database by ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern_id": {
                    "type": "string",
                    "description": "The unique identifier of the pattern."
                }
            },
            "required": ["pattern_id"]
        }
    }
]
```

### Step B: Handle the Execution
Implement the action inside the `execute_tool()` function dispatcher:

```python
# pattern_vault/agent/tools.py
def execute_tool(name: str, arguments: dict, db_path: str) -> dict:
    # Dispatchers...
    if name == "delete_pattern":
        pid = arguments["pattern_id"]
        # Delete code ...
        return {"status": "success", "message": f"Deleted pattern {pid}"}
```

---

## 4. Supporting a New Language

Pattern Vault leverages **tree-sitter AST parsing** to identify class, function, and method boundaries.

### Steps
1.  **Install tree-sitter bindings**: Add the required parser to your python dependencies (e.g., `uv add tree-sitter-go`).
2.  **Update Chunker Configuration**: Open `pattern_vault/indexer/chunker.py` and register the extension and language mapping in `LANG_MAP`:
    ```python
    LANG_MAP = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".go": "go",  # New extension
    }
    ```
3.  **Specify AST Target Node Types**: In the same file, add the relevant tree-sitter node type names in `SYMBOL_TYPES` so the chunker knows which syntax branches constitute functions and classes:
    ```python
    SYMBOL_TYPES = {
        "python": ["function_definition", "class_definition"],
        "go": ["function_declaration", "method_declaration", "type_declaration"],
    }
    ```

---

## 5. Adjusting LLM Prompts

To tune how patterns are identified and graded:
-   Edit `EXTRACTION_SYSTEM_PROMPT` in `pattern_vault/indexer/extractor.py`.
-   This system prompt guides the LLM on quality thresholds, categorisation strategies, and summary formats. Small updates here will heavily influence overall database quality.

---

## 6. Running the Test Suite

We maintain extensive pytest coverage for database CRUD, chunker boundaries, model client adaptors, and CLI commands.

### Prerequisites
Install all development-specific requirements:
```bash
uv sync --extra dev --extra web
```

### Run Linter Checks
We use **Ruff** for super-fast linting and code formatting:
```bash
uv run ruff check pattern_vault tests
```

### Run Unit Tests
Execute the unit tests using pytest:
```bash
uv run pytest
```
