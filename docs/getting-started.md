# Getting Started

This guide walks you through setting up Pattern Vault on your local machine, configuring your preferred language model backend, and running your very first code ingestion pipeline.

---

## Prerequisites

Before installing, ensure your environment meets the following specifications:

-   **Python**: Version `3.10` to `3.13` (Python `3.11` to `3.13` is required if you plan to run the legacy Chainlit interface).
-   **Node.js**: Version `20` or higher (required for the Vite + React dashboard UI).
-   **Package Manager**: We highly recommend [uv](https://github.com/astral-sh/uv) for fast, predictable Python environment management.

---

## Installation

Follow these steps to clone the repository and install the backend and frontend package dependencies.

### 1. Clone the Repository
```bash
git clone https://github.com/arunksingh16/pattern-vault.git
cd pattern-vault
```

### 2. Install Python Environment & Dependencies
Using `uv`, synchronize the virtual environment and install the required dependencies (including `web` tools for the API BFF):
```bash
uv sync --extra web
```

### 3. Install React Dashboard Dependencies
Navigate to the frontend workspace and install the NPM packages:
```bash
cd web
npm ci
cd ..
```

---

## Configure Model Backends

Pattern Vault relies on an LLM to identify, classify, and summarize reusable patterns. You can configure any of the following four provider options by setting environment variables.

=== "Direct Anthropic (Recommended)"
    Uses Anthropic's Claude models directly. Provides the highest extraction quality.

    ```bash
    export PATTERN_VAULT_BACKEND=anthropic
    export ANTHROPIC_API_KEY="your-sk-ant-api-key"
    # Optional model override (defaults to Claude 3.5 Sonnet)
    export PATTERN_VAULT_MODEL="claude-3-5-sonnet-20241022"
    ```

=== "AWS Bedrock"
    Utilizes Claude models hosted inside your AWS account. Very secure and highly compliant.

    ```bash
    export PATTERN_VAULT_BACKEND=bedrock
    export AWS_REGION="us-east-1"
    export AWS_ACCESS_KEY_ID="YOUR_ACCESS_KEY"
    export AWS_SECRET_ACCESS_KEY="YOUR_SECRET_KEY"
    # Optional session token for temporary credentials
    export AWS_SESSION_TOKEN="YOUR_SESSION_TOKEN"
    ```

=== "Bifrost"
    Proxies calls through a Bifrost endpoint wrapper. Useful for complex corporate proxy setups.

    ```bash
    export PATTERN_VAULT_BACKEND=bifrost
    export BIFROST_URL="http://localhost:8080/anthropic"
    export PATTERN_VAULT_MODEL="bedrock/eu.anthropic.claude-haiku-4-5-20251001-v1:0"
    export BIFROST_API_KEY="dummy"
    ```

=== "Local Ollama"
    Run completely local extraction using offline models. Ideal for offline work and private codebase compliance.

    ```bash
    export PATTERN_VAULT_BACKEND=ollama
    export OLLAMA_BASE_URL="http://localhost:11434/v1"
    # We recommend high-performance coder models
    export PATTERN_VAULT_MODEL="qwen2.5-coder:7b"
    ```

---

## Your First Indexing and Search

Let's test the installation by indexing a local folder (or even the Pattern Vault directory itself!) and performing an intent search.

### 1. Run a Dry-Run Indexing Job
A dry-run performs directory scanning and AST chunking *without* making any expensive LLM calls. Excellent for checking filters and file sizes:
```bash
uv run pv index ./pattern_vault --dry-run
```

### 2. Ingest the Codebase
Now run a full indexing job. We will use the `curated` profile to focus on extraction quality rather than raw volume:
```bash
uv run pv index ./pattern_vault --profile curated
```

### 3. Query the Database
Search the database by intent:
```bash
uv run pv search "FastAPI app initialization"
```

---

## Run the Custom React Dashboard

Pattern Vault comes with a premium multi-pane React dashboard. A simple unified helper script manages both the FastAPI backend and Vite frontend processes:

```bash
# Start backend (8001) and frontend (5173) in the background
./dev.sh start
```

Open [http://localhost:5173](http://localhost:5173) in your browser to view the interactive dashboard.

### Helper Lifecycle Commands:
-   **Status Check**: Check background process health and PID allocations:
    ```bash
    ./dev.sh status
    ```
-   **Restart Server**: Restart both processes:
    ```bash
    ./dev.sh restart
    ```
-   **Stop Server**: Cleanly shutdown both servers:
    ```bash
    ./dev.sh stop
    ```
