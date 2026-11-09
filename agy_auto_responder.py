#!/usr/bin/env python3
"""
Universal Antigravity CLI Prompt Auto-Approver Daemon (Production-Grade, Anti-Spam)

Key Safeguards & Architecture:
1. Multithreaded kernel inspection:
   - Scans /proc/<pid>/task/*/children so child commands (bash, cargo, pytest, systemctl)
     spawned by async worker threads are accurately detected without false positives.
2. Step-Index Circuit Breaker (Anti-Spam):
   - Tracks unique (conv_id, step_index) pairs.
   - Max attempts per prompt (default: 2). If a window or background Kitty split pane does not
     advance after max attempts, the daemon backs off immediately instead of looping.
3. Dynamic Exclusion & Filters:
   - Dynamic exclusion via CLI args (--ignore-conv, --ignore-pid) and environment variables
     (AGY_IGNORE_CONV, AGY_IGNORE_PID).
4. Terminal & Kitty Remote Control Support:
   - Detects Kitty child windows (KITTY_WINDOW_ID) and attempts targeted injection via
     `kitty @ send-text` if remote control is available, with graceful fallback to wdotool.
5. Zero CPU overhead:
   - Pure /proc kernel reads (<15ms per cycle, ~0.0% CPU).
"""

import os
import sys
import time
import json
import glob
import shutil
import argparse
import subprocess
import logging
from typing import Dict, List, Tuple, Optional, Set

# Dynamic configuration & paths
LOG_FILE = os.environ.get(
    "AGY_LOG_FILE",
    os.path.expanduser("~/.local/share/agy-auto-responder/agy_auto_responder.log")
)
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a"),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("agy_auto_responder")

# Dynamic binary resolution for wdotool
def resolve_wdotool() -> Optional[str]:
    which_bin = shutil.which("wdotool")
    if which_bin and os.path.exists(which_bin):
        return which_bin
    cargo_bin = os.path.expanduser("~/.cargo/bin/wdotool")
    if os.path.exists(cargo_bin):
        return cargo_bin
    return None

WDOTOOL_BIN = resolve_wdotool()
BRAIN_DIR = os.environ.get(
    "AGY_BRAIN_DIR",
    os.path.expanduser("~/.gemini/antigravity-cli/brain")
)

def parse_args():
    parser = argparse.ArgumentParser(description="Zero-Lag Antigravity CLI Auto-Approver Daemon")
    parser.add_argument("--ignore-pid", type=int, action="append", default=[], help="PID(s) of agy sessions to ignore")
    parser.add_argument("--ignore-conv", type=str, action="append", default=[], help="Conversation ID(s) to ignore")
    parser.add_argument("--max-attempts", type=int, default=2, help="Max approval attempts per prompt before backing off")
    parser.add_argument("--cooldown", type=float, default=3.0, help="Cooldown in seconds between attempts")
    return parser.parse_args()

def acquire_screensaver_inhibit() -> Optional[int]:
    """Inhibits screen locking/sleep via D-Bus."""
    try:
        cookie_str = subprocess.check_output(
            [
                "qdbus",
                "org.freedesktop.ScreenSaver",
                "/ScreenSaver",
                "org.freedesktop.ScreenSaver.Inhibit",
                "Antigravity Auto-Approver",
                "Permission Auto-Approval"
            ],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if cookie_str.isdigit():
            logger.info("ScreenSaver sleep inhibition active (Cookie: %s)", cookie_str)
            return int(cookie_str)
    except Exception as e:
        logger.debug("Could not acquire D-Bus screensaver inhibit: %s", e)
    return None

def get_ancestors(pid: int) -> Set[int]:
    """Gets all ancestor PIDs of a process via /proc."""
    ancestors = set()
    curr = pid
    while curr > 1 and curr not in ancestors:
        ancestors.add(curr)
        try:
            with open(f"/proc/{curr}/stat", "r") as f:
                stat = f.read().split()
            curr = int(stat[3])
        except Exception:
            break
    return ancestors

def find_window_for_pid(agy_pid: int) -> Optional[str]:
    """Walks up ancestor tree to find the terminal window UUID in KWin via wdotool."""
    if not WDOTOOL_BIN or not os.path.exists(WDOTOOL_BIN):
        return None

    curr = agy_pid
    visited = set()
    while curr > 1 and curr not in visited:
        visited.add(curr)
        try:
            with open(f"/proc/{curr}/stat", "r") as f:
                stat = f.read().split()
            ppid = int(stat[3])
        except Exception:
            break

        try:
            res = subprocess.run([WDOTOOL_BIN, "search", "--pid", str(curr)], capture_output=True, text=True, timeout=2)
            for line in res.stdout.splitlines():
                line = line.strip()
                if line.startswith("{"):
                    return line.split()[0]
        except Exception:
            pass

        curr = ppid
    return None

def get_kitty_window_id(agy_pid: int) -> Optional[str]:
    """Reads KITTY_WINDOW_ID from environment of process or its immediate shell parent."""
    for check_pid in [agy_pid]:
        try:
            with open(f"/proc/{check_pid}/stat", "r") as f:
                ppid = int(f.read().split()[3])
            pids_to_check = [check_pid, ppid]
        except Exception:
            pids_to_check = [check_pid]

        for p in pids_to_check:
            try:
                with open(f"/proc/{p}/environ", "rb") as ef:
                    env_bytes = ef.read()
                for item in env_bytes.split(b"\0"):
                    if item.startswith(b"KITTY_WINDOW_ID="):
                        return item.decode("utf-8", errors="ignore").split("=", 1)[1]
            except Exception:
                continue
    return None

def get_active_agy_sessions(ignore_pids: Set[int], ignore_convs: Set[str]) -> Dict[int, str]:
    """
    Finds running agy processes and their active conversation IDs by reading
    /proc/<pid>/fd directly (ZERO process forks, sub-millisecond speed).
    """
    sessions = {}
    my_ancestors = get_ancestors(os.getpid())
    combined_ignore_pids = ignore_pids.union(my_ancestors)

    for p in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(os.path.basename(p))
            if pid in combined_ignore_pids:
                continue

            with open(f"/proc/{pid}/cmdline", "rb") as cf:
                cmd = cf.read().decode("utf-8", errors="ignore")

            # Must be agy CLI binary
            if "agy" in cmd and "python" not in cmd and "grep" not in cmd and "bash" not in cmd:
                # Find the open presence lock file descriptor directly
                for fd in glob.glob(f"/proc/{pid}/fd/*"):
                    try:
                        target = os.readlink(fd)
                        if "presence/" in target and target.endswith(".lock"):
                            conv_id = os.path.basename(target)[:-5]
                            # Check ignore conversation filters
                            if any(conv_id.startswith(ic) or ic.startswith(conv_id) for ic in ignore_convs if ic):
                                break
                            sessions[pid] = conv_id
                            break
                    except Exception:
                        pass
        except Exception:
            pass

    return sessions

def has_running_command(agy_pid: int) -> bool:
    """
    Checks ALL thread children under /proc/<pid>/task/*/children directly (<1ms read).
    Fixes the multithreading bug where worker threads spawn subprocesses.
    """
    try:
        task_dir = f"/proc/{agy_pid}/task"
        if not os.path.exists(task_dir):
            return False

        for task_entry in os.scandir(task_dir):
            if not task_entry.is_dir():
                continue
            children_file = os.path.join(task_entry.path, "children")
            if not os.path.exists(children_file):
                continue
            try:
                with open(children_file, "r") as f:
                    children = f.read().split()

                for c_str in children:
                    if not c_str.isdigit():
                        continue
                    cpid = int(c_str)
                    try:
                        with open(f"/proc/{cpid}/cmdline", "rb") as cf:
                            ccmd = cf.read().decode("utf-8", errors="ignore")
                        # Ignore persistent background MCP servers & helper tools
                        if not any(k in ccmd for k in ["codebase-memory", "blender-mcp", "uv tool", "uvx", "wdotool"]):
                            return True
                    except Exception:
                        pass
            except Exception:
                pass
    except Exception:
        pass
    return False

def is_session_waiting_for_input(conv_id: str, agy_pid: int) -> Tuple[bool, bool, str, int]:
    """
    Checks if an agy session is waiting for approval without any process forks.
    Returns: (is_waiting, is_mcp, summary, step_index)
    """
    transcript_path = os.path.join(BRAIN_DIR, conv_id, ".system_generated", "logs", "transcript.jsonl")
    if not os.path.exists(transcript_path):
        return False, False, "", -1

    try:
        with open(transcript_path, "r", errors="ignore") as f:
            lines = f.readlines()
        if not lines:
            return False, False, "", -1

        last = json.loads(lines[-1])
        if last.get("type") != "PLANNER_RESPONSE" or not last.get("tool_calls"):
            return False, False, "", -1

        step_index = last.get("step_index", -1)

        # If a non-MCP child command process is actively running, it's busy executing
        if has_running_command(agy_pid):
            return False, False, "", step_index

        tool_calls = last.get("tool_calls", [])
        tool_names = [tc.get("name", "") for tc in tool_calls]
        is_mcp = any("mcp" in tn.lower() for tn in tool_names)

        summary_parts = []
        for tc in tool_calls:
            name = tc.get("name", "tool")
            args = tc.get("args", {})
            if isinstance(args, dict):
                cmd_arg = args.get("CommandLine") or args.get("Path") or args.get("toolSummary") or ""
                summary_parts.append(f"{name}({str(cmd_arg)[:35]})")
            else:
                summary_parts.append(name)

        return True, is_mcp, ", ".join(summary_parts) or "Permission Request", step_index

    except Exception as e:
        logger.debug("Error checking transcript for %s: %s", conv_id, e)
        return False, False, "", -1

def approve_window(window_id: str, is_mcp: bool, kitty_win_id: Optional[str] = None):
    """
    Delivers approval keystrokes.
    Prioritizes kitty remote control if available, otherwise safely activates window.
    """
    # Try Kitty targeted injection first if Kitty window ID is known
    if kitty_win_id:
        try:
            cmd = ["kitty", "@", "send-text", f"--match=id:{kitty_win_id}", "\x0b\r" if is_mcp else "\r"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
            if res.returncode == 0:
                logger.debug("Delivered approval via Kitty remote control to window %s", kitty_win_id)
                return
        except Exception:
            pass

    if not WDOTOOL_BIN or not os.path.exists(WDOTOOL_BIN) or not window_id:
        return

    active_win = None
    try:
        active_win = subprocess.check_output([WDOTOOL_BIN, "getactivewindow"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        pass

    try:
        # If the target window is not active, switch focus and restore after
        if active_win and active_win != window_id:
            subprocess.run([WDOTOOL_BIN, "windowactivate", window_id], stderr=subprocess.DEVNULL, timeout=2)
            time.sleep(0.05)

        if is_mcp:
            subprocess.run([WDOTOOL_BIN, "key", "ctrl+k"], capture_output=True, text=True, timeout=2)
            time.sleep(0.04)

        subprocess.run([WDOTOOL_BIN, "key", "Return"], capture_output=True, text=True, timeout=2)
        time.sleep(0.04)

        if active_win and active_win != window_id:
            subprocess.run([WDOTOOL_BIN, "windowactivate", active_win], stderr=subprocess.DEVNULL, timeout=2)
    except Exception as e:
        logger.error("Error approving window %s: %s", window_id, e)

def main_loop():
    args = parse_args()

    ignore_pids = set(args.ignore_pid)
    env_ignore_pid = os.environ.get("AGY_IGNORE_PID")
    if env_ignore_pid:
        for p in env_ignore_pid.split(","):
            if p.strip().isdigit():
                ignore_pids.add(int(p.strip()))

    ignore_convs = set()
    ignore_convs.update(args.ignore_conv)
    env_ignore_conv = os.environ.get("AGY_IGNORE_CONV")
    if env_ignore_conv:
        for c in env_ignore_conv.split(","):
            if c.strip():
                ignore_convs.add(c.strip())

    logger.info("Starting Antigravity CLI Auto-Approver Daemon (PID: %d)...", os.getpid())
    if ignore_convs:
        logger.info("Excluding supervisor/specified conversations: %s", ", ".join(list(ignore_convs)[:3]))
    acquire_screensaver_inhibit()

    window_cache: Dict[int, str] = {}
    kitty_cache: Dict[int, Optional[str]] = {}
    step_attempts: Dict[Tuple[str, int], int] = {}
    last_attempt_time: Dict[str, float] = {}

    while True:
        try:
            now = time.time()
            sessions = get_active_agy_sessions(ignore_pids, ignore_convs)

            # Purge dead sessions from caches
            dead_pids = [p for p in window_cache if p not in sessions]
            for dp in dead_pids:
                window_cache.pop(dp, None)
                kitty_cache.pop(dp, None)

            # Clean stale step attempts (keep only active sessions)
            active_convs = set(sessions.values())
            dead_keys = [k for k in step_attempts if k[0] not in active_convs]
            for dk in dead_keys:
                step_attempts.pop(dk, None)

            for agy_pid, conv_id in sessions.items():
                conv_key = f"conv:{conv_id}"

                # Enforce cooldown per conversation
                if conv_key in last_attempt_time and (now - last_attempt_time[conv_key]) < args.cooldown:
                    continue

                is_waiting, is_mcp, summary, step_index = is_session_waiting_for_input(conv_id, agy_pid)
                if not is_waiting or step_index < 0:
                    continue

                attempt_key = (conv_id, step_index)
                current_attempts = step_attempts.get(attempt_key, 0)

                # Circuit breaker: max attempts reached, back off to avoid spamming
                if current_attempts >= args.max_attempts:
                    if current_attempts == args.max_attempts:
                        logger.warning(
                            "Step %d for session %s exceeded max attempts (%d). "
                            "Window or split pane is likely inactive/unfocused. Backing off.",
                            step_index, conv_id[:8], args.max_attempts
                        )
                        step_attempts[attempt_key] = current_attempts + 1
                    continue

                win_id = window_cache.get(agy_pid)
                if not win_id:
                    win_id = find_window_for_pid(agy_pid)
                    if win_id:
                        window_cache[agy_pid] = win_id

                kitty_win_id = kitty_cache.get(agy_pid)
                if agy_pid not in kitty_cache:
                    kitty_win_id = get_kitty_window_id(agy_pid)
                    kitty_cache[agy_pid] = kitty_win_id

                if win_id:
                    logger.info(
                        "Prompt in PID %d (%s, step %d, win %s, attempt %d/%d): %s",
                        agy_pid, conv_id[:8], step_index, win_id, current_attempts + 1, args.max_attempts, summary
                    )
                    approve_window(win_id, is_mcp, kitty_win_id)
                    last_attempt_time[conv_key] = time.time()
                    step_attempts[attempt_key] = current_attempts + 1
                    logger.info("==> [APPROVED] Sent %s to window %s", "ctrl+k" if is_mcp else "Enter", win_id)

        except Exception as e:
            logger.debug("Loop exception: %s", e)

        time.sleep(1.0)

if __name__ == "__main__":
    main_loop()
