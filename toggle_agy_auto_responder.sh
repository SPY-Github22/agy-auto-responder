#!/usr/bin/env bash
# AGY Auto-Responder Desktop Controller / Launcher

set -euo pipefail

ACTION="${1:-toggle}"
UNIT="agy-auto-responder.service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${AGY_RESPONDER_BIN:-$SCRIPT_DIR/agy_auto_responder.py}"
LOG="${AGY_LOG_FILE:-$HOME/.local/share/agy-auto-responder/agy_auto_responder.log}"

# Ensure cargo/local binaries are in PATH
export PATH="$HOME/.cargo/bin:$HOME/.local/bin:$PATH"

mkdir -p "$(dirname "$LOG")"

is_active() {
    systemctl --user is-active --quiet "$UNIT"
}

start_service() {
    systemctl --user stop "$UNIT" 2>/dev/null || true
    systemctl --user reset-failed "$UNIT" 2>/dev/null || true
    systemd-run --user --unit=agy-auto-responder python3 "$SCRIPT"
    sleep 0.8
    if is_active; then
        command -v notify-send >/dev/null 2>&1 && notify-send -i media-playback-start \
            -a "AGY Auto-Responder" \
            "AGY Auto-Responder ON" \
            "Actively auto-approving prompts across Kitty, Konsole & all agy chats." || true
        echo "[+] AGY Auto-Responder started successfully."
    else
        command -v notify-send >/dev/null 2>&1 && notify-send -i dialog-error \
            -a "AGY Auto-Responder" \
            "Failed to Start" \
            "Check $LOG for details." || true
        echo "[-] Failed to start AGY Auto-Responder. Check $LOG."
        exit 1
    fi
}

stop_service() {
    systemctl --user stop "$UNIT" 2>/dev/null || true
    systemctl --user reset-failed "$UNIT" 2>/dev/null || true
    command -v notify-send >/dev/null 2>&1 && notify-send -i media-playback-stop \
        -a "AGY Auto-Responder" \
        "AGY Auto-Responder OFF" \
        "Auto-approval daemon has been stopped." || true
    echo "[+] AGY Auto-Responder stopped."
}

case "$ACTION" in
    start)
        start_service
        ;;
    stop)
        if is_active; then
            stop_service
        else
            command -v notify-send >/dev/null 2>&1 && notify-send -i dialog-information \
                -a "AGY Auto-Responder" \
                "Already Stopped" \
                "AGY Auto-Responder is not running." || true
            echo "[*] AGY Auto-Responder is already stopped."
        fi
        ;;
    restart)
        start_service
        ;;
    toggle)
        if is_active; then
            stop_service
        else
            start_service
        fi
        ;;
    status)
        if is_active; then
            command -v notify-send >/dev/null 2>&1 && notify-send -i media-playback-start \
                -a "AGY Auto-Responder" \
                "Status: Active" \
                "Daemon is running." || true
            echo "[*] Status: ACTIVE"
        else
            command -v notify-send >/dev/null 2>&1 && notify-send -i media-playback-stop \
                -a "AGY Auto-Responder" \
                "Status: Inactive" \
                "Daemon is stopped." || true
            echo "[*] Status: INACTIVE"
        fi
        ;;
    logs)
        tail -n 50 -f "$LOG"
        ;;
    *)
        echo "Usage: $0 [start|stop|restart|toggle|status|logs]"
        exit 1
        ;;
esac
