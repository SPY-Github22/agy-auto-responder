#!/usr/bin/env bash
# Quick Installer for AGY Auto-Responder

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

echo "[*] Installing AGY Auto-Responder..."

mkdir -p "$BIN_DIR"
mkdir -p "$APP_DIR"

# Symlink or copy binaries to ~/.local/bin
ln -sf "$SCRIPT_DIR/agy_auto_responder.py" "$BIN_DIR/agy-auto-responder"
ln -sf "$SCRIPT_DIR/toggle_agy_auto_responder.sh" "$BIN_DIR/agy-toggle-auto-responder"

chmod +x "$SCRIPT_DIR/agy_auto_responder.py"
chmod +x "$SCRIPT_DIR/toggle_agy_auto_responder.sh"

# Install desktop shortcut
cp "$SCRIPT_DIR/agy-auto-responder.desktop" "$APP_DIR/agy-auto-responder.desktop"
chmod +x "$APP_DIR/agy-auto-responder.desktop"
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APP_DIR" || true

echo "[+] Installation complete!"
echo "    - CLI daemon: agy-auto-responder"
echo "    - Toggle script: agy-toggle-auto-responder [start|stop|toggle|status|logs]"
echo "    - Desktop entry installed to $APP_DIR/agy-auto-responder.desktop"
