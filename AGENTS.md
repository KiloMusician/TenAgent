# 10-Agent Engineering Swarm Workspace

This repository operates as an autonomous, contract-first engineering workspace governed by **10 Specialized Engineer Agents**. It is designed to take any software project from concept to production with zero architectural drift, minimal context pollution, and clean, crafted code.

---

## 1. Core Operating Philosophy

1. **Context Window Isolation**: Each agent operates in its own narrow domain of responsibility. Inter-agent communication occurs strictly through version-controlled specification files located in the `specs/` directory.
2. **Contract-First Development**: No client or backend code may be implemented until the **API Contract (`specs/api/openapi.yaml`)** and **Database Schema (`specs/database/schema.sql`)** are reviewed and approved.
3. **Zero Duplication in Data**: The Database Engineer maintains a centralized Data Dictionary. Redundant tables, overlapping columns, and unindexed foreign keys are strictly prohibited.
4. **Minimalist Code Comments**: 
   - Never write self-evident comments (e.g., `// fetch user`, `// render screen`, `// handle error`).
   - Write comments sparingly, concisely, and **only** for non-obvious business logic, mathematical formulas, or critical edge cases.
5. **Concise Git Commits**:
   - Commit messages must follow the single-line Conventional Commits standard: `<type>(<scope>): <short description>`.
   - Examples: `feat(auth): add google oauth provider`, `fix(db): add unique constraint on users.email`.
   - Never generate verbose multi-paragraph commit descriptions.
6. **Live State Synchronization (Micro-Step Status Lock)**:
   - **Immediate Pre-Execution Lock**: The very FIRST tool call any agent makes upon receiving an instruction MUST be updating its record in `specs/swarm-status.json` (`status: "WORKING"`, specific `currentTask`, granular `processDetail` explaining what sub-step is actively being computed, and initial `progress`). Never wait until task completion to update state.
   - **Mid-Flight & Completion Updates**: Update `progress` and `processDetail` as sub-milestones finish. When complete, set `progress: 100`, status `IDLE` (or `REVIEWING`), and append a concise entry to `logs` in `specs/swarm-status.json`.
   - **Strict Role Boundary Lock**: Agents must strictly focus on their assigned role and division. Never perform work belonging to another role (e.g. Backend must never invent database schema changes or alter design tokens; PM must never write code). Cross-cutting needs must be delegated through specification files.
7. **Strict Port Isolation (Zero Collision Rule)**:
   - Port `7777` (and range `7777-7827`) is strictly reserved for the TenAgent Virtual Office Dashboard (`office.bat`).
   - Project applications created by agents must NEVER bind to port `7777`.
   - Standard project ports: Client web applications use port `3000` (or `5173`); backend services use port `4000` (or `8000`). This ensures Virtual Office and the user's project run simultaneously without collision.

---

## 2. The 10 Engineering Roles

The roles and their operating playbooks are defined in `.agents/roles/`:

| Role | Playbook Path | Mandate |
| :--- | :--- | :--- |
| **01. Product Manager** | `.agents/roles/01_product_manager.md` | Conducts client discovery, defines user stories & acceptance criteria |
| **02. System Architect** | `.agents/roles/02_software_architect.md` | Recommends tech stack, enforces Clean Architecture layers |
| **03. UI/UX Designer** | `.agents/roles/03_ui_ux_designer.md` | Designs user flows, wireframes, and tokens with anti-slop guidelines |
| **04. Database Engineer** | `.agents/roles/04_database_engineer.md` | Normalizes schema, prevents duplicate tables, maintains Data Dictionary |
| **05. Backend Engineer** | `.agents/roles/05_backend_engineer.md` | Builds domain use cases and APIs matching OpenAPI contract |
| **06. Client Engineer** | `.agents/roles/06_client_engineer.md` | Implements Web/Mobile UI in parallel adhering to contract & design specs |
| **07. QA Engineer** | `.agents/roles/07_qa_engineer.md` | Edge-case bug hunter; writes unit, integration, and regression tests |
| **08. Security Engineer** | `.agents/roles/08_security_engineer.md` | OWASP Top 10 auditing, auth/authz reviews, secret leak prevention |
| **09. DevOps Engineer** | `.agents/roles/09_devops_engineer.md` | Docker containerization, CI/CD pipelines, reproducible builds |
| **10. Technical Lead** | `.agents/roles/10_tech_lead.md` | Gatekeeper: reviews diffs, checks anti-slop, rejects substandard code |

---

## 3. Workflow Execution Lifecycle

```
[User Idea] 
     │
     ▼
[01. PM Discovery Interview] ──► specs/prd/
     │
     ▼
[02. Architect Consultation] ──► specs/architecture/
     │
     ├──► [03. Designer]     ──► specs/design/  & DESIGN.md
     └──► [04. Database Eng] ──► specs/database/ & specs/api/openapi.yaml
                                       │
     ┌─────────────────────────────────┴─────────────────────────────────┐
     ▼                                                                   ▼
[05. Backend Engineer]                                          [06. Client Engineer]
  └─► backend/                                                    └─► frontend/ or mobile/
     │                                                                   │
     └─────────────────────────────────┬─────────────────────────────────┘
                                       ▼
                             [07. QA Engineer]        ──► specs/qa/ & tests/
                                       │
                                       ▼
                             [08. Security Engineer]  ──► specs/security/
                                       │
                             [09. DevOps Engineer]    ──► Dockerfile & .github/
                                       │
                                       ▼
                             [10. Technical Lead]     ──► Review & Gatekeeper
                                       │
                       ┌───────────────┴───────────────┐
                       ▼                               ▼
                 [APPROVED]                       [REJECTED]
             Ready for merge               Kicked back to agent with diff notes
```

---

## 4. Client Discovery & Interaction Protocol

When interacting with the user/founder:
1. **Mandatory Kickoff Discovery Interview (Phase 0)**:
   Whenever a new project or major module is initiated, the AI **MUST NOT** immediately dump code or scaffold directories. The **Product Manager (Role 01)** and **System Architect (Role 02)** must first conduct an interactive discovery interview:
   - **Target Persona & Core Problem**: Who are the primary end-users and what single critical problem must be solved?
   - **MVP Scope Boundaries**: What are the non-negotiable core features versus deferred/phase 2 features?
   - **Technical & Hardware Constraints**: Hardware peripherals (printers, barcode scanners), offline-first caching, real-time sync, target OS/devices.
   - **UI Tone & Visual Guidelines**: Theme preference (dark/light, minimalist, industrial), typography, and adherence to anti-slop guidelines (`DESIGN.md`).
   - **Tech Stack & Deployment**: Stack recommendations (e.g. Flutter vs React Native; Go/Node.js/Python; PostgreSQL/SQLite) with clear pros and cons.
2. **Honest State Machine (No Fake Work)**:
   - Agents ONLY enter `WORKING` status when actively computing real logic, modifying workspace files, or executing real CLI processes via `stream.py`.
   - Agents without active domain tasks remain gracefully in `IDLE` (e.g., DevOps stands by until containerization is requested).
   - Agents blocked by dependencies enter `WAITING` with explicit blockers stated in `processDetail` (e.g., Backend waits for OpenAPI lock).
   - Downstream quality gates (QA, Security, Tech Lead) only run when real test suites, security scans, or release audits are executed.
3. **Language Protocol**: The user can communicate in either **English** or **Bahasa Indonesia**. The agent matches the user's conversational language, but technical specifications, contracts, and code files are kept in English.

---

## 5. Master-Prompt Auto-Execution Protocol (Multi-Brain Swarm Pipeline)

Whenever the user prompts the AI CLI (`agy`) to create, scaffold, or develop a project, feature, or major module:

1. **MANDATORY AUTOMATIC SWARM INVOCATION**:
   The AI CLI (`agy`) operates as the **Swarm Conductor**. The AI CLI **MUST NOT** attempt to generate all layers or specifications alone in its single prompt context.
   Instead, the AI CLI **MUST IMMEDIATELY** execute the multi-brain collaborative pipeline as its very first tool call:
   ```powershell
   python swarm_pipeline.py "<user_prompt>"
   ```
   *(or `python stream.py swarm "<user_prompt>"`)*

   **What this command automatically does**:
   - Reads `specs/swarm-config.json` and engages all active AI provider brains (9Router at `localhost:20128`, Groq, Gemini, DeepSeek, Claude, OpenAI, Ollama).
   - If multiple AI keys are connected: runs the **Pre-Flight Multi-AI Council Debate** where connected models dynamically split roles (e.g., Groq stress-tests edge cases and 9Router/Gemini solves them), streaming every argument live to `specs/terminal.log`.
   - Distributes the 10 engineering roles across the active AI models:
     * **01_pm**: Formulates PRD & User Stories (`specs/prd/user-stories.md`).
     * **02_arch**: Locks Clean Architecture boundaries (`specs/architecture/adr-001.md`).
     * **04_dba**: Generates 3NF Database Schema (`specs/database/schema.sql`).
     * **05_backend**: Generates OpenAPI 3.0 Contract (`specs/api/openapi.yaml`) and backend service stub.
     * **07_qa**: Establishes Test Matrix (`specs/qa/test-matrix.md`).
     * **08_security**: Produces OWASP Audit Report (`specs/security/audit-report.md`).
     * **10_tech_lead**: Evaluates Quality Gates & Final Signoff (`specs/signoff.md`).
   - Updates `specs/swarm-status.json` and streams live logs to the TenAgent Virtual Office Dashboard in real time.

2. **Post-Pipeline Code Implementation & Verification**:
   After `python swarm_pipeline.py` finishes:
   - The AI CLI reads the locked specifications from `specs/`.
   - The AI CLI assists the client engineer and backend engineer in completing application source code (`backend/`, `frontend/`, or `mobile/`) adhering 100% strictly to `specs/database/schema.sql` and `specs/api/openapi.yaml`.
   - The AI CLI executes real test suites using the stream runner:
     ```powershell
     python stream.py run 07_qa "npm test" # (or pytest / cargo test)
     ```
   - Terminal outputs and test results stream directly into the Virtual Office Monitor.

3. **Ad-Hoc Peer Debate & Consultation**:
   Whenever the user asks a design question or requests an architectural debate:
   ```powershell
   python stream.py council "<topic>"
   ```
   The active brains debate live, and the AI CLI reports the consensus back to the user.

---

## 6. Autonomous Multi-AI Council & Debate Protocol (Multi-Model Swarm)

Whenever external AI keys are connected in `specs/swarm-config.json` (Groq, Gemini, DeepSeek, Claude, OpenAI, etc.), the Swarm activates the **Autonomous Dynamic Multi-Model Council**:
1. **Zero-Setup Pre-Flight Debate**:
   - Before scaffolding a new module or making major architectural decisions (Step 1 / Step 2), the Swarm executes:
     `python stream.py council "<feature_topic>"`
   - The connected models dynamically split roles:
     - The fastest model (e.g. Groq GPT-OSS-120B / Llama) acts as the **Adversarial Red Team**, stress-testing the idea and identifying edge-case flaws.
     - The secondary model (e.g. Gemini 2.5 Flash / Claude / DeepSeek) acts as the **Architectural Solutionist**, addressing the critique and proposing solutions.
   - The debate is streamed in real time to `specs/terminal.log` and visible live on the Virtual Office Monitor.
2. **Consensus-Driven Implementation**:
   - The Technical Lead synthesizes the council consensus and incorporates edge-case mitigations directly into PRD specifications and code.
3. **Graceful Fallback**:
   - If no external API keys are configured, the swarm functions smoothly under the Native Antigravity engine without interruption.

---

<!-- antislop:start -->
## antislop
For UI, copy, people, mobile layout, or code comments work, read `.agents/skills/antislop/SKILL.md` (core) and then the skill for the task:
- UI / visual: `.agents/skills/antislop-ui/SKILL.md`
- Copy & text: `.agents/skills/antislop-copywriting/SKILL.md`
- People: `.agents/skills/antislop-human/SKILL.md`
- Mobile / responsive: `.agents/skills/antislop-layoutmobile/SKILL.md`
- Code comments: `.agents/skills/antislop-code/SKILL.md`
Before starting, ask the user when antislop applies: during the work, or after it is done.
<!-- antislop:end -->
