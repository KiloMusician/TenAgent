#!/usr/bin/env python3
"""
TenAgent Autonomous Dynamic Multi-AI Council & Debate Engine (v1.0.1)
Coordinates real-time multi-model debates and peer consultations
among any connected AI providers (Groq, Gemini, DeepSeek, Claude, OpenAI, etc.).
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import urllib.error

try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT_DIR = os.path.abspath(os.path.dirname(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
from dashboard.security import scrub_log_text  # one scrubber for every log writer
SPECS_DIR = os.path.join(ROOT_DIR, "specs")
CONFIG_FILE = os.path.join(SPECS_DIR, "swarm-config.json")
STATUS_FILE = os.path.join(SPECS_DIR, "swarm-status.json")
LOG_FILE = os.path.join(SPECS_DIR, "terminal.log")

BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Dynamic persona and mission generator based on provider type
PROVIDER_PROFILES = {
    "groq": {
        "name": "Groq (GPT-OSS-120B)",
        "role": "Adversarial Red Team & Bug Hunter",
        "tag": "groq_challenger",
        "style": "Fast, critical, hyper-focused on edge cases, race conditions, and vulnerabilities."
    },
    "gemini": {
        "name": "Google Gemini (2.5 Flash)",
        "role": "Scalability & Architecture Consultant",
        "tag": "gemini_advisor",
        "style": "Holistic, architectural, balancing developer experience with system scale."
    },
    "deepseek": {
        "name": "DeepSeek (V3/R1)",
        "role": "Algorithm & Logic Specialist",
        "tag": "deepseek_logic",
        "style": "Deep algorithmic analysis, data structure optimization, and strict logic verification."
    },
    "anthropic": {
        "name": "Anthropic Claude (3.5 Sonnet)",
        "role": "Clean Code & UX Perfectionist",
        "tag": "claude_auditor",
        "style": "Clean Architecture adherence, strict boundaries, anti-slop guidelines."
    },
    "openai": {
        "name": "OpenAI (GPT-4o)",
        "role": "Business Domain & API Strategist",
        "tag": "openai_strategist",
        "style": "Enterprise patterns, robust API design, and user story completeness."
    },
    "ollama": {
        "name": "Ollama (Local LLM)",
        "role": "Local Privacy & Offline Auditor",
        "tag": "ollama_local",
        "style": "Lightweight, privacy-focused, zero-leak review."
    },
    "9router": {
        "name": "9Router (Gateway)",
        "role": "Full-Stack System Architect",
        "tag": "9router_architect",
        "style": "Pragmatic, clean architectural layering, robust API contract design."
    }
}

def get_active_providers(root_dir: str = None) -> list:
    """Reads specs/swarm-config.json and returns only active/valid providers with keys."""
    base = root_dir or ROOT_DIR
    cfg_path = os.path.join(base, "specs", "swarm-config.json")
    if not os.path.exists(cfg_path):
        example_path = os.path.join(base, "specs", "swarm-config.example.json")
        if os.path.exists(example_path):
            try:
                import shutil
                shutil.copy2(example_path, cfg_path)
            except Exception:
                pass
    if not os.path.exists(cfg_path):
        return []

    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        providers = cfg.get("providers", [])
        active = []
        for p in providers:
            p_id = (p.get("provider") or "").lower().strip()
            key = (p.get("key") or "").strip()
            b_url = (p.get("baseUrl") or p.get("base_url") or "").strip()
            model = p.get("model") or ("ag/gemini-3.8-flash" if "9router" in p_id else "")
            # Must have key and not marked invalid
            if key and p.get("status") != "invalid_key" and p.get("valid") is not False:
                active.append({
                    "id": p_id,
                    "key": key,
                    "baseUrl": b_url,
                    "model": model,
                    "name": p.get("name") or PROVIDER_PROFILES.get(p_id, {}).get("name", p_id.upper()),
                    "profile": PROVIDER_PROFILES.get(p_id, {
                        "name": p_id.upper(),
                        "role": "Senior Peer Reviewer",
                        "tag": f"{p_id}_agent",
                        "style": "Constructive technical review and optimization."
                    })
                })
        return active
    except Exception:
        return []

def log_council_message(tag: str, message: str, root_dir: str = None):
    """Logs message to specs/terminal.log and mirrors to console."""
    message = scrub_log_text(message)
    ts = datetime.datetime.now().strftime("%H:%M:%S")
    target_log = os.path.join(root_dir or ROOT_DIR, "specs", "terminal.log")
    log_line = f"[{ts}] [{tag}] {message}\n"
    
    try:
        safe_msg = message.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8')
        print(f"[{tag}] {safe_msg}")
        sys.stdout.flush()
    except Exception:
        pass

    try:
        os.makedirs(os.path.dirname(target_log), exist_ok=True)
        with open(target_log, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception:
        pass

def call_llm(provider: dict, system_prompt: str, user_prompt: str, timeout: int = 75) -> str:
    """Dispatches prompt to any supported LLM provider using pure Python standard library."""
    p_id = provider["id"]
    key = provider["key"]

    # 1. Google Gemini
    if "gemini" in p_id or "google" in p_id:
        models = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-pro", "gemini-1.5-flash"]
        if provider.get("model"):
            models = [provider.get("model")] + [m for m in models if m != provider.get("model")]
        headers = {
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA
        }
        payload = {
            "contents": [{
                "parts": [{"text": f"{system_prompt}\n\nTask:\n{user_prompt}"}]
            }],
            "generationConfig": {
                "maxOutputTokens": 600,
                "temperature": 0.7
            }
        }
        for m in models:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
                req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        res_text = "".join(part.get("text", "") for part in parts).strip()
                        if res_text:
                            return res_text
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                raise
        return ""

    # 2. Anthropic Claude
    elif "anthropic" in p_id or "claude" in p_id:
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
            "User-Agent": BROWSER_UA
        }
        chosen_claude_model = provider.get("model") or "claude-3-5-sonnet-20241022"
        payload = {
            "model": chosen_claude_model,
            "max_tokens": 600,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}]
        }
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            parts = data.get("content", [])
            return "".join(p.get("text", "") for p in parts if p.get("type") == "text").strip()

    # 3. OpenAI-Compatible Providers (Groq, DeepSeek, OpenAI, Ollama, OpenRouter)
    else:
        endpoint = "https://api.openai.com/v1/chat/completions"
        models = ["gpt-4o-mini"]

        if "groq" in p_id:
            endpoint = "https://api.groq.com/openai/v1/chat/completions"
            models = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", "llama-3.3-70b-versatile"]
        elif "9router" in p_id or provider.get("baseUrl"):
            target = provider.get("baseUrl") or "http://localhost:20128/v1"
            target = target.rstrip("/")
            if target.endswith("/v1"):
                endpoint = f"{target}/chat/completions"
            elif "/chat/completions" not in target:
                endpoint = f"{target}/v1/chat/completions"
            else:
                endpoint = target
            models = [provider.get("model") or "ag/gemini-3.8-flash", "ag/gemini-2.5-flash", "gpt-4o-mini"]
        elif "deepseek" in p_id:
            endpoint = "https://api.deepseek.com/v1/chat/completions"
            models = ["deepseek-chat"]
        elif "ollama" in p_id:
            endpoint = "http://localhost:11434/v1/chat/completions"
            models = ["llama3", "mistral"]
        elif "openrouter" in p_id:
            endpoint = "https://openrouter.ai/api/v1/chat/completions"
            models = ["meta-llama/llama-3.3-70b-instruct:free", "auto"]

        if provider.get("model"):
            models = [provider.get("model")] + [m for m in models if m != provider.get("model")]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "User-Agent": BROWSER_UA
        }

        for m in models:
            try:
                payload = {
                    "model": m,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    "max_tokens": 1200,
                    "temperature": 0.7,
                    "stream": False
                }
                req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw_resp = resp.read().decode("utf-8").strip()
                    if raw_resp.startswith("data:"):
                        text_chunks = []
                        for line in raw_resp.split("\n"):
                            line_s = line.strip()
                            if line_s.startswith("data:"):
                                line_json = line_s[5:].strip()
                                if line_json and line_json != "[DONE]":
                                    try:
                                        c_data = json.loads(line_json)
                                        delta = c_data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        if delta:
                                            text_chunks.append(delta)
                                    except Exception:
                                        pass
                        if text_chunks:
                            return "".join(text_chunks).strip()

                    try:
                        data = json.loads(raw_resp)
                        choices = data.get("choices", [])
                        if choices:
                            res_text = choices[0].get("message", {}).get("content", "").strip()
                            if res_text:
                                return res_text
                    except Exception:
                        pass
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    continue
                raise
        return ""

def run_council_debate(topic: str, root_dir: str = None) -> dict:
    """
    Executes an autonomous multi-model debate on any topic/feature.
    Streams back-and-forth arguments in real time to the Virtual Office.
    """
    providers = get_active_providers(root_dir)
    
    if not providers:
        log_council_message("council", "No external AI keys configured. Running under Native Antigravity Engine.", root_dir)
        return {"status": "native_only", "consensus": None}

    log_council_message("council", f"=== Multi-AI Council Convened for: '{topic[:60]}...' ===", root_dir)
    log_council_message("council", f"Participating AI models: {', '.join(p['name'] for p in providers)}", root_dir)

    # CASE A: Only 1 connected AI provider -> Senior Peer Reviewer
    if len(providers) == 1:
        p = providers[0]
        prof = p["profile"]
        log_council_message(prof["tag"], f"Consulting {p['name']} ({prof['role']})...", root_dir)

        sys_prompt = (
            f"You are {prof['name']}, acting as {prof['role']} in an autonomous software engineering team. "
            f"Personality: {prof['style']}. "
            "Analyze the proposal concisely. Give 2-3 specific insights, potential traps, or optimization recommendations in concise bullet points. No generic filler."
        )
        try:
            review = call_llm(p, sys_prompt, f"Review and critique this task/architecture:\n{topic}")
            for line in review.split("\n"):
                if line.strip():
                    log_council_message(prof["tag"], line.strip(), root_dir)
            return {"status": "consulted", "single_review": review, "participants": [p["name"]]}
        except Exception as e:
            log_council_message(prof["tag"], f"Error querying {p['name']}: {str(e)}", root_dir)
            return {"status": "error", "error": str(e)}

    # CASE B: 2 or more connected AI providers -> Multi-Model Debate & Defense
    challenger = providers[0]
    defender = providers[1]

    # If Groq is among them, always prefer Groq as challenger because of its 500 tps speed
    for i, p in enumerate(providers):
        if "groq" in p["id"]:
            challenger = providers.pop(i)
            defender = providers[0]
            providers.insert(0, challenger)
            break

    c_prof = challenger["profile"]
    d_prof = defender["profile"]

    # --- ROUND 1: Adversarial Challenge ---
    log_council_message(c_prof["tag"], f"Round 1 [Challenger]: {challenger['name']} is stress-testing the proposal...", root_dir)
    c_sys = (
        f"You are {challenger['name']}, acting as the {c_prof['role']} in an elite engineering swarm. "
        "Your duty is to be ruthlessly critical. Analyze the founder's prompt/plan and identify 2-3 critical edge cases, "
        "race conditions, security gaps, or architectural flaws. Be direct, concise, and technical. Max 3 bullet points."
    )
    
    critique = ""
    c_ok = False
    try:
        critique = call_llm(challenger, c_sys, f"Stress test this topic:\n{topic}")
        if critique and critique.strip():
            c_ok = True
            for line in critique.split("\n"):
                if line.strip():
                    log_council_message(c_prof["tag"], line.strip(), root_dir)
    except Exception as e:
        log_council_message(c_prof["tag"], f"[FAILED] Challenger {challenger['name']} error: {str(e)}", root_dir)

    time.sleep(0.5)

    # --- ROUND 2: Architectural Defense & Counter-Proposal ---
    log_council_message(d_prof["tag"], f"Round 2 [Defender]: {defender['name']} is evaluating critique and designing solutions...", root_dir)
    d_sys = (
        f"You are {defender['name']}, acting as {d_prof['role']} in the engineering council. "
        f"The challenger ({challenger['name']}) raised these concerns:\n{critique}\n\n"
        "Evaluate which points are valid, propose concrete architectural mitigations or counter-arguments, and recommend the definitive action plan. Be concise and actionable."
    )

    defense = ""
    d_ok = False
    try:
        defense = call_llm(defender, d_sys, f"Original Goal:\n{topic}\n\nChallenger Critique:\n{critique}")
        if defense and defense.strip():
            d_ok = True
            for line in defense.split("\n"):
                if line.strip():
                    log_council_message(d_prof["tag"], line.strip(), root_dir)
    except Exception as e:
        log_council_message(d_prof["tag"], f"[FAILED] Defender {defender['name']} error: {str(e)}", root_dir)

    # --- SYNTHESIS / VERDICT (No Fake Consensus) ---
    if not c_ok and not d_ok:
        err_msg = f"Council Debate FAILED: Both {challenger['name']} and {defender['name']} failed to respond."
        log_council_message("council_verdict", f"[FATAL ERROR] {err_msg}", root_dir)
        log_council_message("council", "=== Council Session Aborted due to provider errors. ===", root_dir)
        return {
            "status": "failed",
            "error": err_msg,
            "consensus": None
        }

    if c_ok and d_ok:
        verdict = (
            f"Council Consensus reached between {challenger['name']} and {defender['name']}. "
            "Key edge cases mitigated. Proceeding to execution."
        )
    elif d_ok:
        verdict = f"Council partial consensus: {defender['name']} formulated architectural mitigations (Challenger was offline)."
    else:
        verdict = f"Council partial consensus: {challenger['name']} identified key risk factors (Defender was offline)."

    log_council_message("council_verdict", verdict, root_dir)
    log_council_message("council", "=== Council Session Concluded. Swarm executing consensus. ===", root_dir)

    return {
        "status": "debated",
        "challenger": challenger["name"],
        "critique": critique,
        "defender": defender["name"],
        "defense": defense,
        "consensus": verdict
    }

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="TenAgent Dynamic Multi-AI Council")
    parser.add_argument("command", choices=["debate", "check", "list"], help="Council action to perform")
    parser.add_argument("topic", nargs="?", default="System Architecture Review", help="Topic to debate")
    args = parser.parse_args()

    if args.command == "list" or args.command == "check":
        active = get_active_providers()
        print(f"Found {len(active)} active AI provider(s):")
        for p in active:
            print(f" - [{p['id']}] {p['name']} -> Role: {p['profile']['role']}")
    elif args.command == "debate":
        run_council_debate(args.topic)
