#!/usr/bin/env python3
"""
TenAgent Terminal Stream Runner & Logger (v1.0.1)
Pipes live CLI execution output directly to the TenAgent Virtual Office Monitor
in real-time (sub-second streaming).

Usage:
  1. Command Wrapper (runs any command and streams stdout/stderr live):
     python stream.py "npm run build"
     python stream.py run 05_backend "npm install express"
     stream.bat "pytest"

  2. Pipe Mode (streams piped stdout from any process):
     npm test | python stream.py pipe 07_qa
     dir | python stream.py pipe

  3. Quick Agent Log (instantly logs a line and syncs agent processDetail):
     python stream.py log 05_backend "Creating user entity in domain layer"
     python stream.py log 04_dba "Running 3NF migration" --status WORKING --progress 80

  4. Interactive Shell (launches monitored shell):
     python stream.py shell
     stream.bat
"""

import sys
import os
import re
import json
import time
import datetime
import subprocess
import argparse
import tempfile

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    from swarm_pipeline import atomic_write_text as _atomic_write_text
except Exception:  # keep the logger usable even if the pipeline module cannot be imported
    def _atomic_write_text(path, text):
        """Minimal fallback: unique temp file, replace, brief retry while a reader holds the target."""
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), prefix=os.path.basename(path) + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            for attempt in range(6):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(0.02 * (attempt + 1))
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
SPECS_DIR = os.path.join(ROOT_DIR, "specs")
LOG_FILE = os.path.join(SPECS_DIR, "terminal.log")
STATUS_FILE = os.path.join(SPECS_DIR, "swarm-status.json")

# Regex to strip ANSI escape sequences for clean web rendering
ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

# Known 10 agent IDs
VALID_AGENTS = {
    "01_pm", "02_arch", "03_designer", "04_dba", "05_backend",
    "06_client", "07_qa", "08_security", "09_devops", "10_tech_lead"
}

# Heuristic keywords for auto-detecting agents from output if not explicitly tagged
KEYWORD_AGENT_MAP = [
    (re.compile(r'\b(schema\.sql|sql|migration|database|data-dictionary|3nf)\b', re.I), "04_dba"),
    (re.compile(r'\b(prd|user stor|requirements|discovery)\b', re.I), "01_pm"),
    (re.compile(r'\b(architecture|adr-|clean architecture|layer boundary)\b', re.I), "02_arch"),
    (re.compile(r'\b(contrast|token|figma|wireframe|css|svg|design)\b', re.I), "03_designer"),
    (re.compile(r'\b(backend|express|fastapi|controller|endpoint|entity|service)\b', re.I), "05_backend"),
    (re.compile(r'\b(frontend|mobile|flutter|react|screen|client|ui component)\b', re.I), "06_client"),
    (re.compile(r'\b(test|pytest|jest|qa|test-matrix|spec\.ts)\b', re.I), "07_qa"),
    (re.compile(r'\b(security|owasp|vulnerability|audit-report|token leak)\b', re.I), "08_security"),
    (re.compile(r'\b(docker|dockerfile|container|ci/cd|\.github|deploy)\b', re.I), "09_devops"),
    (re.compile(r'\b(gatekeeper|quality gate|review|signoff|tech lead)\b', re.I), "10_tech_lead"),
]

def clean_ansi(text: str) -> str:
    return ANSI_REGEX.sub('', text)

def get_timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")

def ensure_specs_dir():
    os.makedirs(SPECS_DIR, exist_ok=True)

def append_terminal_log(agent_id: str, message: str):
    ensure_specs_dir()
    clean_msg = clean_ansi(message).strip()
    if not clean_msg:
        return

    ts = get_timestamp()
    tag = agent_id if agent_id in VALID_AGENTS else "cli"
    log_line = f"[{ts}] [{tag}] {clean_msg}\n"

    try:
        # Check size to rotate if > 500KB (keep last 1000 lines)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 500 * 1024:
            with open(LOG_FILE, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            with open(LOG_FILE, "w", encoding="utf-8") as f:
                f.writelines(lines[-800:])

        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
            f.flush()
    except Exception as e:
        # Never crash the main process on logging failure
        pass

def update_agent_status(agent_id: str, process_detail: str, status: str = None, progress: int = None):
    if not os.path.exists(STATUS_FILE) or agent_id not in VALID_AGENTS:
        return

    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        agent_found = False
        clean_detail = clean_ansi(process_detail).strip()

        for a in data.get("agents", []):
            if a.get("id") == agent_id:
                agent_found = True
                if clean_detail:
                    a["processDetail"] = clean_detail
                if status:
                    a["status"] = status
                elif a.get("status") in ("WAITING", "IDLE"):
                    a["status"] = "WORKING"
                if progress is not None:
                    a["progress"] = max(0, min(100, int(progress)))
                break

        if agent_found:
            # Also append to swarmData.logs if informative
            if "logs" not in data:
                data["logs"] = []
            data["logs"].append({
                "timestamp": get_timestamp(),
                "agent": agent_id,
                "message": f"[{agent_id}] {clean_detail[:120]}"
            })
            # Keep swarm logs to last 50 entries
            data["logs"] = data["logs"][-50:]

            # Atomic write (unique temp file + replace, retried while a reader holds the target).
            _atomic_write_text(STATUS_FILE, json.dumps(data, indent=2))
    except Exception as exc:
        print(f"[stream] WARNING: could not update swarm-status.json ({type(exc).__name__}); "
              "on-disk state is unchanged.", file=sys.stderr)

def detect_agent_from_text(text: str, fallback_agent: str = None) -> str:
    if fallback_agent and fallback_agent in VALID_AGENTS:
        return fallback_agent

    # 1. Explicit tag in text e.g. [05_backend] or 05_backend:
    for aid in VALID_AGENTS:
        if f"[{aid}]" in text or f"{aid}:" in text or f" {aid} " in text:
            return aid

    # 2. Heuristic keywords
    for pattern, aid in KEYWORD_AGENT_MAP:
        if pattern.search(text):
            return aid

    return fallback_agent or "cli"

def run_command(cmd: str, default_agent: str = None):
    """Executes a command, streams stdout/stderr live to console & terminal.log."""
    print(f"\n[TenAgent Stream Pipe] > {cmd}")
    ts_start = get_timestamp()
    append_terminal_log(default_agent or "cli", f"$ {cmd}")

    if default_agent and default_agent in VALID_AGENTS:
        update_agent_status(default_agent, f"$ {cmd}", status="WORKING")

    # Start subprocess in unbuffered mode
    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            encoding='utf-8',
            errors='replace'
        )

        for raw_line in iter(proc.stdout.readline, ''):
            # Print to real console
            sys.stdout.write(raw_line)
            sys.stdout.flush()

            clean_line = clean_ansi(raw_line).strip()
            if not clean_line:
                continue

            agent_id = detect_agent_from_text(clean_line, default_agent)
            append_terminal_log(agent_id, clean_line)

            # If an agent was tagged or recognized, update process detail
            if agent_id in VALID_AGENTS:
                update_agent_status(agent_id, clean_line)

        proc.stdout.close()
        return_code = proc.wait()

        ts_end = get_timestamp()
        status_msg = f"Process finished with code {return_code}"
        append_terminal_log(default_agent or "cli", status_msg)

        if default_agent and default_agent in VALID_AGENTS:
            if return_code == 0:
                update_agent_status(default_agent, f"Completed: {cmd[:40]}", status="REVIEWING")
            else:
                update_agent_status(default_agent, f"Failed (exit {return_code}): {cmd[:40]}", status="FAILED")

        return return_code
    except Exception as e:
        err_msg = f"[ERROR] Execution failed: {e}"
        print(err_msg, file=sys.stderr)
        append_terminal_log(default_agent or "cli", err_msg)
        return 1

def run_pipe(default_agent: str = None):
    """Reads lines from stdin (piped input), streams to console and log."""
    print(f"[TenAgent Stream Pipe] Listening to standard input (pipe mode)...")
    try:
        for raw_line in sys.stdin:
            sys.stdout.write(raw_line)
            sys.stdout.flush()

            clean_line = clean_ansi(raw_line).strip()
            if not clean_line:
                continue

            agent_id = detect_agent_from_text(clean_line, default_agent)
            append_terminal_log(agent_id, clean_line)
            if agent_id in VALID_AGENTS:
                update_agent_status(agent_id, clean_line)
    except KeyboardInterrupt:
        pass

def run_log(agent_id: str, message: str, status: str = None, progress: int = None):
    """Directly logs an agent action to terminal.log and updates swarm-status.json."""
    print(f"[{get_timestamp()}] [{agent_id}] {message}")
    append_terminal_log(agent_id, message)
    if agent_id in VALID_AGENTS:
        update_agent_status(agent_id, message, status=status, progress=progress)

def run_interactive_shell(default_agent: str = None):
    """Launches an interactive prompt session streaming commands to TenAgent."""
    print("=======================================================")
    print("TenAgent Virtual Office Monitored Shell")
    print("Commands executed here will stream live to the 2D Dashboard.")
    print("Type 'exit' to return to regular shell.")
    print("=======================================================\n")

    while True:
        try:
            prompt_str = f"tenagent[{default_agent or 'live'}]> "
            cmd = input(prompt_str).strip()
            if not cmd:
                continue
            if cmd.lower() in ("exit", "quit"):
                break
            run_command(cmd, default_agent)
        except (EOFError, KeyboardInterrupt):
            print("\nExiting TenAgent Monitored Shell.")
            break

def main():
    if len(sys.argv) < 2:
        run_interactive_shell()
        return

    subcmd = sys.argv[1].lower()

    # Subcommand: log
    if subcmd == "log":
        parser = argparse.ArgumentParser(prog="stream.py log")
        parser.add_argument("agent", help="Agent ID (e.g. 05_backend) or message")
        parser.add_argument("message", nargs="?", default="", help="Log message text")
        parser.add_argument("--status", choices=["IDLE", "WORKING", "WAITING", "REVIEWING"], default=None)
        parser.add_argument("--progress", type=int, default=None)
        args, _ = parser.parse_known_args(sys.argv[2:])

        if args.agent in VALID_AGENTS:
            msg = args.message or args.agent
            run_log(args.agent, msg, status=args.status, progress=args.progress)
        else:
            # First arg was the message itself
            combined_msg = f"{args.agent} {args.message}".strip()
            aid = detect_agent_from_text(combined_msg)
            run_log(aid, combined_msg, status=args.status, progress=args.progress)
        return

    # Subcommand: pipe
    if subcmd == "pipe":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        run_pipe(agent)
        return

    # Subcommand: council / debate
    if subcmd in ("council", "debate"):
        topic = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "System Architecture Review"
        try:
            import council
            council.run_council_debate(topic, ROOT_DIR)
        except Exception as e:
            print(f"[council_error] Failed to run council debate: {e}")
        return

    # Subcommand: swarm / build
    if subcmd in ("swarm", "build"):
        goal = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else "Full-Stack System MVP"
        try:
            import swarm_pipeline
            generated = swarm_pipeline.execute_multi_brain_swarm(goal, ROOT_DIR)
        except Exception as e:
            print(f"[swarm_error] Swarm execution failed: {e}")
            sys.exit(1)
        # Exit 0 only when a draft was generated; failure or a blocked start must not look like success.
        sys.exit(0 if generated else 1)

    # Subcommand: shell
    if subcmd == "shell":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        run_interactive_shell(agent)
        return

    # Subcommand: run <agent> <cmd>
    if subcmd == "run":
        if len(sys.argv) < 3:
            print("Usage: python stream.py run <agent_id> <command>")
            sys.exit(1)
        agent = sys.argv[2]
        cmd = " ".join(sys.argv[3:])
        code = run_command(cmd, agent)
        sys.exit(code)

    # Default: Treat entire argument string as a command to run
    full_cmd = " ".join(sys.argv[1:])
    # Check if first arg was an agent ID e.g. "05_backend npm install"
    parts = full_cmd.split(" ", 1)
    if parts[0] in VALID_AGENTS and len(parts) > 1:
        code = run_command(parts[1], parts[0])
    else:
        code = run_command(full_cmd)
    sys.exit(code)

if __name__ == "__main__":
    main()
