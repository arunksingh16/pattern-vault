#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${PATTERN_VAULT_STATE_DIR:-$ROOT_DIR/.temp/backend}"
PID_FILE="$STATE_DIR/backend.pid"
LOG_FILE="$STATE_DIR/backend.log"
APP_MODULE="${PATTERN_VAULT_APP_MODULE:-pattern_vault.api.main:app}"
HOST="${PATTERN_VAULT_API_HOST:-127.0.0.1}"
PORT="${PATTERN_VAULT_API_PORT:-8001}"
DEFAULT_PYTHON_BIN="$ROOT_DIR/venv/bin/python"
if [[ ! -x "$DEFAULT_PYTHON_BIN" && -x "$ROOT_DIR/.venv/bin/python" ]]; then
    DEFAULT_PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
fi
if [[ ! -x "$DEFAULT_PYTHON_BIN" ]]; then
    DEFAULT_PYTHON_BIN="python"
    if ! command -v "$DEFAULT_PYTHON_BIN" >/dev/null 2>&1 && command -v python3 >/dev/null 2>&1; then
        DEFAULT_PYTHON_BIN="python3"
    fi
fi
PYTHON_BIN="${PATTERN_VAULT_PYTHON_BIN:-$DEFAULT_PYTHON_BIN}"

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|stop|restart|status}

Environment overrides:
  PATTERN_VAULT_PYTHON_BIN  Python executable to use (default: python)
  PATTERN_VAULT_API_HOST    Host to bind (default: 127.0.0.1)
  PATTERN_VAULT_API_PORT    Port to bind (default: 8001)
  PATTERN_VAULT_STATE_DIR   Directory for pid/log files (default: .temp/backend)
  PATTERN_VAULT_APP_MODULE  Uvicorn app module (default: pattern_vault.api.main:app)
EOF
}

ensure_state_dir() {
    mkdir -p "$STATE_DIR"
}

command_for_pid() {
    local pid="$1"
    ps -p "$pid" -o command= 2>/dev/null || true
}

pid_is_running() {
    local pid="$1"
    kill -0 "$pid" 2>/dev/null
}

pid_matches_backend() {
    local pid="$1"
    local cmd
    cmd="$(command_for_pid "$pid")"
    [[ -n "$cmd" && "$cmd" == *"$APP_MODULE"* ]]
}

read_pid_file() {
    [[ -f "$PID_FILE" ]] || return 1
    tr -d '[:space:]' < "$PID_FILE"
}

cleanup_stale_pid_file() {
    local pid="${1:-}"
    if [[ -n "$pid" && ! -f "$PID_FILE" ]]; then
        return
    fi

    if [[ -z "$pid" ]]; then
        pid="$(read_pid_file 2>/dev/null || true)"
    fi

    if [[ -n "$pid" && ! $(pid_is_running "$pid"; echo $?) -eq 0 ]]; then
        rm -f "$PID_FILE"
    fi
}

port_listener_pid() {
    lsof -tiTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
}

managed_backend_pid() {
    local pid
    pid="$(read_pid_file 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_is_running "$pid" && pid_matches_backend "$pid"; then
        echo "$pid"
        return 0
    fi

    cleanup_stale_pid_file "$pid"

    pid="$(port_listener_pid || true)"
    if [[ -n "$pid" ]] && pid_matches_backend "$pid"; then
        echo "$pid"
        return 0
    fi

    return 1
}

assert_runtime_ready() {
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        echo "Python executable not found: $PYTHON_BIN" >&2
        exit 1
    fi

    if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
        echo "uvicorn is not available for $PYTHON_BIN" >&2
        exit 1
    fi
}

print_status() {
    local pid
    pid="$(managed_backend_pid || true)"
    if [[ -n "$pid" ]]; then
        echo "Pattern Vault backend is running"
        echo "PID: $pid"
        echo "URL: http://$HOST:$PORT"
        echo "Log: $LOG_FILE"
        return 0
    fi

    local port_pid
    port_pid="$(port_listener_pid || true)"
    if [[ -n "$port_pid" ]]; then
        echo "Port $PORT is in use by a different process (PID $port_pid)"
        echo "Command: $(command_for_pid "$port_pid")"
        return 1
    fi

    echo "Pattern Vault backend is not running"
    echo "Expected URL: http://$HOST:$PORT"
    echo "Log: $LOG_FILE"
}

start_backend() {
    local pid
    pid="$(managed_backend_pid || true)"
    if [[ -n "$pid" ]]; then
        echo "Pattern Vault backend is already running (PID $pid)"
        echo "URL: http://$HOST:$PORT"
        return 0
    fi

    local port_pid
    port_pid="$(port_listener_pid || true)"
    if [[ -n "$port_pid" ]]; then
        echo "Cannot start backend: port $PORT is already used by PID $port_pid" >&2
        echo "Command: $(command_for_pid "$port_pid")" >&2
        exit 1
    fi

    assert_runtime_ready
    ensure_state_dir

    (
        cd "$ROOT_DIR"
        nohup "$PYTHON_BIN" -m uvicorn "$APP_MODULE" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
    )

    pid="$(read_pid_file)"
    for _ in {1..20}; do
        if pid_is_running "$pid" && [[ -n "$(port_listener_pid || true)" ]]; then
            echo "Pattern Vault backend started"
            echo "PID: $pid"
            echo "URL: http://$HOST:$PORT"
            echo "Log: $LOG_FILE"
            return 0
        fi
        if ! pid_is_running "$pid"; then
            break
        fi
        sleep 0.25
    done

    echo "Backend failed to start. Recent log output:" >&2
    if [[ -f "$LOG_FILE" ]]; then
        tail -n 20 "$LOG_FILE" >&2
    fi
    rm -f "$PID_FILE"
    exit 1
}

stop_backend() {
    local pid
    pid="$(managed_backend_pid || true)"
    if [[ -z "$pid" ]]; then
        echo "Pattern Vault backend is not running"
        return 0
    fi

    kill "$pid"
    for _ in {1..20}; do
        if ! pid_is_running "$pid"; then
            rm -f "$PID_FILE"
            echo "Pattern Vault backend stopped"
            return 0
        fi
        sleep 0.25
    done

    kill -9 "$pid" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "Pattern Vault backend force-stopped"
}

restart_backend() {
    stop_backend
    start_backend
}

case "${1:-}" in
    start)
        start_backend
        ;;
    stop)
        stop_backend
        ;;
    restart)
        restart_backend
        ;;
    status)
        print_status
        ;;
    *)
        usage
        exit 1
        ;;
esac
