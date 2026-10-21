#!/usr/bin/env python3
"""
10-Agent Swarm Project Initializer
Installs and bootstraps the 10-Agent Swarm framework into any new project folder.

Usage:
    python setup_project.py "C:\\path\\to\\new-project"
"""

import os
import sys
import shutil
import json

SOURCE_ROOT = os.path.abspath(os.path.dirname(__file__))

def bootstrap_new_project(target_dir):
    target_dir = os.path.abspath(target_dir)
    print(f"\n=======================================================")
    print(f"10-Agent Swarm Framework Initializer")
    print(f"Target Directory: {target_dir}")
    print(f"=======================================================\n")

    os.makedirs(target_dir, exist_ok=True)

    # 1. Copy Core Manifestos & Playbooks
    items_to_copy = [
        "AGENTS.md",
        ".agents",
        "dashboard",
        "assets",
        "office.bat",
        "council.py",
        "stream.py",
        "stream.bat",
        "swarm_pipeline.py",
        "favicon.ico",
        "LICENSE",
        ".gitignore"
    ]

    for item in items_to_copy:
        src = os.path.join(SOURCE_ROOT, item)
        dst = os.path.join(target_dir, item)
        if os.path.exists(src):
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                print(f"[OK] Copied directory: {item}/")
            else:
                shutil.copy2(src, dst)
                print(f"[OK] Copied file: {item}")

    # 2. Setup Clean specs/ Directory
    specs_target = os.path.join(target_dir, "specs")
    os.makedirs(os.path.join(specs_target, "prd"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "architecture"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "design"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "database"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "api"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "qa"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "security"), exist_ok=True)
    os.makedirs(os.path.join(specs_target, "reviews"), exist_ok=True)

    # Copy data dictionary template and openapi template if available
    src_specs = os.path.join(SOURCE_ROOT, "specs")
    if os.path.exists(os.path.join(src_specs, "database", "data-dictionary.md")):
        shutil.copy2(
            os.path.join(src_specs, "database", "data-dictionary.md"),
            os.path.join(specs_target, "database", "data-dictionary.md")
        )

    if os.path.exists(os.path.join(src_specs, "swarm-config.example.json")):
        shutil.copy2(
            os.path.join(src_specs, "swarm-config.example.json"),
            os.path.join(specs_target, "swarm-config.example.json")
        )

    # 3. Initialize Fresh Phase 1 Swarm Status
    initial_status = {
        "project": {
            "name": os.path.basename(target_dir),
            "version": "0.1.0",
            "phase": "Phase 1: Discovery & Requirements",
            "overallProgress": 5,
            "lastUpdated": "2026-10-19T02:00:00Z"
        },
        "agents": [
            {
                "id": "01_pm",
                "role": "Product Manager",
                "status": "WORKING",
                "currentTask": "Conducting Client Discovery interview to define MVP feature scope.",
                "processDetail": "Interviewing client: clarifying target users, core business problem, and MVP user stories.",
                "progress": 25,
                "deliverable": "specs/prd/FEATURE_NAME.md"
            },
            {
                "id": "02_arch",
                "role": "System Architect",
                "status": "WAITING",
                "currentTask": "Waiting for PRD feature list to consult tech stack & architecture layers.",
                "processDetail": "Standby to prepare ADR-001 (Clean Architecture layers & boundaries).",
                "progress": 0,
                "deliverable": "specs/architecture/layers.md"
            },
            {
                "id": "03_designer",
                "role": "UI/UX Designer",
                "status": "WAITING",
                "currentTask": "Waiting for PRD to design user flows and UI tokens.",
                "processDetail": "Standby to enforce anti-slop guidelines and design tokens.",
                "progress": 0,
                "deliverable": "specs/design/screen-flows.md"
            },
            {
                "id": "04_dba",
                "role": "Database Engineer",
                "status": "WAITING",
                "currentTask": "Waiting for architecture schema boundary definition.",
                "processDetail": "Standby to design 3NF relational schema and enforce zero duplicate tables.",
                "progress": 0,
                "deliverable": "specs/database/schema.sql"
            },
            {
                "id": "05_backend",
                "role": "Backend Engineer",
                "status": "WAITING",
                "currentTask": "Waiting for OpenAPI contract and database schema lock.",
                "processDetail": "Standby to build domain use cases strictly adhering to OpenAPI contract.",
                "progress": 0,
                "deliverable": "backend/src/"
            },
            {
                "id": "06_client",
                "role": "Client Engineer",
                "status": "WAITING",
                "currentTask": "Waiting for design specs and OpenAPI contract.",
                "processDetail": "Standby for concurrent mobile/web client development.",
                "progress": 0,
                "deliverable": "frontend/src/"
            },
            {
                "id": "07_qa",
                "role": "QA Engineer",
                "status": "IDLE",
                "currentTask": "Standby: Will write test matrix from acceptance criteria.",
                "processDetail": "Waiting for backend/client code implementations.",
                "progress": 0,
                "deliverable": "specs/qa/test-matrix.md"
            },
            {
                "id": "08_security",
                "role": "Security Engineer",
                "status": "IDLE",
                "currentTask": "Standby: Will audit OWASP Top 10 & auth authorization barriers.",
                "processDetail": "Waiting for endpoint routes to run security scanners.",
                "progress": 0,
                "deliverable": "specs/security/audit-report.md"
            },
            {
                "id": "09_devops",
                "role": "DevOps Engineer",
                "status": "IDLE",
                "currentTask": "Standby: Will prepare Docker containerization and CI/CD pipelines.",
                "processDetail": "Waiting for dependency tree finalization.",
                "progress": 0,
                "deliverable": "Dockerfile"
            },
            {
                "id": "10_tech_lead",
                "role": "Technical Lead",
                "status": "WAITING",
                "currentTask": "Gatekeeper standing by to audit diffs and enforce 6 Quality Gates.",
                "processDetail": "Will reject substandard code and approve production merges.",
                "progress": 0,
                "deliverable": "specs/reviews/signoff.md"
            }
        ],
        "logs": [
            {
                "timestamp": "00:00:01",
                "message": "Swarm initialized for new project. Phase 1 Discovery activated."
            }
        ]
    }

    with open(os.path.join(specs_target, "swarm-status.json"), "w", encoding="utf-8") as f:
        json.dump(initial_status, f, indent=2)
    print(f"[OK] Initialized fresh Phase 1 status in: specs/swarm-status.json")

    print("\n-------------------------------------------------------")
    print(f"SUCCESS! Project '{os.path.basename(target_dir)}' is ready.")
    print("-------------------------------------------------------")
    print("\nNext Steps:")
    print(f"1. Open new workspace in Antigravity:")
    print(f"   cd \"{target_dir}\"")
    print(f"2. Launch the 2D Virtual Office Monitor:")
    print(f"   Double-click 'office.bat' or run: python dashboard/serve.py")
    print(f"3. Start Phase 1 Discovery with Agent 01 (Product Manager):")
    print(f"   Prompt: 'Halo, kita mulai project baru ini. Apa yang perlu kita siapkan?'\n")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python setup_project.py <target_directory>")
        print("Example: python setup_project.py C:\\Users\\LENOVO\\Downloads\\projek-baru")
        sys.exit(1)
    bootstrap_new_project(sys.argv[1])
