# agy-auto-responder

> **Autonomous permission & prompt responder daemon for Google Antigravity CLI (`agy`) sessions on Linux.**

`agy-auto-responder` is a lightweight, zero-overhead background daemon built for developers running unattended or background `agy` agent sessions. When `agy` pauses for tool confirmations or command approvals—and standard terminal auto-inputs fail—`agy-auto-responder` dynamically detects pending prompts and safely delivers approvals.

---

## Features & Safeguards

* **Multithreaded Kernel Subprocess Inspection**:
  * Inspects `/proc/<pid>/task/*/children` in real time (<15ms per cycle).
  * Distinguishes between active subprocesses (e.g. `pytest`, `cargo`, `bash`) and idle sessions waiting for prompt confirmation, eliminating false positives during long build steps.
* **Step-Index Circuit Breaker**:
  * Tracks unique `(conversation_id, step_index)` pairs.
  * Backs off automatically after a configurable limit (default: 2 attempts) to prevent looping if a window or split pane is closed or unresponsive.
* **Dual Injection Mechanism**:
  * **Kitty Terminal**: Inspects `KITTY_WINDOW_ID` and delivers targeted keystrokes via `kitty @ send-text`.
  * **Wayland / KWin Fallback**: Traverses process ancestry to find target windows and injects approvals via `wdotool`.
* **Zero CPU & Power Consumption**:
  * Pure `/proc` filesystem polling with sub-millisecond execution.
  * Screen-saver/lock-screen inhibition via standard D-Bus calls while active.
* **Desktop & Systemd Integration**:
  * Includes a single-click desktop shortcut (`.desktop`) and `systemd --user` background controller script (`toggle_agy_auto_responder.sh`).

---

## Prerequisites

* **Linux** with `systemd` user sessions
* **Python 3.8+**
* For Wayland / KWin keystroke injection: [`wdotool`](https://github.com/gebart/wdotool)
  ```bash
  cargo install wdotool
  ```
* For Kitty terminal: remote control enabled in `kitty.conf` (optional, but recommended):
  ```conf
  allow_remote_control yes
  listen_on unix:/tmp/mykitty
  ```
* `libnotify` (`notify-send`) for desktop notifications (optional).

---

## Installation

Clone the repository and run the installer:

```bash
git clone https://github.com/SPY-Github22/agy-auto-responder.git
cd agy-auto-responder
./install.sh
```

This creates symlinks in `~/.local/bin/` and registers the desktop launcher in `~/.local/share/applications/`.

---

## Usage

### 1. Toggle Daemon via Desktop Shortcut or CLI
Use the controller script to start, stop, or toggle the daemon:

```bash
# Toggle daemon state ON/OFF
agy-toggle-auto-responder toggle

# Start daemon
agy-toggle-auto-responder start

# Check status
agy-toggle-auto-responder status

# View live logs
agy-toggle-auto-responder logs

# Stop daemon
agy-toggle-auto-responder stop
```

### 2. Run Directly in Terminal
You can also run the daemon in the foreground:

```bash
python3 agy_auto_responder.py
```

#### CLI Options:
* `--max-attempts <N>`: Maximum approval keystrokes sent per prompt before backing off (default: `2`).
* `--cooldown <SEC>`: Cooldown period between prompts in seconds (default: `3.0`).
* `--ignore-pid <PID>`: Explicit PID(s) to exclude from auto-approval.
* `--ignore-conv <ID>`: Conversation ID(s) to ignore (e.g. active supervisor sessions).

---

## Configuration & Environment Variables

| Variable | Description | Default |
| :--- | :--- | :--- |
| `AGY_LOG_FILE` | Log file destination | `~/.local/share/agy-auto-responder/agy_auto_responder.log` |
| `AGY_BRAIN_DIR` | Antigravity brain transcripts directory | `~/.gemini/antigravity-cli/brain` |
| `AGY_IGNORE_PID` | Comma-separated list of PIDs to ignore | _None_ |
| `AGY_IGNORE_CONV` | Comma-separated list of conversation IDs to ignore | _None_ |

---

## Alternative: Native Permission Bypassing

If you are running `agy` sessions directly in an isolated container, VM, or environment where full permission bypassing is acceptable without running an external watcher daemon, you can alternatively launch `agy` with the native flag:

```bash
agy --dangerously-skip-permissions
```

---

## License

[MIT](LICENSE)
