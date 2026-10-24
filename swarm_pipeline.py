#!/usr/bin/env python3
"""
TenAgent Multi-Brain Collaborative Swarm Pipeline (v1.0.2)
Coordinates all 10 specialized engineering agents by dynamically distributing
workloads across connected AI provider brains (9Router, Groq, Gemini, DeepSeek, Claude, OpenAI, Ollama).
Enforces contract-first specifications, zero fake progress, honest failure reporting, and code verification.
"""

import os
import sys
import json
import time
import datetime
import threading
import urllib.request
import urllib.error
import re
import tempfile

import council

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
SPECS_DIR = os.path.join(ROOT_DIR, "specs")
LOG_FILE = os.path.join(SPECS_DIR, "terminal.log")
STATUS_FILE = os.path.join(SPECS_DIR, "swarm-status.json")

# A stage that has only *generated* output has not been verified by anything, so
# no progress value written by this pipeline may reach 100.
MAX_UNVERIFIED_PROGRESS = 90
GENERATED_PROGRESS = MAX_UNVERIFIED_PROGRESS  # per-agent value once a stage has only *generated* output

_PATH_LOCKS = {}
_PATH_LOCKS_GUARD = threading.Lock()
_KNOWN_SECRETS = set()
_WARNED = set()


def get_timestamp() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def remember_secrets(providers: list):
    """Remember provider keys so that they can be scrubbed from logs and status."""
    for p in providers or []:
        key = (p.get("key") or "").strip()
        if len(key) >= 6:
            _KNOWN_SECRETS.add(key)


def redact(text: str) -> str:
    text = str(text)
    for secret in sorted(_KNOWN_SECRETS, key=len, reverse=True):
        text = text.replace(secret, "[REDACTED]")
    return text


def status_lock(path: str):
    """In-process lock guarding read-modify-write of one status file."""
    key = os.path.normcase(os.path.abspath(path))
    with _PATH_LOCKS_GUARD:
        return _PATH_LOCKS.setdefault(key, threading.RLock())


def atomic_write_text(path: str, text: str):
    """Write via a unique temp file in the same directory, then os.replace."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=os.path.basename(path) + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(6):
            try:
                os.replace(tmp_path, path)
                return
            except PermissionError:
                # Windows: a reader (e.g. the dashboard) briefly holds the target open.
                if attempt == 5:
                    raise
                time.sleep(0.02 * (attempt + 1))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def log_swarm_message(agent_id: str, message: str, root_dir: str = None):
    target_log = os.path.join(root_dir or ROOT_DIR, "specs", "terminal.log")
    ts = get_timestamp()
    clean_msg = redact(message).strip()
    if not clean_msg:
        return
    log_line = f"[{ts}] [{agent_id}] {clean_msg}\n"

    try:
        print(f"[{agent_id}] {clean_msg}")
        sys.stdout.flush()
    except Exception:
        pass

    try:
        os.makedirs(os.path.dirname(target_log), exist_ok=True)
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass


def _mutate_status(root_dir: str, mutate) -> bool:
    """Locked, atomic read-modify-write of specs/swarm-status.json.

    Returns False (and says so in the log, once) when the file is absent or
    unreadable instead of silently pretending the update happened.
    """
    base = root_dir or ROOT_DIR
    target = os.path.join(base, "specs", "swarm-status.json")
    if not os.path.exists(target):
        return False
    with status_lock(target):
        try:
            with open(target, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("status root must be a JSON object")
            mutate(data)
            atomic_write_text(target, json.dumps(data, indent=2))
            return True
        except Exception as exc:
            marker = (os.path.normcase(target), type(exc).__name__)
            if marker not in _WARNED:
                _WARNED.add(marker)
                log_swarm_message(
                    "swarm", f"[WARNING] specs/swarm-status.json not updated ({type(exc).__name__}); "
                    "the dashboard may show stale state.", base)
            return False


def reset_swarm_status(root_dir: str = None) -> bool:
    """Start of a run: drop progress and states inherited from any previous run."""
    def mutate(data):
        project = data.setdefault("project", {})
        project["overallProgress"] = 0
        project["phase"] = "Run starting"
        for agent in data.get("agents", []):
            agent["status"] = "WAITING"
            agent["progress"] = 0
            agent["processDetail"] = "Queued for this swarm run."
    return _mutate_status(root_dir, mutate)


def update_swarm_status(agent_id: str, status: str, process_detail: str, progress: int = None, root_dir: str = None, overall_progress: int = None, phase: str = None) -> bool:
    detail = redact(process_detail or "")

    def mutate(data):
        if overall_progress is not None and "project" in data:
            data["project"]["overallProgress"] = max(0, min(MAX_UNVERIFIED_PROGRESS, int(overall_progress)))
        if phase and "project" in data:
            data["project"]["phase"] = redact(phase)

        for a in data.get("agents", []):
            if a.get("id") == agent_id:
                if status:
                    a["status"] = status
                if detail:
                    a["processDetail"] = detail
                if progress is not None:
                    a["progress"] = max(0, min(MAX_UNVERIFIED_PROGRESS, int(progress)))
                break

        if "logs" not in data:
            data["logs"] = []
        data["logs"].append({
            "timestamp": get_timestamp(),
            "agent": agent_id,
            "message": f"[{agent_id}] {detail[:140]}"
        })
        data["logs"] = data["logs"][-50:]

    return _mutate_status(root_dir, mutate)

def assign_brains_to_agents(providers: list) -> dict:
    if not providers:
        fallback = {
            "id": "native",
            "name": "Native Antigravity Engine",
            "key": "",
            "profile": {"name": "Native Engine", "role": "Full-Stack Specialist", "tag": "native"}
        }
        return {aid: fallback for aid in [
            "01_pm", "02_arch", "03_designer", "04_dba", "05_backend",
            "06_client", "07_qa", "08_security", "09_devops", "10_tech_lead"
        ]}

    fast_brains = [p for p in providers if "groq" in p.get("id", "")]
    deep_brains = [p for p in providers if any(k in p.get("id", "") for k in ("9router", "deepseek", "claude", "anthropic", "openai"))]
    creative_brains = [p for p in providers if any(k in p.get("id", "") for k in ("gemini", "google", "claude"))]
    fallback = providers[0]

    pm_brain = (creative_brains or deep_brains or providers)[0]
    arch_brain = (deep_brains or creative_brains or providers)[0]
    designer_brain = (creative_brains or providers)[-1]
    dba_brain = (deep_brains or providers)[0]
    backend_brain = (deep_brains or providers)[0]
    client_brain = (creative_brains or deep_brains or providers)[-1]
    qa_brain = (fast_brains or providers)[0]
    sec_brain = (fast_brains or deep_brains or providers)[-1]
    devops_brain = (deep_brains or providers)[-1]
    lead_brain = (deep_brains or creative_brains or providers)[0]

    return {
        "01_pm": pm_brain,
        "02_arch": arch_brain,
        "03_designer": designer_brain,
        "04_dba": dba_brain,
        "05_backend": backend_brain,
        "06_client": client_brain,
        "07_qa": qa_brain,
        "08_security": sec_brain,
        "09_devops": devops_brain,
        "10_tech_lead": lead_brain
    }

def clean_markdown_block(text: str, code_fence: str = None) -> str:
    cleaned = text.strip()
    if code_fence:
        pattern = f"```{code_fence}"
        if pattern in cleaned:
            parts = cleaned.split(pattern, 1)[1]
            if "```" in parts:
                cleaned = parts.split("```", 1)[0].strip()
        elif "```" in cleaned:
            parts = cleaned.split("```", 1)[1]
            if "```" in parts:
                cleaned = parts.split("```", 1)[0].strip()
    return cleaned

def safe_call_brain(brain: dict, system_prompt: str, user_prompt: str, fallback_brains: list = None, base_dir: str = None) -> tuple:
    """
    Calls assigned AI brain with fallback chain.
    Returns (content_str, success_bool).
    If all brains fail, returns ('', False) to allow honest failure handling (Fail Loudly).
    """
    if brain.get("id") == "native":
        return "", False

    try:
        res = council.call_llm(brain, system_prompt, user_prompt, timeout=75)
        if res and res.strip():
            return res.strip(), True
    except Exception as e:
        log_swarm_message("swarm", f"Notice: [{brain['name']}] latency ({str(e)[:45]}). Engaging backup brain...", base_dir)

    if fallback_brains:
        for fb in fallback_brains:
            if fb.get("id") != brain.get("id") and fb.get("id") != "native":
                try:
                    res = council.call_llm(fb, system_prompt, user_prompt, timeout=60)
                    if res and res.strip():
                        log_swarm_message("swarm", f"Assisted by backup brain: [{fb['name']}]", base_dir)
                        return res.strip(), True
                except Exception:
                    continue

    return "", False

def execute_multi_brain_swarm(goal: str, root_dir: str = None):
    base_dir = root_dir or ROOT_DIR
    providers = council.get_active_providers(base_dir)
    remember_secrets(providers)
    reset_swarm_status(base_dir)
    brains = assign_brains_to_agents(providers)

    if not providers:
        log_swarm_message("swarm", "[ERROR] No active AI provider; no engineering stages executed.", base_dir)
        update_swarm_status("01_pm", "ERROR", "No AI provider available.", 0, base_dir, overall_progress=0, phase="FAILED: NO_PROVIDER")
        return False

    log_swarm_message("swarm", f"=== Multi-Brain Collaborative Swarm Activated for: '{goal[:60]}...' ===", base_dir)
    log_swarm_message("swarm", f"Active Brains: {', '.join(p['name'] for p in providers)}", base_dir)
    log_swarm_message("swarm", f"Assignments: PM->{brains['01_pm']['name']} | Arch->{brains['02_arch']['name']} | Design->{brains['03_designer']['name']} | DBA->{brains['04_dba']['name']} | Backend->{brains['05_backend']['name']} | Client->{brains['06_client']['name']} | QA->{brains['07_qa']['name']} | Sec->{brains['08_security']['name']} | DevOps->{brains['09_devops']['name']} | Lead->{brains['10_tech_lead']['name']}", base_dir)

    TOTAL_MILESTONES = 10
    completed_milestones = 0

    def compute_progress(step_num):
        # Generation alone cannot satisfy the downstream verification/release gates.
        return min(90, int((step_num / TOTAL_MILESTONES) * 90))

    # -------------------------------------------------------------
    # PRE-FLIGHT MULTI-AI COUNCIL DEBATE (If 2+ Providers Connected)
    # -------------------------------------------------------------
    debate_context = ""
    if len(providers) >= 2:
        log_swarm_message("swarm", f"Engaging pre-flight debate between {len(providers)} active brains...", base_dir)
        update_swarm_status("10_tech_lead", "WORKING", f"Synthesizing multi-model council debate on '{goal[:35]}...'", 20, base_dir, phase="Phase 0: Multi-AI Council Debate")
        debate_res = council.run_council_debate(f"Architecture, Race Conditions, and Edge Cases for: {goal}", base_dir)
        if debate_res and debate_res.get("consensus"):
            debate_context = f"\n\n## Multi-AI Council Pre-Flight Debate Consensus:\n{debate_res['consensus']}\n"
            log_swarm_message("10_tech_lead", "Council consensus established and fed into PRD/Architecture pipelines.", base_dir)
        elif debate_res and debate_res.get("status") == "failed":
            log_swarm_message("10_tech_lead", f"[WARNING] Council pre-flight debate inconclusive: {debate_res.get('error')}. Proceeding with individual agent governance.", base_dir)
        update_swarm_status("10_tech_lead", "WAITING", "Standing by to review deliverables against Quality Gates.", 0, base_dir)

    # -------------------------------------------------------------
    # STAGE 1: 01_PM (Product Manager)
    # -------------------------------------------------------------
    b_pm = brains["01_pm"]
    log_swarm_message("01_pm", f"Brain [{b_pm['name']}]: Formulating PRD, User Stories, and Acceptance Criteria...", base_dir)
    update_swarm_status("01_pm", "WORKING", f"[{b_pm['name']}] Writing specs/prd/user-stories.md", 30, base_dir, phase="Phase 1: PRD & Requirements")

    pm_sys = (
        "You are the Product Manager in an autonomous software engineering swarm. "
        "Formulate a complete, professional Product Requirements Document (PRD). "
        "Include: 1) Executive Summary, 2) Target End-User Persona, 3) Core MVP User Stories with Acceptance Criteria (Given-When-Then format), "
        "and 4) Scope Boundaries. Output clean, crafted Markdown adhering to anti-slop guidelines."
    )
    prd_content, ok = safe_call_brain(b_pm, pm_sys, f"Project Goal: {goal}{debate_context}", providers, base_dir)
    if not ok or not prd_content.strip():
        err_msg = f"Stage 01_pm FAILED: All connected AI brains failed to respond. Halting pipeline to prevent silent corruption."
        log_swarm_message("01_pm", f"[FATAL ERROR] {err_msg}", base_dir)
        update_swarm_status("01_pm", "ERROR", "Generation failed. API offline or quota exhausted.", 0, base_dir, phase="FAILED: 01_PM")
        return False

    prd_dir = os.path.join(base_dir, "specs", "prd")
    os.makedirs(prd_dir, exist_ok=True)
    with open(os.path.join(prd_dir, "user-stories.md"), "w", encoding="utf-8") as f:
        f.write(prd_content.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("01_pm", f"Deliverable locked: specs/prd/user-stories.md ({len(prd_content)} bytes)", base_dir)
    update_swarm_status("01_pm", "REVIEWING", "PRD locked. Handoff to 02_arch.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 2: 02_Arch (System Architect)
    # -------------------------------------------------------------
    b_arch = brains["02_arch"]
    log_swarm_message("02_arch", f"Brain [{b_arch['name']}]: Establishing Clean Architecture layer boundaries (ADR-001)...", base_dir)
    update_swarm_status("02_arch", "WORKING", f"[{b_arch['name']}] Writing specs/architecture/adr-001.md", 35, base_dir, phase="Phase 2: Architecture & ADR")

    arch_sys = (
        "You are the System Architect in an autonomous software engineering swarm. "
        "Read the PRD context and formulate Architecture Decision Record ADR-001. "
        "Include: 1) Architectural Style (Clean Architecture separating Domain, UseCase, Repository, Controller layers), "
        "2) Tech Stack Decision with trade-offs, 3) Layer Dependency Inversion rules, 4) Concrete Directory Layout. Output clean Markdown."
    )
    arch_content, ok = safe_call_brain(b_arch, arch_sys, f"PRD Context:\n{prd_content[:2000]}\n\nTask: Design Clean Architecture for {goal}", providers, base_dir)
    if not ok or not arch_content.strip():
        err_msg = "Stage 02_arch FAILED: Architecture generation failed across all AI brains."
        log_swarm_message("02_arch", f"[FATAL ERROR] {err_msg}", base_dir)
        update_swarm_status("02_arch", "ERROR", "Generation failed. API offline.", 0, base_dir, phase="FAILED: 02_ARCH")
        return False

    arch_dir = os.path.join(base_dir, "specs", "architecture")
    os.makedirs(arch_dir, exist_ok=True)
    with open(os.path.join(arch_dir, "adr-001.md"), "w", encoding="utf-8") as f:
        f.write(arch_content.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("02_arch", f"Deliverable locked: specs/architecture/adr-001.md", base_dir)
    update_swarm_status("02_arch", "REVIEWING", "Architecture locked. Handoff to 03_designer & 04_dba.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 3: 03_Designer (UI/UX Designer)
    # -------------------------------------------------------------
    b_des = brains["03_designer"]
    log_swarm_message("03_designer", f"Brain [{b_des['name']}]: Synthesizing design tokens, typography, and screen navigation...", base_dir)
    update_swarm_status("03_designer", "WORKING", f"[{b_des['name']}] Writing specs/design/tokens.json & screen-flows.md", 40, base_dir, phase="Phase 3: Design Tokens & UI/UX")

    des_sys = (
        "You are the Senior UI/UX Designer enforcing anti-slop guidelines (WCAG AA contrast, purposeful tokens, tactile controls). "
        "Generate a valid JSON object of design tokens containing: colors (primary, surface, background, border, textPrimary, accent), "
        "typography (fontFamily, scale), and spacing. Only output pure JSON inside a markdown ```json block."
    )
    tokens_raw, ok = safe_call_brain(b_des, des_sys, f"Project Goal: {goal}\nPRD Context:\n{prd_content[:1500]}", providers, base_dir)
    tokens_clean = clean_markdown_block(tokens_raw, "json") if ok else ""
    try:
        if not tokens_clean or not isinstance(json.loads(tokens_clean), dict):
            raise ValueError("Design tokens must be a nonempty JSON object.")
    except (ValueError, json.JSONDecodeError) as exc:
        log_swarm_message("03_designer", f"[ERROR] Design token generation invalid: {exc}", base_dir)
        update_swarm_status("03_designer", "ERROR", "Invalid or missing design tokens.", 0, base_dir, phase="FAILED: 03_DESIGNER")
        return False

    design_dir = os.path.join(base_dir, "specs", "design")
    os.makedirs(design_dir, exist_ok=True)
    with open(os.path.join(design_dir, "tokens.json"), "w", encoding="utf-8") as f:
        f.write(tokens_clean.strip() + "\n")

    screen_flow_sys = (
        "You are the Senior UI/UX Designer. Create a concise Screen Flow Document (screen-flows.md). "
        "Detail the primary user journeys, screen layout hierarchy, and tactile interaction patterns. Output clean Markdown."
    )
    screen_flow_content, flow_ok = safe_call_brain(b_des, screen_flow_sys, f"Project: {goal}\nTokens:\n{tokens_clean[:500]}", providers, base_dir)
    if not flow_ok or not screen_flow_content.strip():
        log_swarm_message("03_designer", "[ERROR] Screen-flow generation failed.", base_dir)
        update_swarm_status("03_designer", "ERROR", "Screen flows unavailable.", 0, base_dir, phase="FAILED: 03_DESIGNER")
        return False
    with open(os.path.join(design_dir, "screen-flows.md"), "w", encoding="utf-8") as f:
        f.write(screen_flow_content.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("03_designer", "Deliverables locked: specs/design/tokens.json & screen-flows.md", base_dir)
    update_swarm_status("03_designer", "REVIEWING", "Design specifications complete.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 4: 04_DBA (Database Engineer)
    # -------------------------------------------------------------
    b_dba = brains["04_dba"]
    log_swarm_message("04_dba", f"Brain [{b_dba['name']}]: Designing 3NF database schema & OpenAPI 3.0 contract...", base_dir)
    update_swarm_status("04_dba", "WORKING", f"[{b_dba['name']}] Writing specs/database/schema.sql & openapi.yaml", 40, base_dir, phase="Phase 4: Database & API Contract")

    dba_sys = (
        "You are the Database Engineer. Produce a production-grade 3NF normalized SQL schema. "
        "Enforce zero redundant tables, primary keys (UUID/VARCHAR), foreign keys with indexes, timestamps (created_at, updated_at). "
        "Only output pure valid SQL inside a markdown ```sql code block."
    )
    sql_raw, ok = safe_call_brain(b_dba, dba_sys, f"Project: {goal}\nArchitecture Context:\n{arch_content[:1500]}", providers, base_dir)
    if not ok or not sql_raw.strip():
        err_msg = "Stage 04_dba FAILED: Database schema generation failed across all AI brains."
        log_swarm_message("04_dba", f"[FATAL ERROR] {err_msg}", base_dir)
        update_swarm_status("04_dba", "ERROR", "Generation failed. API offline.", 0, base_dir, phase="FAILED: 04_DBA")
        return False

    sql_clean = clean_markdown_block(sql_raw, "sql")
    db_dir = os.path.join(base_dir, "specs", "database")
    os.makedirs(db_dir, exist_ok=True)
    with open(os.path.join(db_dir, "schema.sql"), "w", encoding="utf-8") as f:
        f.write(sql_clean.strip() + "\n")

    api_sys = (
        "You are an API Architect. Generate a complete OpenAPI 3.0 YAML specification for this system. "
        "Include health check, CRUD endpoints, request/response schemas. Only output pure valid YAML inside a markdown ```yaml code block."
    )
    api_raw, ok = safe_call_brain(b_dba, api_sys, f"Project: {goal}\nDatabase Schema:\n{sql_clean[:1500]}", providers, base_dir)
    api_clean = clean_markdown_block(api_raw, "yaml") if ok else ""
    if not api_clean or "openapi:" not in api_clean:
        log_swarm_message("04_dba", "[ERROR] OpenAPI generation returned no contract.", base_dir)
        update_swarm_status("04_dba", "ERROR", "Missing OpenAPI specification.", 0, base_dir, phase="FAILED: 04_DBA")
        return False

    api_dir = os.path.join(base_dir, "specs", "api")
    os.makedirs(api_dir, exist_ok=True)
    with open(os.path.join(api_dir, "openapi.yaml"), "w", encoding="utf-8") as f:
        f.write(api_clean.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("04_dba", "Deliverables locked: specs/database/schema.sql & specs/api/openapi.yaml", base_dir)
    update_swarm_status("04_dba", "REVIEWING", "Schema and OpenAPI locked. Handoff to 05_backend & 06_client.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 5: 05_Backend (Backend Engineer)
    # -------------------------------------------------------------
    b_back = brains["05_backend"]
    log_swarm_message("05_backend", f"Brain [{b_back['name']}]: Scaffolding domain entities, use cases, and REST routes...", base_dir)
    update_swarm_status("05_backend", "WORKING", f"[{b_back['name']}] Writing backend/src/ domain layer", 50, base_dir, phase="Phase 5: Backend Domain Implementation")

    backend_sys = (
        "You are the Backend Engineer. Implement core domain entities, repository interfaces, and use-case handlers "
        "matching the OpenAPI specification and database schema. Provide clean, self-contained Python code adhering to Clean Architecture. "
        "Only output pure valid Python code inside a markdown ```python block."
    )
    code_raw, ok = safe_call_brain(b_back, backend_sys, f"Goal: {goal}\nOpenAPI:\n{api_clean[:1200]}\nSchema:\n{sql_clean[:1200]}", providers, base_dir)
    if not ok or not code_raw.strip():
        err_msg = "Stage 05_backend FAILED: Backend code generation failed across all AI brains."
        log_swarm_message("05_backend", f"[FATAL ERROR] {err_msg}", base_dir)
        update_swarm_status("05_backend", "ERROR", "Generation failed. API offline.", 0, base_dir, phase="FAILED: 05_BACKEND")
        return False

    code_clean = clean_markdown_block(code_raw, "python")
    try:
        if not code_clean:
            raise SyntaxError("Empty Python source")
        compile(code_clean, "generated-backend", "exec")
    except SyntaxError as exc:
        log_swarm_message("05_backend", f"[ERROR] Invalid backend Python: {exc}", base_dir)
        update_swarm_status("05_backend", "ERROR", "Invalid backend syntax.", 0, base_dir, phase="FAILED: 05_BACKEND")
        return False
    backend_src = os.path.join(base_dir, "backend", "src")
    os.makedirs(backend_src, exist_ok=True)
    with open(os.path.join(backend_src, "main.py"), "w", encoding="utf-8") as f:
        f.write(code_clean.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("05_backend", "Deliverable locked: backend/src/main.py", base_dir)
    update_swarm_status("05_backend", "REVIEWING", "Backend domain implementation complete.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 6: 06_Client (Client Engineer)
    # -------------------------------------------------------------
    b_client = brains["06_client"]
    log_swarm_message("06_client", f"Brain [{b_client['name']}]: Scaffolding client interface views & API integration...", base_dir)
    update_swarm_status("06_client", "WORKING", f"[{b_client['name']}] Building client views consuming OpenAPI & tokens", 50, base_dir, phase="Phase 6: Client UI Implementation")

    client_sys = (
        "You are the Client Engineer. Build a clean, tactile frontend application component (or HTML5/JavaScript dashboard view) "
        "that consumes the REST API endpoints and applies the design tokens from specs/design/tokens.json. "
        "Output clean code inside a markdown ```html code block."
    )
    client_raw, ok = safe_call_brain(b_client, client_sys, f"Goal: {goal}\nAPI Contract:\n{api_clean[:1000]}\nTokens:\n{tokens_clean[:600]}", providers, base_dir)
    client_clean = clean_markdown_block(client_raw, "html") if ok else ""
    if not client_clean.strip():
        log_swarm_message("06_client", "[ERROR] Client implementation was not generated.", base_dir)
        update_swarm_status("06_client", "ERROR", "Client generation failed.", 0, base_dir, phase="FAILED: 06_CLIENT")
        return False

    frontend_dir = os.path.join(base_dir, "frontend", "public")
    os.makedirs(frontend_dir, exist_ok=True)
    with open(os.path.join(frontend_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(client_clean.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("06_client", "Deliverable locked: frontend/public/index.html", base_dir)
    update_swarm_status("06_client", "REVIEWING", "Client view components compiled.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 7: 07_QA (QA Engineer)
    # -------------------------------------------------------------
    b_qa = brains["07_qa"]
    log_swarm_message("07_qa", f"Brain [{b_qa['name']}]: Generating QA Test Matrix and executable unit test suite...", base_dir)
    update_swarm_status("07_qa", "WORKING", f"[{b_qa['name']}] Formulating test matrix & writing tests/test_api.py", 60, base_dir, phase="Phase 7: QA Test Engineering")

    qa_sys = (
        "You are the QA Engineer. 1) Analyze the API specification and implementation, 2) Formulate a QA Test Matrix "
        "covering Happy Path, Edge Cases, Boundary Limits, and Concurrency Scenarios. Output clean Markdown."
    )
    qa_raw, ok = safe_call_brain(b_qa, qa_sys, f"Goal: {goal}\nAPI Contract:\n{api_clean[:1200]}\nBackend Code:\n{code_clean[:1200]}", providers, base_dir)
    if not ok or not qa_raw.strip():
        log_swarm_message("07_qa", "[ERROR] QA test matrix missing.", base_dir)
        update_swarm_status("07_qa", "ERROR", "QA matrix generation failed.", 0, base_dir, phase="FAILED: 07_QA")
        return False
    qa_dir = os.path.join(base_dir, "specs", "qa")
    os.makedirs(qa_dir, exist_ok=True)
    with open(os.path.join(qa_dir, "test-matrix.md"), "w", encoding="utf-8") as f:
        f.write(qa_raw.strip() + "\n")

    # Generate executable test file
    test_code_sys = (
        "You are the QA Engineer. Write a self-contained, executable Python unittest suite (tests/test_api.py) "
        "testing the domain entity constraints, input boundaries, and error cases from the backend implementation. "
        "Only output pure valid Python code inside a markdown ```python block."
    )
    test_code_raw, tests_ok = safe_call_brain(b_qa, test_code_sys, f"Goal: {goal}\nBackend Code:\n{code_clean[:1500]}", providers, base_dir)
    test_clean = clean_markdown_block(test_code_raw, "python")
    if not tests_ok or not test_clean.strip() or "assertTrue(True)" in test_clean:
        log_swarm_message("07_qa", "[ERROR] QA tests missing or tautological.", base_dir)
        update_swarm_status("07_qa", "ERROR", "No usable generated tests.", 0, base_dir, phase="FAILED: 07_QA")
        return False
    try:
        compile(test_clean, "generated-test", "exec")
    except SyntaxError as exc:
        log_swarm_message("07_qa", f"[ERROR] Generated QA tests have invalid syntax: {exc}", base_dir)
        update_swarm_status("07_qa", "ERROR", "Invalid test syntax.", 0, base_dir, phase="FAILED: 07_QA")
        return False

    tests_dir = os.path.join(base_dir, "tests")
    os.makedirs(tests_dir, exist_ok=True)
    with open(os.path.join(tests_dir, "test_api.py"), "w", encoding="utf-8") as f:
        f.write(test_clean.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("07_qa", "QA tests generated; NOT executed or verified.", base_dir)
    update_swarm_status("07_qa", "REVIEWING", "Generated test source requires isolated test execution.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 8: 08_Security (Security Engineer - Real Code Audit)
    # -------------------------------------------------------------
    b_sec = brains["08_security"]
    log_swarm_message("08_security", f"Brain [{b_sec['name']}]: Auditing backend source code & schema against OWASP Top 10...", base_dir)
    update_swarm_status("08_security", "WORKING", f"[{b_sec['name']}] Performing code-level OWASP vulnerability inspection", 70, base_dir, phase="Phase 8: Security Vulnerability Audit")

    sec_sys = (
        "You are an OWASP Application Security Auditor. Perform an objective code-level security audit on the provided "
        "backend source code and database schema. Audit against: 1) Injection vulnerabilities (SQL/Command), 2) Broken Authentication/Token lifecycles, "
        "3) Sensitive Data Exposure, 4) Security Misconfiguration, 5) Input Validation. "
        "For each category, provide status (PASS / WARN / FAIL) with concrete line references and remediation notes. Output clean Markdown."
    )
    sec_raw, ok = safe_call_brain(b_sec, sec_sys, f"Backend Code:\n{code_clean[:1800]}\n\nDatabase Schema:\n{sql_clean[:1200]}", providers, base_dir)
    if not ok or not sec_raw.strip():
        log_swarm_message("08_security", "[ERROR] Security review model did not respond.", base_dir)
        update_swarm_status("08_security", "ERROR", "No security review generated.", 0, base_dir, phase="FAILED: 08_SECURITY")
        return False
    sec_dir = os.path.join(base_dir, "specs", "security")
    os.makedirs(sec_dir, exist_ok=True)
    with open(os.path.join(sec_dir, "audit-report.md"), "w", encoding="utf-8") as f:
        f.write("# AI security review (advisory, unverified)\n\n"
                "No automated scanner or real security test was executed by this stage.\n\n"
                + sec_raw.strip() + "\n")

    completed_milestones += 1
    log_swarm_message("08_security", "Advisory security review generated; security gate NOT verified.", base_dir)
    update_swarm_status("08_security", "REVIEWING", "Advisory review only; independent scanning required.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 9: 09_DevOps (DevOps Engineer)
    # -------------------------------------------------------------
    b_dev = brains["09_devops"]
    log_swarm_message("09_devops", f"Brain [{b_dev['name']}]: Designing reproducible multi-stage Docker build & CI workflow...", base_dir)
    update_swarm_status("09_devops", "WORKING", f"[{b_dev['name']}] Writing Dockerfile and .github/workflows/ci.yml", 80, base_dir, phase="Phase 9: DevOps & Containerization")

    docker_sys = (
        "You are the DevOps Engineer. Generate a production-grade multi-stage Dockerfile for this service. "
        "Enforce minimal attack surface (distroless/alpine), non-root user, health checks, and reproducible builds. "
        "Only output pure valid Dockerfile content inside a markdown ```dockerfile block."
    )
    docker_raw, docker_ok = safe_call_brain(b_dev, docker_sys, f"Goal: {goal}\nTech Stack Context:\n{arch_content[:1000]}", providers, base_dir)
    docker_clean = clean_markdown_block(docker_raw, "dockerfile")
    if not docker_ok or not docker_clean.strip():
        log_swarm_message("09_devops", "[ERROR] Dockerfile generation failed.", base_dir)
        update_swarm_status("09_devops", "ERROR", "No Dockerfile generated.", 0, base_dir, phase="FAILED: 09_DEVOPS")
        return False

    # Stage generated DevOps files separately; never overwrite TenAgent's own
    # Dockerfile and CI pipeline with unreviewed model-generated output.
    devops_dir = os.path.join(base_dir, "specs", "devops")
    os.makedirs(devops_dir, exist_ok=True)
    with open(os.path.join(devops_dir, "Dockerfile"), "w", encoding="utf-8") as f:
        f.write(docker_clean.strip() + "\n")

    # Generate CI workflow
    ci_workflow = (
        "name: CI Pipeline\n"
        "on: [push, pull_request]\n"
        "jobs:\n"
        "  verify:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - name: Set up Python\n"
        "        uses: actions/setup-python@v5\n"
        "        with:\n"
        "          python-version: '3.11'\n"
        "      - name: Run Quality Gate Tests\n"
        "        run: |\n"
        "          python -m unittest discover tests\n"
    )
    with open(os.path.join(devops_dir, "ci.yml"), "w", encoding="utf-8") as f:
        f.write(ci_workflow)

    completed_milestones += 1
    log_swarm_message("09_devops", "Generated specs/devops/Dockerfile and ci.yml; NOT built or executed.", base_dir)
    update_swarm_status("09_devops", "REVIEWING", "Generated DevOps templates require verification.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones))
    time.sleep(0.5)

    # -------------------------------------------------------------
    # STAGE 10: 10_Tech Lead (Gatekeeper Review & Signoff)
    # -------------------------------------------------------------
    b_lead = brains["10_tech_lead"]
    log_swarm_message("10_tech_lead", f"Brain [{b_lead['name']}]: Evaluating deliverables against all 6 Quality Gates...", base_dir)
    update_swarm_status("10_tech_lead", "WORKING", f"[{b_lead['name']}] Evaluating artifacts for production signoff", 90, base_dir, phase="Phase 10: Final Quality Gate Audit")

    lead_sys = (
        "You are the Technical Lead and ultimate gatekeeper in an elite engineering swarm. "
        "Critically evaluate the generated project deliverables: 1) PRD, 2) Clean Architecture ADR, 3) 3NF Schema & OpenAPI, "
        "4) Backend Implementation, 5) Client Views, 6) QA Matrix & Executable Tests, 7) Security Code Audit. "
        "Verify: No architectural drift, no silent failures, contract compliance. "
        "Output an advisory review only: [READY FOR INDEPENDENT VERIFICATION] or [REJECTED - REMEDIATION REQUIRED]. Do not authorize production release."
    )
    review_context = f"Project: {goal}\nPRD:\n{prd_content[:600]}\nADR:\n{arch_content[:600]}\nBackend:\n{code_clean[:800]}\nSecurity:\n{sec_raw[:600] if 'sec_raw' in locals() else 'Passed'}"
    lead_raw, ok = safe_call_brain(b_lead, lead_sys, review_context, providers, base_dir)

    signoff_path = os.path.join(base_dir, "specs", "signoff.md")
    if not ok or not lead_raw.strip():
        log_swarm_message("10_tech_lead", "[ERROR] Technical review generation failed.", base_dir)
        update_swarm_status("10_tech_lead", "ERROR", "No lead review available.", 0, base_dir, phase="FAILED: 10_TECH_LEAD")
        return False

    review_rejected = "REJECTED" in lead_raw.upper()
    # Even an optimistic model verdict is only an opinion, not release proof.
    advisory = re.sub(r"approved\s+for\s+production", "AI MODEL OPINION ONLY", lead_raw, flags=re.I)
    with open(signoff_path, "w", encoding="utf-8") as f:
        f.write("# Draft technical review: NOT VERIFIED FOR PRODUCTION\n\n")
        f.write("No generated QA tests, security scanners, builds or CI jobs were run "
                "by this pipeline. Independent checks are still required.\n\n")
        f.write(advisory.strip() + "\n")

    if review_rejected:
        log_swarm_message("10_tech_lead", "[REJECTED] Model review flagged issues for remediation.", base_dir)
        update_swarm_status("10_tech_lead", "ERROR", "Model review rejected deliverables.", 0, base_dir, phase="FAILED: LEAD_REVIEW")
        return False

    completed_milestones += 1
    log_swarm_message("10_tech_lead", "Generation stages complete, but production readiness remains UNVERIFIED.", base_dir)
    update_swarm_status("10_tech_lead", "REVIEWING", "Pending independent QA, security and CI evidence.", GENERATED_PROGRESS, base_dir, overall_progress=compute_progress(completed_milestones), phase="Generated: Awaiting Verification")
    log_swarm_message("swarm", "=== Draft Generated; NOT Verified or Approved for Production ===", base_dir)
    return True

def start_swarm_pipeline_thread(goal: str, root_dir: str = None):
    t = threading.Thread(target=execute_multi_brain_swarm, args=(goal, root_dir), daemon=True)
    t.start()
    return t

if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "Automated Inventory POS System"
    execute_multi_brain_swarm(prompt)
