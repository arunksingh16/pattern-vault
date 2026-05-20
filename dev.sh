#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_SCRIPT="$ROOT_DIR/backend.sh"
FRONTEND_DIR="$ROOT_DIR/web"
FRONTEND_HOST="${PATTERN_VAULT_FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${PATTERN_VAULT_FRONTEND_PORT:-5173}"
STATE_DIR="${PATTERN_VAULT_DEV_STATE_DIR:-$ROOT_DIR/.temp/dev}"
FRONTEND_PID_FILE="$STATE_DIR/frontend.pid"
FRONTEND_LOG_FILE="$STATE_DIR/frontend.log"
VITE_BIN="$FRONTEND_DIR/node_modules/.bin/vite"

usage() {
    cat <<EOF
Usage: $(basename "$0") {start|stop|restart|status}

Environment overrides:
  PATTERN_VAULT_FRONTEND_HOST  Host to bind Vite to (default: 127.0.0.1)
  PATTERN_VAULT_FRONTEND_PORT  Port to bind Vite to (default: 5173)
  PATTERN_VAULT_DEV_STATE_DIR  Directory for frontend pid/log files (default: .temp/dev)
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

frontend_matches_process() {
    local pid="$1"
    local cmd
    cmd="$(command_for_pid "$pid")"
    [[ -n "$cmd" && "$cmd" == *"vite"* && "$cmd" == *"$FRONTEND_PORT"* ]]
}

read_pid_file() {
    [[ -f "$FRONTEND_PID_FILE" ]] || return 1
    tr -d '[:space:]' < "$FRONTEND_PID_FILE"
}

cleanup_stale_pid_file() {
    local pid="${1:-}"
    if [[ -z "$pid" ]]; then
        pid="$(read_pid_file 2>/dev/null || true)"
    fi

    if [[ -n "$pid" ]] && ! pid_is_running "$pid"; then
        rm -f "$FRONTEND_PID_FILE"
    fi
}

frontend_port_pid() {
    lsof -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN 2>/dev/null | head -n 1
}

managed_frontend_pid() {
    local pid
    pid="$(read_pid_file 2>/dev/null || true)"
    if [[ -n "$pid" ]] && pid_is_running "$pid" && frontend_matches_process "$pid"; then
        echo "$pid"
        return 0
    fi

    cleanup_stale_pid_file "$pid"

    pid="$(frontend_port_pid || true)"
    if [[ -n "$pid" ]] && frontend_matches_process "$pid"; then
        echo "$pid"
        return 0
    fi

    return 1
}

assert_frontend_ready() {
    if [[ ! -x "$VITE_BIN" ]]; then
        echo "Vite is not installed. Run 'cd web && npm install' first." >&2
        exit 1
    fi
}

start_frontend() {
    local pid
    pid="$(managed_frontend_pid || true)"
    if [[ -n "$pid" ]]; then
        echo "Pattern Vault frontend is already running (PID $pid)"
        echo "URL: http://$FRONTEND_HOST:$FRONTEND_PORT"
        return 0
    fi

    local port_pid
    port_pid="$(frontend_port_pid || true)"
    if [[ -n "$port_pid" ]]; then
        echo "Cannot start frontend: port $FRONTEND_PORT is already used by PID $port_pid" >&2
        echo "Command: $(command_for_pid "$port_pid")" >&2
        exit 1
    fi

    assert_frontend_ready
    ensure_state_dir

    (
        cd "$FRONTEND_DIR"
        nohup "$VITE_BIN" --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" > "$FRONTEND_LOG_FILE" 2>&1 &
        echo $! > "$FRONTEND_PID_FILE"
    )

    pid="$(read_pid_file)"
    for _ in {1..20}; do
        if pid_is_running "$pid" && [[ -n "$(frontend_port_pid || true)" ]]; then
            echo "Pattern Vault frontend started"
            echo "PID: $pid"
            echo "URL: http://$FRONTEND_HOST:$FRONTEND_PORT"
            echo "Log: $FRONTEND_LOG_FILE"
            return 0
        fi
        if ! pid_is_running "$pid"; then
            break
        fi
        sleep 0.25
    done

    echo "Frontend failed to start. Recent log output:" >&2
    if [[ -f "$FRONTEND_LOG_FILE" ]]; then
        tail -n 20 "$FRONTEND_LOG_FILE" >&2
    fi
    rm -f "$FRONTEND_PID_FILE"
    exit 1
}

stop_frontend() {
    local pid
    pid="$(managed_frontend_pid || true)"
    if [[ -z "$pid" ]]; then
        echo "Pattern Vault frontend is not running"
        return 0
    fi

    kill "$pid"
    for _ in {1..20}; do
        if ! pid_is_running "$pid"; then
            rm -f "$FRONTEND_PID_FILE"
            echo "Pattern Vault frontend stopped"
            return 0
        fi
        sleep 0.25
    done

    kill -9 "$pid" 2>/dev/null || true
    rm -f "$FRONTEND_PID_FILE"
    echo "Pattern Vault frontend force-stopped"
}

print_status() {
    local backend_status=0
    local frontend_status=0

    echo "Backend:"
    if ! "$BACKEND_SCRIPT" status; then
        backend_status=1
    fi

    echo
    echo "Frontend:"
    local frontend_pid
    frontend_pid="$(managed_frontend_pid || true)"
    if [[ -n "$frontend_pid" ]]; then
        echo "Pattern Vault frontend is running"
        echo "PID: $frontend_pid"
        echo "URL: http://$FRONTEND_HOST:$FRONTEND_PORT"
        echo "Log: $FRONTEND_LOG_FILE"
    else
        local port_pid
        port_pid="$(frontend_port_pid || true)"
        if [[ -n "$port_pid" ]]; then
            echo "Port $FRONTEND_PORT is in use by a different process (PID $port_pid)"
            echo "Command: $(command_for_pid "$port_pid")"
            frontend_status=1
        else
            echo "Pattern Vault frontend is not running"
            echo "Expected URL: http://$FRONTEND_HOST:$FRONTEND_PORT"
            echo "Log: $FRONTEND_LOG_FILE"
        fi
    fi

    if [[ "$backend_status" -ne 0 || "$frontend_status" -ne 0 ]]; then
        return 1
    fi
}

start_stack() {
    "$BACKEND_SCRIPT" start
    if ! start_frontend; then
        "$BACKEND_SCRIPT" stop || true
        exit 1
    fi

    echo
    echo "Pattern Vault dev stack is ready"
    echo "Backend:  http://127.0.0.1:${PATTERN_VAULT_API_PORT:-8001}"
    echo "Frontend: http://$FRONTEND_HOST:$FRONTEND_PORT"
}

stop_stack() {
    local frontend_status=0
    local backend_status=0

    if ! stop_frontend; then
        frontend_status=1
    fi

    if ! "$BACKEND_SCRIPT" stop; then
        backend_status=1
    fi

    if [[ "$frontend_status" -ne 0 || "$backend_status" -ne 0 ]]; then
        return 1
    fi
}

restart_stack() {
    stop_stack
    start_stack
}

case "${1:-}" in
    start)
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    restart)
        restart_stack
        ;;
    status)
        print_status
        ;;
    *)
        usage
        exit 1
        ;;
esac
