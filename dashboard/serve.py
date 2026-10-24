#!/usr/bin/env python3
"""
TenAgent Virtual Office Simulator Server
Serves the 2D dashboard and live swarm status with automatic port selection.
Usage: python dashboard/serve.py
"""

import http.server
import socketserver
import socket
import webbrowser
import os
import sys
import secrets

_SESSION_TOKEN = secrets.token_hex(24)
_DASHBOARD_PASSWORD = os.environ.get('TENAGENT_DASHBOARD_PASSWORD') or secrets.token_urlsafe(24)

DEFAULT_PORT = 7777
MAX_PORT_ATTEMPTS = 50
DIRECTORY = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if DIRECTORY not in sys.path:
    sys.path.insert(0, DIRECTORY)

from dashboard.security import (
    parse_log_update,
    public_config,
    valid_local_host,
    valid_mutation_origin,
    valid_operator_authorization,
    valid_static_path,
)

import json
import datetime
import threading
import time
import subprocess
import urllib.request
import urllib.error
import re
import concurrent.futures

SPECS_DIR = os.path.join(DIRECTORY, "specs")
LOG_FILE = os.path.join(SPECS_DIR, "terminal.log")
STATUS_FILE = os.path.join(SPECS_DIR, "swarm-status.json")

ANSI_REGEX = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')

def clean_ansi(text: str) -> str:
    return ANSI_REGEX.sub('', text)

KNOWN_SHELL_CMDS = {
    "dir", "ls", "cd", "pwd", "git", "npm", "pnpm", "yarn", "python", "py", 
    "node", "deno", "pip", "docker", "powershell", "cmd", "echo", "cat", 
    "type", "mkdir", "rm", "del", "touch", "clear", "cls", "pytest", "cargo", 
    "go", "dotnet", "curl", "wget", "stream", "stream.bat", "tree", "find", 
    "grep", "test-path", "get-content", "set-content", "whoami", "hostname", "npx", "agy"
}

def is_shell_command(cmd: str) -> bool:
    c = cmd.strip()
    if c.startswith("$ ") or c.startswith("> ") or c.startswith("./") or c.startswith(".\\"):
        return True
    first_word = c.split()[0].lower() if c else ""
    if first_word in KNOWN_SHELL_CMDS or first_word.endswith(".exe") or first_word.endswith(".bat") or first_word.endswith(".ps1") or first_word.endswith(".py"):
        return True
    if any(op in c for op in ("|", "&&", "||", ";", ">", "<")):
        return True
    return False

def append_to_terminal_log(agent: str, text: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    os.makedirs(SPECS_DIR, exist_ok=True)
    clean = clean_ansi(text).strip()
    if not clean:
        return
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] [{agent}] {clean}\n")

def safe_write_json(filepath: str, data: dict):
    try:
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception:
        pass

def set_agent_status_direct(agent_id: str, status: str, process_detail: str, progress: int = None):
    try:
        if os.path.exists(STATUS_FILE):
            with open(STATUS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated = False
            for a in data.get("agents", []):
                if a.get("id") == agent_id:
                    a["status"] = status
                    if process_detail:
                        a["processDetail"] = process_detail
                    if progress is not None:
                        a["progress"] = progress
                    updated = True
                    break
            if updated:
                safe_write_json(STATUS_FILE, data)
    except Exception:
        pass

def run_powershell_subprocess(cmd: str, root_dir: str):
    def worker():
        try:
            exec_cmd = cmd.strip()
            if exec_cmd.startswith("$ ") or exec_cmd.startswith("> "):
                exec_cmd = exec_cmd[2:].strip()
                
            append_to_terminal_log("cli", f"$ {exec_cmd}")
            proc = subprocess.Popen(
                ["powershell.exe", "-NoProfile", "-Command", exec_cmd],
                cwd=root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace"
            )
            for line in iter(proc.stdout.readline, ''):
                clean = line.strip()
                if clean:
                    append_to_terminal_log("cli", clean)
            proc.stdout.close()
            code = proc.wait()
            if code != 0:
                append_to_terminal_log("cli", f"Process exited with code {code}")
            else:
                append_to_terminal_log("cli", "Command completed (code 0)")
        except Exception as e:
            append_to_terminal_log("cli", f"Execution error: {str(e)}")

    threading.Thread(target=worker, daemon=True).start()

def run_agy_prompt(prompt: str, root_dir: str):
    def worker():
        try:
            agy_bin = "agy.exe"
            # Resolve from PATH rather than a developer-specific home directory.
            append_to_terminal_log("01_pm", "Starting Antigravity AI generation...")
            append_to_terminal_log("01_pm", f"Processing: {prompt}")
            set_agent_status_direct("01_pm", "WORKING", f"Generating response for: {prompt[:40]}...", progress=35)

            proc = subprocess.Popen(
                [agy_bin, "-p", prompt],
                cwd=root_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True,
                encoding="utf-8",
                errors="replace"
            )
            for line in iter(proc.stdout.readline, ''):
                clean = line.strip()
                if clean:
                    append_to_terminal_log("01_pm", clean)
            proc.stdout.close()
            code = proc.wait()
            if code != 0:
                append_to_terminal_log("01_pm", f"Process exited with code {code}")
                set_agent_status_direct("01_pm", "ERROR", f"AI engine exit code {code}.", progress=0)
            else:
                append_to_terminal_log("01_pm", "Response generated; verification pending.")
                set_agent_status_direct("01_pm", "REVIEWING", "AI response received; not verified.", progress=90)
        except Exception as e:
            append_to_terminal_log("01_pm", f"Error communicating with agy: {str(e)}")
            set_agent_status_direct("01_pm", "ERROR", "Error communicating with AI engine.", progress=0)

    threading.Thread(target=worker, daemon=True).start()

def verify_ai_provider_key(provider_id: str, key: str, base_url: str = "") -> dict:
    p_id = (provider_id or "").lower().strip()
    k = (key or "").strip()
    b_url = (base_url or "").strip()
    if not k:
        return {"status": "empty", "valid": False, "statusDetail": "Empty Key", "models": []}
    
    headers = {"User-Agent": "TenAgent/1.0"}
    models = []
    
    try:
        if "gemini" in p_id or "google" in p_id:
            url = f"https://generativelanguage.googleapis.com/v1beta/models?key={k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        for m in raw.get("models", []):
                            m_name = m.get("name", "").replace("models/", "")
                            methods = m.get("supportedGenerationMethods", [])
                            if "generateContent" in methods or "gemini" in m_name:
                                models.append(m_name)
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        elif "anthropic" in p_id or "claude" in p_id:
            url = "https://api.anthropic.com/v1/models"
            headers["x-api-key"] = k
            headers["anthropic-version"] = "2023-06-01"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("id") for m in raw.get("data", []) if m.get("id")]
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        elif "groq" in p_id:
            url = "https://api.groq.com/openai/v1/models"
            headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("id") for m in raw.get("data", []) if m.get("id") and m.get("active", True) is not False]
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        elif "deepseek" in p_id:
            url = "https://api.deepseek.com/models"
            headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("id") for m in raw.get("data", []) if m.get("id")]
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        elif "grok" in p_id or "xai" in p_id or "x.ai" in p_id:
            url = "https://api.x.ai/v1/models"
            headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("id") for m in raw.get("data", []) if m.get("id")]
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        elif "ollama" in p_id:
            url = "http://localhost:11434/api/tags"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=3) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        models = [m.get("name") or m.get("model") for m in raw.get("models", []) if m.get("name") or m.get("model")]
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active (Local)", "models": models[:60]}
        elif "9router" in p_id or b_url:
            target = b_url if b_url else "http://localhost:20128/v1"
            target = target.rstrip("/")
            if target.endswith("/v1"):
                url = f"{target}/models"
            elif "/models" in target:
                url = target
            else:
                url = f"{target}/v1/models"
            headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status in (200, 201):
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        items = raw.get("data") if isinstance(raw.get("data"), list) else raw.get("models", [])
                        for item in items:
                            if isinstance(item, dict):
                                m_id = item.get("id") or item.get("name")
                                if m_id:
                                    models.append(m_id)
                            elif isinstance(item, str):
                                models.append(item)
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
        else:
            url = "https://api.openai.com/v1/models"
            headers["Authorization"] = f"Bearer {k}"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=8) as resp:
                if resp.status == 200:
                    try:
                        raw = json.loads(resp.read().decode("utf-8"))
                        all_m = [m.get("id") for m in raw.get("data", []) if m.get("id")]
                        chat_pfx = ("gpt-4", "gpt-3.5", "o1", "o3", "chatgpt")
                        models = [m for m in all_m if any(m.startswith(p) for p in chat_pfx)] or all_m
                        models.sort()
                    except Exception:
                        pass
                    return {"status": "active", "valid": True, "statusDetail": "Active", "models": models[:60]}
    except urllib.error.HTTPError as e:
        if e.code in (400, 401, 403):
            return {"status": "invalid_key", "valid": False, "statusDetail": "Invalid Key", "models": []}
        elif e.code == 429:
            return {"status": "rate_limited", "valid": False, "statusDetail": "Rate Limited", "models": []}
        return {"status": "error", "valid": False, "statusDetail": f"HTTP {e.code}", "models": []}
    except Exception:
        if "ollama" in p_id:
            return {"status": "connection_error", "valid": False, "statusDetail": "Ollama Offline", "models": []}
        if "9router" in p_id or b_url:
            return {"status": "connection_error", "valid": False, "statusDetail": "Connection Failed", "models": []}
        return {"status": "connection_error", "valid": False, "statusDetail": "Connection Failed", "models": []}
        
    return {"status": "invalid_key", "valid": False, "statusDetail": "Invalid Key", "models": []}

if sys.platform != "win32":
    print("\n[TenAgent] Notice: TenAgent Virtual Office is designed and optimized for Windows environments.")
    print("Please launch TenAgent on Windows 10 or 11.\n")
    sys.exit(0)

import ctypes
from ctypes import wintypes

_TH32CS_SNAPPROCESS = 0x00000002
_PROCESS_QUERY_INFORMATION = 0x0400
_PROCESS_VM_READ = 0x0010

_kernel32 = ctypes.windll.kernel32
_ntdll = ctypes.windll.ntdll

class _PROCESSENTRY32(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_void_p),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", ctypes.c_char * 260)
    ]

class _PROCESS_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Reserved1", ctypes.c_void_p),
        ("PebBaseAddress", ctypes.c_void_p),
        ("Reserved2", ctypes.c_void_p * 2),
        ("UniqueProcessId", ctypes.c_void_p),
        ("Reserved3", ctypes.c_void_p),
    ]

class _UNICODE_STRING(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", ctypes.c_void_p),
    ]

def _get_process_info(pid: int):
    """Retrieves (cwd, cmdline) for a target Windows process PID via PEB."""
    h_proc = _kernel32.OpenProcess(_PROCESS_QUERY_INFORMATION | _PROCESS_VM_READ, False, pid)
    if not h_proc:
        return None, None
    try:
        pbi = _PROCESS_BASIC_INFORMATION()
        ret_len = wintypes.ULONG()
        status = _ntdll.NtQueryInformationProcess(
            h_proc, 0, ctypes.byref(pbi), ctypes.sizeof(pbi), ctypes.byref(ret_len)
        )
        if status != 0 or not pbi.PebBaseAddress:
            return None, None

        proc_params_addr = ctypes.c_void_p()
        read_bytes = ctypes.c_size_t()
        res = _kernel32.ReadProcessMemory(
            h_proc, ctypes.c_void_p(pbi.PebBaseAddress + 0x20),
            ctypes.byref(proc_params_addr), ctypes.sizeof(proc_params_addr),
            ctypes.byref(read_bytes)
        )
        if not res or not proc_params_addr.value:
            return None, None

        cwd_val = None
        cur_dir_str = _UNICODE_STRING()
        res = _kernel32.ReadProcessMemory(
            h_proc, ctypes.c_void_p(proc_params_addr.value + 0x38),
            ctypes.byref(cur_dir_str), ctypes.sizeof(cur_dir_str),
            ctypes.byref(read_bytes)
        )
        if res and cur_dir_str.Buffer and cur_dir_str.Length > 0:
            buf = ctypes.create_unicode_buffer(cur_dir_str.Length // 2)
            if _kernel32.ReadProcessMemory(h_proc, ctypes.c_void_p(cur_dir_str.Buffer), buf, cur_dir_str.Length, ctypes.byref(read_bytes)):
                cwd_val = buf.value

        cmdline_val = None
        cmd_str = _UNICODE_STRING()
        res = _kernel32.ReadProcessMemory(
            h_proc, ctypes.c_void_p(proc_params_addr.value + 0x70),
            ctypes.byref(cmd_str), ctypes.sizeof(cmd_str),
            ctypes.byref(read_bytes)
        )
        if res and cmd_str.Buffer and cmd_str.Length > 0:
            cbuf = ctypes.create_unicode_buffer(cmd_str.Length // 2)
            if _kernel32.ReadProcessMemory(h_proc, ctypes.c_void_p(cmd_str.Buffer), cbuf, cmd_str.Length, ctypes.byref(read_bytes)):
                cmdline_val = cbuf.value

        return cwd_val, cmdline_val
    finally:
        _kernel32.CloseHandle(h_proc)

def _get_process_cwd(pid: int):
    cwd, _ = _get_process_info(pid)
    return cwd

_cli_cache = {"time": 0, "data": {"name": "No CLI Detected", "status": "offline", "active": False}}

def detect_cli_status(root_dir: str) -> dict:
    norm_root = os.path.normpath(root_dir).lower()
    
    h_snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if h_snap == -1:
        return {'name': 'No CLI Detected', 'status': 'offline', 'active': False}

    pe32 = _PROCESSENTRY32()
    pe32.dwSize = ctypes.sizeof(_PROCESSENTRY32)

    found = None
    terminal_fallback = None

    # Identify self PID and parent PIDs (e.g. office.bat / cmd running serve.py) to avoid false positives
    self_pid = os.getpid()
    ignored_pids = {self_pid}
    curr_pid = self_pid
    for _ in range(5):
        try:
            h_p = _kernel32.OpenProcess(_PROCESS_QUERY_INFORMATION, False, curr_pid)
            if not h_p:
                break
            pbi_p = _PROCESS_BASIC_INFORMATION()
            ret_p = wintypes.ULONG()
            if _ntdll.NtQueryInformationProcess(h_p, 0, ctypes.byref(pbi_p), ctypes.sizeof(pbi_p), ctypes.byref(ret_p)) == 0:
                ppid = int(pbi_p.Reserved3 or 0)
                if ppid and ppid not in ignored_pids:
                    ignored_pids.add(ppid)
                    curr_pid = ppid
                else:
                    _kernel32.CloseHandle(h_p)
                    break
            _kernel32.CloseHandle(h_p)
        except Exception:
            break

    CANDIDATE_EXES = (
        'agy', 'kiro', 'claude', 'gemini', 'aider', 'cursor', 'cline', 'codex', 'goose',
        'windsurf', 'code.exe', 'wsl.exe', 'interpreter', 'plandex', 'mentat',
        'openhands', 'opendevin', 'opencode', 'crush', 'droid', 'bolt', 'qodo',
        'codium', 'continue', 'cody', 'copilot', 'tabby',
        'node.exe', 'python.exe', 'python3.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe',
        'windowsterminal.exe', 'wt.exe', 'bash.exe'
    )

    try:
        success = _kernel32.Process32First(h_snap, ctypes.byref(pe32))
        while success:
            pid = pe32.th32ProcessID
            if pid in ignored_pids:
                success = _kernel32.Process32Next(h_snap, ctypes.byref(pe32))
                continue

            exe_name = pe32.szExeFile.decode('latin-1', errors='ignore').lower()
            if any(cli in exe_name for cli in CANDIDATE_EXES):
                cwd, cmdline = _get_process_info(pid)
                if cwd:
                    norm_cwd = os.path.normpath(cwd).lower()
                    if norm_cwd == norm_root or norm_cwd.startswith(norm_root + os.sep):
                        cmd_lower = (cmdline or "").lower()

                        # Strictly ignore background server scripts and dashboard launchers
                        if any(ign in cmd_lower for ign in ('serve.py', 'office.bat', 'stream.py', 'swarm_pipeline.py', 'py_compile')):
                            success = _kernel32.Process32Next(h_snap, ctypes.byref(pe32))
                            continue

                        # Detect specific AI coding CLIs and tools
                        if 'agy' in exe_name or 'agy' in cmd_lower:
                            found = {'name': 'Antigravity CLI (agy)', 'status': 'active', 'active': True}
                            break
                        elif 'kiro' in exe_name or 'kiro' in cmd_lower:
                            found = {'name': 'Kiro CLI', 'status': 'active', 'active': True}
                            break
                        elif 'claude' in exe_name or 'claude' in cmd_lower:
                            found = {'name': 'Claude Code', 'status': 'active', 'active': True}
                            break
                        elif 'gemini' in exe_name or 'gemini' in cmd_lower:
                            found = {'name': 'Gemini CLI', 'status': 'active', 'active': True}
                            break
                        elif 'aider' in exe_name or 'aider' in cmd_lower:
                            found = {'name': 'Aider CLI', 'status': 'active', 'active': True}
                            break
                        elif 'cursor' in exe_name or 'cursor' in cmd_lower:
                            found = {'name': 'Cursor IDE', 'status': 'active', 'active': True}
                            break
                        elif 'windsurf' in exe_name or 'windsurf' in cmd_lower:
                            found = {'name': 'Windsurf IDE', 'status': 'active', 'active': True}
                            break
                        elif 'roo' in cmd_lower:
                            found = {'name': 'Roo Code Assistant', 'status': 'active', 'active': True}
                            break
                        elif 'cline' in exe_name or 'cline' in cmd_lower:
                            found = {'name': 'Cline Assistant', 'status': 'active', 'active': True}
                            break
                        elif 'interpreter' in cmd_lower or 'open-interpreter' in cmd_lower:
                            found = {'name': 'Open Interpreter', 'status': 'active', 'active': True}
                            break
                        elif 'plandex' in exe_name or 'plandex' in cmd_lower:
                            found = {'name': 'Plandex AI', 'status': 'active', 'active': True}
                            break
                        elif 'mentat' in exe_name or 'mentat' in cmd_lower:
                            found = {'name': 'Mentat AI', 'status': 'active', 'active': True}
                            break
                        elif 'openhands' in cmd_lower or 'opendevin' in cmd_lower:
                            found = {'name': 'OpenHands (OpenDevin)', 'status': 'active', 'active': True}
                            break
                        elif 'opencode' in cmd_lower:
                            found = {'name': 'OpenCode CLI', 'status': 'active', 'active': True}
                            break
                        elif 'crush' in cmd_lower:
                            found = {'name': 'Crush AI', 'status': 'active', 'active': True}
                            break
                        elif 'droid' in cmd_lower:
                            found = {'name': 'Factory Droid', 'status': 'active', 'active': True}
                            break
                        elif 'bolt' in cmd_lower:
                            found = {'name': 'Bolt.new CLI', 'status': 'active', 'active': True}
                            break
                        elif 'qodo' in cmd_lower or 'codium' in cmd_lower:
                            found = {'name': 'Qodo Gen (Codium)', 'status': 'active', 'active': True}
                            break
                        elif 'continue' in cmd_lower:
                            found = {'name': 'Continue Dev', 'status': 'active', 'active': True}
                            break
                        elif 'cody' in cmd_lower:
                            found = {'name': 'Sourcegraph Cody', 'status': 'active', 'active': True}
                            break
                        elif 'copilot' in cmd_lower:
                            found = {'name': 'GitHub Copilot CLI', 'status': 'active', 'active': True}
                            break
                        elif 'codex' in exe_name or 'codex' in cmd_lower:
                            found = {'name': 'Codex CLI', 'status': 'active', 'active': True}
                            break
                        elif 'goose' in exe_name or 'goose' in cmd_lower:
                            found = {'name': 'Goose CLI', 'status': 'active', 'active': True}
                            break
                        elif 'code.exe' in exe_name:
                            found = {'name': 'VS Code (Active in Project)', 'status': 'active', 'active': True}
                            break
                        # Generic interactive terminal detection (separate from office.bat launcher)
                        elif not terminal_fallback and any(sh in exe_name for sh in ('powershell.exe', 'pwsh.exe', 'wt.exe', 'bash.exe', 'wsl.exe', 'cmd.exe')):
                            # Only treat CMD / PowerShell as active if it's an interactive shell not running serve.py
                            if 'cmd' in exe_name:
                                terminal_fallback = {'name': 'Command Prompt (CMD)', 'status': 'active', 'active': True}
                            elif 'powershell' in exe_name or 'pwsh' in exe_name:
                                terminal_fallback = {'name': 'PowerShell', 'status': 'active', 'active': True}
                            elif 'wsl' in exe_name or 'bash' in exe_name:
                                terminal_fallback = {'name': 'WSL Terminal', 'status': 'active', 'active': True}
            success = _kernel32.Process32Next(h_snap, ctypes.byref(pe32))
    finally:
        _kernel32.CloseHandle(h_snap)
        
    return found or terminal_fallback or {'name': 'No CLI Detected', 'status': 'offline', 'active': False}

def cli_status_background_worker(root_dir: str):
    while True:
        try:
            status = detect_cli_status(root_dir)
            _cli_cache["data"] = status
            _cli_cache["time"] = time.time()
        except Exception:
            pass
        time.sleep(2.0)

def get_cached_cli_status(root_dir: str) -> dict:
    if _cli_cache["data"] is not None:
        return _cli_cache["data"]
    data = detect_cli_status(root_dir)
    _cli_cache["data"] = data
    _cli_cache["time"] = time.time()
    return data

def update_provider_runtime_status(provider_id: str, status: str, status_detail: str, valid: bool = None):
    try:
        cfg_file = os.path.join(SPECS_DIR, "swarm-config.json")
        if not os.path.exists(cfg_file):
            return
        with open(cfg_file, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        changed = False
        p_target = provider_id.lower().strip()
        for p in cfg.get("providers", []):
            cur_p = (p.get("provider") or "").lower().strip()
            if cur_p == p_target or (cur_p in p_target) or (p_target in cur_p):
                if p.get("status") != status:
                    p["status"] = status
                    p["statusDetail"] = status_detail
                    if valid is not None:
                        p["valid"] = valid
                    changed = True
                break
        if changed:
            safe_write_json(cfg_file, cfg)
    except Exception:
        pass

def probe_and_update_local_provider(p: dict) -> bool:
    """Probes a local provider (e.g. 9Router or Ollama) via TCP socket and syncs status. Returns True if changed."""
    p_id = (p.get("provider") or "").lower().strip()
    b_url = (p.get("baseUrl") or p.get("base_url") or "").strip()
    is_local = "9router" in p_id or "ollama" in p_id or "localhost" in b_url or "127.0.0.1" in b_url
    if not is_local:
        return False

    host = "127.0.0.1"
    port = 20128 if "9router" in p_id else (11434 if "ollama" in p_id else 8000)
    if b_url:
        try:
            from urllib.parse import urlparse
            parsed = urlparse(b_url if "://" in b_url else f"http://{b_url}")
            if parsed.hostname:
                host = parsed.hostname
            if parsed.port:
                port = parsed.port
        except Exception:
            pass

    is_alive = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            probe.connect((host, port))
            is_alive = True
    except OSError:
        is_alive = False

    changed = False
    if is_alive:
        if p.get("status") != "active" and p.get("status") != "invalid_key":
            p["status"] = "active"
            p["statusDetail"] = "Active"
            p["valid"] = True
            changed = True
    else:
        if p.get("status") != "connection_error":
            p["status"] = "connection_error"
            p["statusDetail"] = "Offline"
            p["valid"] = False
            changed = True
    return changed

def local_providers_probe_worker(root_dir: str):
    cfg_file = os.path.join(root_dir, "specs", "swarm-config.json")
    while True:
        try:
            time.sleep(2.5)
            if not os.path.exists(cfg_file):
                continue
            with open(cfg_file, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            providers = cfg.get("providers", [])
            changed = False
            for p in providers:
                if probe_and_update_local_provider(p):
                    changed = True

            if changed:
                safe_write_json(cfg_file, cfg)
        except Exception:
            pass

def call_custom_ai_provider(prompt: str, providers: list, root_dir: str):
    def worker():
        valid_providers = [p for p in providers if p.get("valid") is not False and p.get("status") != "invalid_key"]
        if not valid_providers:
            append_to_terminal_log("system", "No valid AI provider keys configured. Please verify your API keys in Connect AI Providers.")
            return

        success = False
        for p_entry in valid_providers:
            p_id = (p_entry.get("provider") or "").lower()
            key = p_entry.get("key") or ""
            name = p_entry.get("name") or p_id.upper()
            if not key:
                continue

            append_to_terminal_log("system", f"Connecting prompt to {name}...")

            if "gemini" in p_id:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={key}"
                    headers = {"Content-Type": "application/json"}
                    req_data = {
                        "contents": [{
                            "parts": [{"text": "You are TenAgent engineering assistant pair programming with the founder. Answer concisely for:\n\n" + prompt}]
                        }]
                    }
                    req = urllib.request.Request(url, data=json.dumps(req_data).encode("utf-8"), headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        candidates = res_json.get("candidates", [])
                        if candidates:
                            parts = candidates[0].get("content", {}).get("parts", [])
                            text = "\n".join(part.get("text", "") for part in parts)
                            if text:
                                for line in text.split("\n"):
                                    line_clean = line.strip()
                                    if line_clean:
                                        append_to_terminal_log("01_pm", line_clean)
                                update_provider_runtime_status(p_id, "active", "Active", True)
                                success = True
                                break
                except urllib.error.HTTPError as e:
                    err_msg = f"HTTP {e.code}"
                    if e.code == 429:
                        err_msg += " (Rate limit exceeded)"
                        update_provider_runtime_status(p_id, "rate_limited", "Rate Limited", False)
                    elif e.code in (401, 402, 403):
                        update_provider_runtime_status(p_id, "invalid_key", "Invalid Key", False)
                    append_to_terminal_log("system", f"{name} error: {err_msg}. Rotating to next provider...")
                except Exception as e:
                    append_to_terminal_log("system", f"{name} error: {str(e)}. Rotating to next provider...")
            else:
                endpoint = "https://api.openai.com/v1/chat/completions"
                model = "gpt-4o-mini"
                if "deepseek" in p_id:
                    endpoint = "https://api.deepseek.com/v1/chat/completions"
                    model = "deepseek-chat"
                elif "groq" in p_id:
                    endpoint = "https://api.groq.com/openai/v1/chat/completions"
                    model = "llama-3.3-70b-versatile"
                elif "ollama" in p_id:
                    endpoint = "http://localhost:11434/v1/chat/completions"
                    model = "llama3"
                elif "9router" in p_id or p_entry.get("base_url") or p_entry.get("baseUrl"):
                    b_url = (p_entry.get("base_url") or p_entry.get("baseUrl") or "").strip()
                    if not b_url and "9router" in p_id:
                        b_url = "http://localhost:20128/v1"
                    b_url = b_url.rstrip("/")
                    if b_url.endswith("/v1"):
                        endpoint = f"{b_url}/chat/completions"
                    elif "/chat/completions" in b_url:
                        endpoint = b_url
                    else:
                        endpoint = f"{b_url}/v1/chat/completions"
                    model = p_entry.get("model") or "gpt-4o-mini"

                try:
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {key}"
                    }
                    req_data = {
                        "model": model,
                        "messages": [
                            {"role": "system", "content": "You are TenAgent engineering assistant pair programming with the founder. Answer concisely."},
                            {"role": "user", "content": prompt}
                        ]
                    }
                    req = urllib.request.Request(endpoint, data=json.dumps(req_data).encode("utf-8"), headers=headers, method="POST")
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        text = ""
                        if "choices" in res_json and res_json["choices"]:
                            text = res_json["choices"][0].get("message", {}).get("content", "")
                        if text:
                            for line in text.split("\n"):
                                line_clean = line.strip()
                                if line_clean:
                                    append_to_terminal_log("01_pm", line_clean)
                            update_provider_runtime_status(p_id, "active", "Active", True)
                            success = True
                            break
                except urllib.error.HTTPError as e:
                    err_msg = f"HTTP {e.code}"
                    if e.code == 429:
                        err_msg += " (Rate limit exceeded)"
                        update_provider_runtime_status(p_id, "rate_limited", "Rate Limited", False)
                    elif e.code in (401, 402, 403):
                        update_provider_runtime_status(p_id, "invalid_key", "Invalid Key", False)
                    append_to_terminal_log("system", f"{name} error: {err_msg}. Rotating to next provider...")
                except Exception as e:
                    append_to_terminal_log("system", f"{name} error: {str(e)}. Rotating to next provider...")

        if not success:
            append_to_terminal_log("system", "All configured AI providers failed to respond. Check API keys and network connection.")

    threading.Thread(target=worker, daemon=True).start()

IGNORE_DIRS = {
    ".git", ".gemini", "node_modules", "__pycache__", ".vscode", 
    ".idea", "dist", "build", ".agents/skills", ".pytest_cache"
}
IGNORE_FILES = {
    "terminal.log", "swarm-status.json", "swarm-status.json.tmp",
    "test-matrix.md", "audit-report.md", "signoff.md"
}

AUTO_GENERATED_FILES = set()

def safe_write_json(filepath: str, data: dict):
    try:
        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception:
        pass

def detect_agent_from_file_path(rel_path: str) -> str:
    norm = rel_path.replace("\\", "/").lower()
    
    # Exclude downstream cascade deliverables and temp/log files to prevent echo loops
    if any(norm.endswith(x) for x in ("test-matrix.md", "audit-report.md", "signoff.md", ".tmp", ".log")):
        return None
    
    if "specs/prd" in norm or "prd/" in norm:
        return "01_pm"
    if "specs/architecture" in norm or "adr-" in norm or "architecture/" in norm:
        return "02_arch"
    if "specs/design" in norm or "design.md" in norm or "screen-flow" in norm:
        return "03_designer"
    if "specs/database" in norm or "data-dictionary" in norm or norm.endswith(".sql") or "migrations" in norm:
        return "04_dba"
    if norm.startswith("backend/") or "/backend/" in norm:
        return "05_backend"
    if norm.startswith("frontend/") or norm.startswith("mobile/") or "/frontend/" in norm or "/mobile/" in norm or norm.startswith("public/"):
        return "06_client"
    if "specs/qa" in norm or "tests/" in norm or "test/" in norm or ".spec." in norm or ".test." in norm:
        return "07_qa"
    if "specs/security" in norm or "security/" in norm or "audit-report" in norm:
        return "08_security"
    if "dockerfile" in norm or "docker-compose" in norm or ".github/" in norm or "devops/" in norm or "specs/devops" in norm:
        return "09_devops"
    if "specs/reviews" in norm or "signoff" in norm or "review" in norm:
        return "10_tech_lead"
    
    # Generic extensions fallback
    if norm.endswith(".css"):
        return "03_designer"
    if norm.endswith((".ts", ".js", ".html")):
        if "mobile" in norm or "frontend" in norm or "public" in norm:
            return "06_client"
        return "05_backend"
    if norm.endswith((".py", ".go", ".rs", ".java", ".php")):
        return "05_backend"
        
    return "05_backend"

ROLE_WORK_STAGES = {
    "01_pm": [
        (25, "Conducting discovery & synthesizing stakeholder requirements"),
        (50, "Drafting user stories & domain boundary specs in specs/prd/"),
        (75, "Defining acceptance criteria & core workflow constraints"),
        (90, "Synthesizing Product Requirements Document"),
        (100, "PRD finalized. Ready for architectural review.")
    ],
    "02_arch": [
        (25, "Evaluating system trade-offs & selecting technology stack"),
        (50, "Formulating Clean Architecture & ADR decision records"),
        (75, "Establishing cross-layer boundaries & interface contracts"),
        (90, "Finalizing architectural specs in specs/architecture/"),
        (100, "System Architecture approved and locked.")
    ],
    "03_designer": [
        (25, "Synthesizing design tokens, palette & typography rules"),
        (50, "Wireframing key screen flows & component hierarchy"),
        (75, "Auditing color contrast (WCAG AA) & anti-slop guidelines"),
        (90, "Publishing design tokens in specs/design/ and DESIGN.md"),
        (100, "Design specifications completed and handed off.")
    ],
    "04_dba": [
        (25, "Mapping domain entities & relational schema models"),
        (50, "Normalizing tables to 3NF & enforcing foreign key integrity"),
        (75, "Generating migration scripts & optimizing table indexes"),
        (90, "Synchronizing specs/database/schema.sql & specs/api/openapi.yaml"),
        (100, "Database schema & OpenAPI contract locked.")
    ],
    "05_backend": [
        (25, "Scaffolding domain layer, entity models & core interfaces"),
        (50, "Implementing domain use cases & repository adapters"),
        (75, "Wiring REST API endpoints & input validation logic"),
        (90, "Verifying API endpoints against OpenAPI contracts"),
        (100, "Backend services compiled and verified against specifications.")
    ],
    "06_client": [
        (25, "Scaffolding client app structure & token theme provider"),
        (50, "Building view components & interactive screen layouts"),
        (75, "Connecting REST API client & reactive state management"),
        (90, "Testing responsive screen layouts & interaction fidelity"),
        (100, "Client views fully rendered and integrated.")
    ],
    "07_qa": [
        (25, "Mapping acceptance criteria into test scenarios"),
        (50, "Writing unit test fixtures & domain logic assertions"),
        (75, "Executing integration test runner & regression suites"),
        (90, "Compiling test coverage report in specs/qa/"),
        (100, "Test suites passing with zero regressions.")
    ],
    "08_security": [
        (25, "Inspecting authentication pipelines & token lifetimes"),
        (50, "Auditing codebase against OWASP Top 10 vulnerabilities"),
        (75, "Verifying secret isolation, input sanitization & CORS"),
        (90, "Packaging security audit report in specs/security/"),
        (100, "Security review verified. No vulnerabilities detected.")
    ],
    "09_devops": [
        (25, "Writing multi-stage Docker build recipes"),
        (50, "Configuring compose services, network bridges & envs"),
        (75, "Setting up CI/CD workflows & build validation pipelines"),
        (90, "Verifying container runtime & reproducible artifacts"),
        (100, "Container environments & CI/CD automation verified.")
    ],
    "10_tech_lead": [
        (25, "Inspecting git commits & architectural compliance"),
        (50, "Auditing code quality, anti-slop criteria & comments hygiene"),
        (75, "Validating cross-agent contract parity across specs"),
        (90, "Performing final quality gate verification"),
        (100, "Quality Gate APPROVED. All deliverables ready for merge.")
    ],
}

def get_role_stage_message(agent_id: str, progress: int) -> str:
    stages = ROLE_WORK_STAGES.get(agent_id, [])
    if not stages:
        return f"Executing {agent_id} tasks ({progress}%)"
    for threshold, msg in stages:
        if progress <= threshold:
            return msg
    return stages[-1][1]

last_activity_time = {}
last_crawl_time = {}
last_file_action_time = {}

last_crawl_time = {}
last_file_action_time = {}

def handle_task_completion(agent_id: str, root_dir: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    log_file = os.path.join(root_dir, "specs", "terminal.log")
    status_file = os.path.join(root_dir, "specs", "swarm-status.json")
    
    try:
        if os.path.exists(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated = False
            for a in data.get("agents", []):
                if a.get("id") == agent_id and a.get("status") == "WORKING":
                    a["status"] = "REVIEWING"
                    a["progress"] = 100
                    a["processDetail"] = get_role_stage_message(agent_id, 100)
                    updated = True
                    break
            if updated:
                msg = f"Task completed (100%). Status set to REVIEWING."
                if "logs" not in data:
                    data["logs"] = []
                data["logs"].append({
                    "timestamp": ts,
                    "agent": agent_id,
                    "message": f"[{agent_id}] {msg}"
                })
                data["logs"] = data["logs"][-50:]
                
                # Natural dependency notification (Honest state without fake execution)
                if agent_id in ("05_backend", "06_client"):
                    for a in data.get("agents", []):
                        if a.get("id") == "07_qa" and a.get("status") in ("IDLE", "WAITING"):
                            a["status"] = "WAITING"
                            a["currentTask"] = "Pending test verification for latest backend/client changes."
                            a["processDetail"] = "Standby: Waiting for automated test execution or QA suite run."
                
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] [{agent_id}] {msg}\n")

                if "project" in data and "agents" in data:
                    total_p = sum(ag.get("progress", 0) for ag in data["agents"])
                    data["project"]["overallProgress"] = int(total_p / len(data["agents"]))

                safe_write_json(status_file, data)
    except Exception:
        pass

def handle_file_event(agent_id: str, action_desc: str, root_dir: str):
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    log_file = os.path.join(root_dir, "specs", "terminal.log")
    status_file = os.path.join(root_dir, "specs", "swarm-status.json")
    
    now = time.time()
    last_activity_time[agent_id] = now
    last_file_action_time[agent_id] = now
    
    # 1. Append to terminal.log
    try:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] [{agent_id}] {action_desc}\n")
    except Exception:
        pass
        
    # 2. Update swarm-status.json with dynamic progress
    try:
        if os.path.exists(status_file):
            with open(status_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            updated = False
            for a in data.get("agents", []):
                if a.get("id") == agent_id:
                    a["processDetail"] = action_desc
                    a["status"] = "WORKING"
                    updated = True
                    break
            if updated:
                if "logs" not in data:
                    data["logs"] = []
                data["logs"].append({
                    "timestamp": ts,
                    "agent": agent_id,
                    "message": f"[{agent_id}] {action_desc}"
                })
                data["logs"] = data["logs"][-50:]
                
                # Update overall project progress
                if "project" in data and "agents" in data:
                    total_p = sum(ag.get("progress", 0) for ag in data["agents"])
                    data["project"]["overallProgress"] = int(total_p / len(data["agents"]))

                safe_write_json(status_file, data)
    except Exception:
        pass

def start_workspace_watcher(root_dir: str):
    def watcher_loop():
        file_mtimes = {}
        log_file = os.path.join(root_dir, "specs", "terminal.log")
        status_file = os.path.join(root_dir, "specs", "swarm-status.json")
        prev_status_mtime = 0
        prev_agent_states = {}

        # Initial scan without triggering events
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not any(ign in os.path.join(root, d).replace('\\', '/') for ign in IGNORE_DIRS)]
            for f in files:
                if f in IGNORE_FILES or f.endswith(".tmp"):
                    continue
                path = os.path.join(root, f)
                try:
                    file_mtimes[path] = os.path.getmtime(path)
                except OSError:
                    pass
                    
        # Seed initial agent states from swarm-status.json
        if os.path.exists(status_file):
            try:
                prev_status_mtime = os.path.getmtime(status_file)
                with open(status_file, "r", encoding="utf-8") as f:
                    sdata = json.load(f)
                for a in sdata.get("agents", []):
                    aid = a.get("id")
                    stat = a.get("status")
                    pdetail = a.get("processDetail", "")
                    prev_agent_states[aid] = (stat, pdetail)
                    if stat == "WORKING":
                        last_activity_time[aid] = time.time()
            except Exception:
                pass
                    
        while True:
            try:
                time.sleep(0.4)
                now = time.time()
                
                # 1. Direct swarm-status.json watcher: stream state changes to terminal.log
                if os.path.exists(status_file):
                    try:
                        smtime = os.path.getmtime(status_file)
                        if smtime > prev_status_mtime:
                            prev_status_mtime = smtime
                            with open(status_file, "r", encoding="utf-8") as f:
                                sdata = json.load(f)
                            for a in sdata.get("agents", []):
                                aid = a.get("id")
                                stat = a.get("status")
                                pdetail = a.get("processDetail", "")
                                old_stat, old_detail = prev_agent_states.get(aid, (None, None))
                                if stat == "WORKING" and (old_stat != "WORKING" or aid not in last_activity_time):
                                    last_activity_time[aid] = now
                                if (stat != old_stat or pdetail != old_detail) and pdetail and pdetail != old_detail:
                                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                                    with open(log_file, "a", encoding="utf-8") as lf:
                                        lf.write(f"[{ts}] [{aid}] {pdetail}\n")
                                prev_agent_states[aid] = (stat, pdetail)
                    except Exception:
                        pass
                
                # 2. Universal state check (Zero fake stopwatch crawler: progress reflects real agent computation)
                for aid, last_t in list(last_activity_time.items()):
                    elapsed = now - last_t
                    # If an agent was in WORKING state for over 120 seconds with no tool activity, return to IDLE without fake 100%
                    if elapsed >= 120.0:
                        del last_activity_time[aid]
                        if os.path.exists(status_file):
                            try:
                                with open(status_file, "r", encoding="utf-8") as f:
                                    sdata = json.load(f)
                                changed = False
                                for a in sdata.get("agents", []):
                                    if a.get("id") == aid and a.get("status") == "WORKING":
                                        a["status"] = "IDLE"
                                        a["processDetail"] = "Standing by for founder instructions."
                                        changed = True
                                if changed:
                                    safe_write_json(status_file, sdata)
                                    prev_status_mtime = os.path.getmtime(status_file)
                            except Exception:
                                pass

                # 3. Workspace filesystem watcher for all project code and specs
                for root, dirs, files in os.walk(root_dir):
                    dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not any(ign in os.path.join(root, d).replace('\\', '/') for ign in IGNORE_DIRS)]
                    for f in files:
                        if f in IGNORE_FILES or f.endswith(".tmp") or f.endswith(".log") or f in ("test-matrix.md", "audit-report.md", "signoff.md"):
                            continue
                        path = os.path.join(root, f)
                        try:
                            mtime = os.path.getmtime(path)
                        except OSError:
                            continue
                            
                        abs_p = os.path.abspath(path)
                        if abs_p in AUTO_GENERATED_FILES:
                            file_mtimes[path] = mtime
                            AUTO_GENERATED_FILES.discard(abs_p)
                            continue

                        prev_mtime = file_mtimes.get(path)
                        if prev_mtime is None:
                            file_mtimes[path] = mtime
                            rel_path = os.path.relpath(path, root_dir).replace("\\", "/")
                            agent_id = detect_agent_from_file_path(rel_path)
                            if agent_id:
                                handle_file_event(agent_id, f"Created {rel_path}", root_dir)
                        elif mtime > prev_mtime:
                            file_mtimes[path] = mtime
                            rel_path = os.path.relpath(path, root_dir).replace("\\", "/")
                            agent_id = detect_agent_from_file_path(rel_path)
                            if agent_id:
                                handle_file_event(agent_id, f"Saved {rel_path}", root_dir)
            except Exception:
                pass
                
    t = threading.Thread(target=watcher_loop, daemon=True)
    t.start()

class SwarmHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        # Silence routine HTTP polling logs to keep the console clean
        pass

    def end_headers(self):
        # This loopback dashboard intentionally does not expose CORS permissions.
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(405)
        self.send_header('Allow', 'GET, POST')
        self.end_headers()

    def do_HEAD(self):
        # Avoid inherited SimpleHTTPRequestHandler HEAD bypassing GET guards.
        if not self._require_dashboard_access():
            return
        self.send_response(405)
        self.send_header('Allow', 'GET, POST')
        self.end_headers()

    def _require_dashboard_access(self, mutation=False):
        port = self.server.server_address[1]
        host = self.headers.get('Host')
        if not valid_local_host(host, port):
            self.send_json_response({"error": "Invalid local Host"}, 403)
            return False
        if mutation and not valid_mutation_origin(
            self.headers.get('Origin'), host,
            self.headers.get('Sec-Fetch-Site'), port
        ):
            self.send_json_response({"error": "Cross-origin operation denied"}, 403)
            return False
        if not valid_operator_authorization(
            self.headers.get('Authorization'), _DASHBOARD_PASSWORD
        ):
            self.send_response(401)
            self.send_header(
                'WWW-Authenticate',
                'Basic realm="TenAgent local operator", charset="UTF-8"',
            )
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False
        return True

    def send_json_response(self, data, status_code=200):
        try:
            if isinstance(data, (dict, list, bool, int, float, str)):
                payload = json.dumps(data).encode('utf-8')
            elif isinstance(data, bytes):
                payload = data
            else:
                payload = str(data).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def do_GET(self):
        if not self._require_dashboard_access():
            return
        clean_path = self.path.split('?')[0]

        # Redirect root to /dashboard/
        if clean_path == '/' or clean_path == '':
            try:
                self.send_response(302)
                self.send_header('Location', '/dashboard/')
                self.send_header('Set-Cookie', f'tenagent_token={_SESSION_TOKEN}; Path=/; SameSite=Strict')
                self.end_headers()
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                pass
            return

        if clean_path == '/api/csrf-token':
            self.send_json_response({"token": _SESSION_TOKEN})
            return

        if clean_path in ('/favicon.ico', '/dashboard/favicon.ico'):
            fav_ico = os.path.join(DIRECTORY, "dashboard", "favicon.ico")
            fav_png = os.path.join(DIRECTORY, "dashboard", "favicon.png")
            fav_svg = os.path.join(DIRECTORY, "dashboard", "favicon.svg")
            fav_path = fav_ico if os.path.exists(fav_ico) else (fav_png if os.path.exists(fav_png) else fav_svg)
            mime = "image/x-icon" if fav_path.endswith('.ico') else ("image/png" if fav_path.endswith('.png') else "image/svg+xml")
            if os.path.exists(fav_path):
                try:
                    with open(fav_path, "rb") as f:
                        fav_data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', mime)
                    self.send_header('Content-Length', str(len(fav_data)))
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    self.wfile.write(fav_data)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass
                return

        if clean_path in ('/favicon.png', '/dashboard/favicon.png'):
            fav_png = os.path.join(DIRECTORY, "dashboard", "favicon.png")
            if os.path.exists(fav_png):
                try:
                    with open(fav_png, "rb") as f:
                        fav_data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/png')
                    self.send_header('Content-Length', str(len(fav_data)))
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    self.wfile.write(fav_data)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass
                return

        if clean_path in ('/favicon.svg', '/dashboard/favicon.svg'):
            fav_svg = os.path.join(DIRECTORY, "dashboard", "favicon.svg")
            if os.path.exists(fav_svg):
                try:
                    with open(fav_svg, "rb") as f:
                        fav_data = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'image/svg+xml')
                    self.send_header('Content-Length', str(len(fav_data)))
                    self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                    self.send_header('Pragma', 'no-cache')
                    self.send_header('Expires', '0')
                    self.end_headers()
                    self.wfile.write(fav_data)
                except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                    pass
                return

        if clean_path == '/api/cli-status':
            self.send_json_response(get_cached_cli_status(DIRECTORY))
            return

        if clean_path == '/api/config':
            cfg = {"engine": "native", "providers": []}
            cfg_file = os.path.join(SPECS_DIR, "swarm-config.json")
            if not os.path.exists(cfg_file):
                example_file = os.path.join(SPECS_DIR, "swarm-config.example.json")
                if os.path.exists(example_file):
                    try:
                        import shutil
                        shutil.copy2(example_file, cfg_file)
                    except Exception:
                        pass

            if os.path.exists(cfg_file):
                try:
                    with open(cfg_file, "r", encoding="utf-8") as f:
                        saved = json.load(f)
                        cfg.update(saved)
                        if "providers" in cfg:
                            probe_changed = False
                            for p in cfg["providers"]:
                                if probe_and_update_local_provider(p):
                                    probe_changed = True
                            if probe_changed:
                                # Persist original credentials, not their redacted HTTP view.
                                safe_write_json(cfg_file, cfg)
                except Exception:
                    pass
            cfg["cli"] = get_cached_cli_status(DIRECTORY)
            self.send_json_response(public_config(cfg))
            return

        # Validate raw static URLs before SimpleHTTPRequestHandler decodes them.
        if not valid_static_path(clean_path):
            self.send_error(403, "Access Forbidden: Encoded or hidden path")
            return

        lower_path = clean_path.lower()
        if lower_path.endswith('.env') or 'swarm-config' in lower_path or lower_path.endswith(('.py', '.bat', '.ps1', '.sh', '.git')):
            self.send_error(403, "Access Forbidden: Protected system resource")
            return

        allowed_prefixes = ('/dashboard/', '/assets/', '/specs/swarm-status.json', '/specs/terminal.log', '/favicon.')
        if not any(clean_path.startswith(p) for p in allowed_prefixes) and clean_path not in ('/dashboard', '/'):
            self.send_error(404, "Not Found")
            return

        try:
            super().do_GET()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

    def do_POST(self):
        if not self._require_dashboard_access(mutation=True):
            return
        if self.path == '/api/config':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                return
            try:
                payload = json.loads(body)
                providers = payload.get("providers", [])
                
                cfg_file = os.path.join(SPECS_DIR, "swarm-config.json")
                existing_keys = {}
                if os.path.exists(cfg_file):
                    try:
                        with open(cfg_file, "r", encoding="utf-8") as f:
                            saved_cfg = json.load(f)
                            for sp in saved_cfg.get("providers", []):
                                sp_id = sp.get("provider", "")
                                if sp_id and sp.get("key"):
                                    existing_keys[sp_id] = sp.get("key")
                    except Exception:
                        pass

                def validate_single_provider(p_entry):
                    p_id = (p_entry.get("provider") or "").strip()
                    k = (p_entry.get("key") or "").strip()
                    b_url = (p_entry.get("baseUrl") or p_entry.get("base_url") or "").strip()
                    if ("..." in k or k == "***") and p_id in existing_keys:
                        k = existing_keys[p_id]
                        p_entry["key"] = k
                    
                    if b_url:
                        p_entry["baseUrl"] = b_url
                        p_entry["base_url"] = b_url
                    
                    if k:
                        ver = verify_ai_provider_key(p_id, k, base_url=b_url)
                        p_entry["status"] = ver["status"]
                        p_entry["valid"] = ver["valid"]
                        p_entry["statusDetail"] = ver["statusDetail"]
                        p_entry["models"] = ver.get("models", [])
                    else:
                        p_entry["status"] = "empty"
                        p_entry["valid"] = False
                        p_entry["statusDetail"] = "No Key"
                        p_entry["models"] = []
                    return p_entry

                if providers:
                    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(providers), 5)) as executor:
                        list(executor.map(validate_single_provider, providers))

                os.makedirs(SPECS_DIR, exist_ok=True)
                with open(cfg_file, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2)

                self.send_json_response({"ok": True, "config": public_config(payload)})
                return
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return

        if self.path.startswith('/api/models'):
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
                payload = json.loads(body)
                p_id = (payload.get("provider") or "").strip()
                k = (payload.get("key") or "").strip()
                b_url = (payload.get("baseUrl") or payload.get("base_url") or "").strip()
                if ("..." in k or k == "***"):
                    cfg_file = os.path.join(SPECS_DIR, "swarm-config.json")
                    if os.path.exists(cfg_file):
                        try:
                            with open(cfg_file, "r", encoding="utf-8") as f:
                                scfg = json.load(f)
                                for sp in scfg.get("providers", []):
                                    if sp.get("provider") == p_id and sp.get("key"):
                                        k = sp.get("key")
                                        break
                        except Exception:
                            pass
                ver = verify_ai_provider_key(p_id, k, base_url=b_url)
                self.send_json_response(ver)
                return
            except Exception as e:
                self.send_json_response({"status": "error", "valid": False, "models": [], "error": str(e)}, 400)
                return

        if self.path == '/api/command':
            # Security Check 1: Must originate from localhost
            client_ip = self.client_address[0] if hasattr(self, 'client_address') and self.client_address else ''
            if client_ip not in ('127.0.0.1', '::1', 'localhost'):
                self.send_json_response({"error": "Forbidden: Remote access denied. TenAgent only accepts commands from localhost."}, 403)
                return

            # Security Check 2: Block cross-site origins
            origin = self.headers.get('Origin', '')
            if origin and not (origin.startswith('http://localhost:') or origin.startswith('http://127.0.0.1:')):
                self.send_json_response({"error": "Forbidden: Cross-origin request rejected"}, 403)
                return
            if self.headers.get('Sec-Fetch-Site') == 'cross-site':
                self.send_json_response({"error": "Forbidden: Cross-site request rejected"}, 403)
                return

            # Security Check 3: CSRF Session Token verification
            req_token = self.headers.get('X-TenAgent-Token', '').strip()
            if not req_token:
                cookie_hdr = self.headers.get('Cookie', '')
                for cookie_part in cookie_hdr.split(';'):
                    if 'tenagent_token=' in cookie_part:
                        req_token = cookie_part.split('tenagent_token=')[1].strip()
                        break
            if not req_token or req_token != _SESSION_TOKEN:
                self.send_json_response({"error": "Forbidden: Invalid or missing CSRF session token"}, 403)
                return

            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                return
            try:
                payload = json.loads(body)
                cmd = payload.get('command', '').strip()
                if not cmd:
                    self.send_json_response({"error": "Empty command"}, 400)
                    return
                
                ts = datetime.datetime.now().strftime("%H:%M:%S")
                os.makedirs(SPECS_DIR, exist_ok=True)
                
                # 1. Log founder prompt to terminal
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(f"[{ts}] [founder] > {cmd}\n")
                
                # Read swarm-config.json to check engine mode
                cfg = {"engine": "native", "providers": []}
                cfg_file = os.path.join(SPECS_DIR, "swarm-config.json")
                if os.path.exists(cfg_file):
                    try:
                        with open(cfg_file, "r", encoding="utf-8") as cf:
                            cfg.update(json.load(cf))
                    except Exception:
                        pass
                
                engine_mode = cfg.get("engine", "native")
                providers = cfg.get("providers", [])

                cmd_stripped = cmd.strip()
                cmd_lower = cmd_stripped.lower()
                
                # Check if user typed bare "agy"
                if cmd_lower in ("agy", "agy.exe"):
                    append_to_terminal_log("agy", "Antigravity AI engine is active and ready. You don't need to type 'agy' first; simply type your prompt directly (e.g. 'halo', 'create login system') or any shell command (e.g. dir, git status).")
                    self.send_json_response({"ok": True})
                    return

                # If user typed "agy -p <prompt>" or "agy --print <prompt>"
                if cmd_lower.startswith("agy -p ") or cmd_lower.startswith("agy --print "):
                    prefix_len = 7 if cmd_lower.startswith("agy -p ") else 12
                    prompt_text = cmd_stripped[prefix_len:].strip().strip('"\'')
                    run_agy_prompt(prompt_text, DIRECTORY)
                    self.send_json_response({"ok": True})
                    return

                # If user typed "agy <prompt>" without flags (e.g. "agy halo" or "agy buatkan X")
                if cmd_lower.startswith("agy ") and not any(cmd_lower.startswith(f"agy {flag}") for flag in ("-", "--", "help", "agent", "models", "mcp", "plugin")):
                    prompt_text = cmd_stripped[4:].strip().strip('"\'')
                    run_agy_prompt(prompt_text, DIRECTORY)
                    self.send_json_response({"ok": True})
                    return

                # 2. Decision: Shell Command vs AI Prompt
                if is_shell_command(cmd):
                    run_powershell_subprocess(cmd, DIRECTORY)
                else:
                    active_p = [p for p in providers if p.get("valid") is not False and p.get("status") != "invalid_key" and p.get("key")]
                    if active_p:
                        try:
                            import swarm_pipeline
                            swarm_pipeline.start_swarm_pipeline_thread(cmd, DIRECTORY)
                        except Exception as e:
                            append_to_terminal_log("system", f"Swarm execution error: {str(e)}")
                            self.send_json_response({"ok": False, "error": f"Failed to start pipeline: {str(e)}"}, 500)
                            return
                    else:
                        run_agy_prompt(cmd, DIRECTORY)
                
                self.send_json_response({"ok": True})
                return
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return

        if self.path == '/api/log':
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8')
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
                return
            try:
                update = parse_log_update(json.loads(body))
                agent_id, message = update.agent, update.message
                status, progress = update.status, update.progress

                if message:
                    ts = datetime.datetime.now().strftime("%H:%M:%S")
                    os.makedirs(SPECS_DIR, exist_ok=True)
                    with open(LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(f"[{ts}] [{agent_id}] {message}\n")

                if os.path.exists(STATUS_FILE) and (status or progress is not None or message):
                    try:
                        with open(STATUS_FILE, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        for a in data.get("agents", []):
                            if a.get("id") == agent_id:
                                if message:
                                    a["processDetail"] = message
                                if status:
                                    a["status"] = status
                                if progress is not None:
                                    a["progress"] = max(0, min(100, int(progress)))
                                break
                        safe_write_json(STATUS_FILE, data)
                    except Exception:
                        pass

                self.send_json_response({"ok": True})
                return
            except Exception as e:
                self.send_json_response({"error": str(e)}, 400)
                return

        try:
            self.send_response(404)
            self.end_headers()
        except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, OSError):
            pass

import socket

BaseServerClass = getattr(http.server, "ThreadingHTTPServer", socketserver.ThreadingTCPServer)

class ThreadedSwarmServer(BaseServerClass):
    allow_reuse_address = False if sys.platform == 'win32' else True
    daemon_threads = True

    def server_bind(self):
        if sys.platform == 'win32' and hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        super().server_bind()

    def handle_error(self, request, client_address):
        exc_type, exc_val, _ = sys.exc_info()
        # Suppress harmless client socket disconnects during page refresh or quick tab close
        if exc_type in (ConnectionResetError, ConnectionAbortedError, BrokenPipeError):
            return
        if isinstance(exc_val, OSError) and getattr(exc_val, 'winerror', None) in (10053, 10054, 10058):
            return
        super().handle_error(request, client_address)

def is_port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.2)
        try:
            probe.connect(('127.0.0.1', port))
            return False
        except OSError:
            pass

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            if sys.platform != 'win32':
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            elif hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
                s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            s.bind(('127.0.0.1', port))
            return True
        except OSError:
            return False

def start_server_with_auto_port(start_port=DEFAULT_PORT, max_attempts=MAX_PORT_ATTEMPTS):
    for port in range(start_port, start_port + max_attempts):
        if not is_port_available(port):
            continue
        try:
            httpd = ThreadedSwarmServer(('127.0.0.1', port), SwarmHandler)
            return httpd, port
        except OSError:
            continue
    raise RuntimeError(f"Could not bind to any port between {start_port} and {start_port + max_attempts}")

def main():
    os.chdir(DIRECTORY)
    start_workspace_watcher(DIRECTORY)
    
    # Start background CLI detection worker
    t_cli = threading.Thread(target=cli_status_background_worker, args=(DIRECTORY,), daemon=True)
    t_cli.start()

    # Start background local provider probe worker (zero cloud cost)
    t_probe = threading.Thread(target=local_providers_probe_worker, args=(DIRECTORY,), daemon=True)
    t_probe.start()

    httpd, port = start_server_with_auto_port(DEFAULT_PORT, MAX_PORT_ATTEMPTS)
    with httpd:
        url = f"http://localhost:{port}/dashboard/"
        print(f"\n=======================================================")
        if port != DEFAULT_PORT:
            print(f"[TenAgent] Port {DEFAULT_PORT} is in use (by another project or dev server).")
            print(f"[TenAgent] Automatically switched to available port: {port}")
        print(f"TenAgent Virtual Office v1.0.1 Running at: {url}")
        print("Local operator username: tenagent")
        print(f"Local operator password: {_DASHBOARD_PASSWORD}")
        print("Set TENAGENT_DASHBOARD_PASSWORD to use a stable password.")
        print(f"Serving live specs from: {DIRECTORY}")
        print(f"Press Ctrl+C to stop the server.")
        print(f"=======================================================\n")
        
        # Auto-open browser
        try:
            webbrowser.open(url)
        except Exception:
            pass

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down TenAgent Virtual Office server. Goodbye!")
            sys.exit(0)

if __name__ == "__main__":
    main()
