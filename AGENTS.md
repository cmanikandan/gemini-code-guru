# AGENTS.md — Developer & AI Agent Guide for `gemini-code-guru`

This file provides context, architectural invariants, and verification commands for AI coding agents (Antigravity, Gemini CLI, etc.) working on the **`gemini-code-guru`** repository.

> [!IMPORTANT]
> **Two `AGENTS.md` Files Exist in This Repository:**
> 1. **`/AGENTS.md` (this file)**: Instructions for developing, testing, and maintaining the `gemini-code-guru` orchestrator, compatibility guardrails, and setup scripts.
> 2. **`/agent/AGENTS.md`**: The runtime instruction file uploaded via `InlineSource` into `/.agents/AGENTS.md` inside every remote **Gemini Managed Agent** Linux sandbox to govern how the autonomous agent modifies the target repository (enterprise private repo, commercial project, or open-source fork) at `/workspace/repo`.

---

## 1. System Overview

`gemini-code-guru` is an event-driven autonomous software engineering and security remediation system for **any Linux-compatible GitHub repository** (private enterprise, commercial, or open-source), built on **Gemini Managed Agents** (`google-genai >= 2.3.0`, Interactions API `/v1beta/`, **Public Preview**):

- **`setup_gemini.py`**: CLI that runs pre-flight compatibility checks (`check`), creates/replaces the saved Gemini Managed Agent (`id="code-guru"`, `base_agent="antigravity-preview-05-2026"`, `model="gemini-3.8-flash"`) for any `--repo <owner>/<repo>` or `--preset <name>`, configures egress-proxy header transforms for GitHub authentication, registers the Gemini static webhook (`interaction.completed`, `interaction.failed`, `interaction.requires_action`), and creates the weekly scheduled trigger (`0 8 * * 1` `Asia/Kolkata`, `execution_timeout_seconds=600`).
- **`agent/`**: Declarative sandbox configuration mounted into `/.agents/` on every agent run:
  - `agent/AGENTS.md`: Hard security & platform compatibility rules, project test profiles (built-in presets + auto-detected polyglot stacks), PR template, and the final `RESULT:` line contract.
  - `agent/skills/vuln-triage/SKILL.md`: Weekly scheduled scanner (`pip-audit`, `bandit`, `npm audit`) that deduplicates and files up to 10 GitHub issues.
  - `agent/skills/vuln-fix/SKILL.md`: Single-issue vulnerability remediation (`agent:remediate`).
  - `agent/skills/feature-build/SKILL.md`: Test-driven feature implementation (`agent:feature`).
  - `agent/skills/code-modernize/SKILL.md`: Behavior-preserving code modernization (`agent:modernize`).
  - `agent/hooks.json`, `agent/hooks-scripts/gate.py`, `agent/hooks-scripts/paths.py`: Deterministic `pre_tool_execution` security and platform compatibility gates.
- **`orchestrator/`**: FastAPI service deployed on Cloud Run:
  - `orchestrator/main.py`: Handles `POST /github-webhook`, `POST /gemini-webhook`, `POST /reconcile`, `POST /preflight`, `GET /`, `GET /metrics`, `GET /runs`, `GET /compatibility`, `GET /login`, `POST /login`, and `GET /logout`. Enforces dashboard/API authentication (`DASHBOARD_USER` / `DASHBOARD_PASSWORD` via session cookie, HTTP Basic Auth, or Bearer token), routes labels via `SKILL_BY_LABEL`, enforces `MAX_CONCURRENT=3`, short-circuits incompatible OS/hardware workloads via `compatibility.py`, tracks sandbox execution time (`sandbox_s`, `provision_s`) and granular Gemini 3.8 Flash token cost (`cost_usd`, `cache_hit_rate`), and retries transient failures once (`MAX_ATTEMPTS=2`).
  - `orchestrator/compatibility.py`: Codifies Gemini Managed Agents (Public Preview) platform limits (Ubuntu Linux, 4 vCPU, 16 GB RAM, no GPU/TPU, 500 MB Git cap, 2 MB inline cap, reserved agent ID prefixes) and provides `check_issue_compatibility()` and `check_repo_compatibility()`.
  - `orchestrator/store.py`: Firestore state store (`STORE=firestore`) and in-memory test store (`STORE=memory`).
  - `orchestrator/github.py`: Minimal GitHub REST API wrapper and `X-Hub-Signature-256` HMAC verifier.
  - `orchestrator/dashboard.py`: Server-rendered HTML/SVG live observability dashboard and login screen with sandbox runtime and per-run cost breakdown.
  - `orchestrator/test_flow.py`: Offline end-to-end test suite (12 tests) using fake Gemini and GitHub backends plus tests for `compatibility.py`, `gate.py`, `paths.py`, dashboard authentication, and sandbox runtime/cost telemetry.
- **`assets/`**: High-resolution Nano Banana architecture, sequence flow (`end_to_end_sequence_flow.jpg`), lifecycle, and security diagrams embedded in `README.md`.
- **`deploy.sh`**: Deploys `orchestrator/` to Cloud Run (`gemini-code-guru`) with `--no-invoker-iam-check` and `--no-cpu-throttling`, binds Secret Manager secrets (including `dashboard-password`), and configures the 10-minute Cloud Scheduler reconciler (`code-guru-reconcile`).

---

## 2. Critical Gemini Managed Agents SDK Invariants (Do Not Regress)

When modifying `setup_gemini.py`, `agent/`, or `orchestrator/`, preserve these verified Gemini API specifications:

1. **Egress Proxy Credential Injection (`setup_gemini.py:network()`)**:
   - The `google-genai` SDK does **not** have a `client.credentials` resource.
   - Outbound credentials must be injected on the wire using the `"transform"` dictionary inside `base_environment.network.allowlist`:
     ```python
     {"domain": "api.github.com", "transform": {"Authorization": f"Bearer {token}"}}
     {"domain": "github.com", "transform": {"Authorization": f"Basic {basic}"}}
     ```
2. **Base Agent & Reserved Agent ID Prefixes (`setup_gemini.py:BASE_AGENT`, `AGENT_ID`)**:
   - Default `BASE_AGENT` must remain `"antigravity-preview-05-2026"` (unless overridden via `BASE_AGENT` env var when a newer harness is released).
   - Default `AGENT_ID` must remain `"code-guru"`. Do **not** prefix custom agent IDs with reserved Google prefixes (`gemini-`, `antigravity-`, `google-`, `gemma-`, `veo-`, `imagen-`, `omni-`, `lyria-`, etc.), which are rejected by `POST /v1beta/agents` with `400 invalid_request`.
3. **Webhooks & Scheduled Triggers (`setup_gemini.py:cmd_webhook`, `cmd_trigger`)**:
   - `client.webhooks.list()` returns a `WebhookListResponse` whose items are on `.webhooks`.
   - Supported interaction webhook event types are `["interaction.completed", "interaction.failed", "interaction.requires_action"]`.
   - `client.triggers.create()` enforces `execution_timeout_seconds <= 600`.
4. **Hook Tool Matchers (`agent/hooks.json`)**:
   - Inside the remote Linux sandbox, the filesystem write tool is named `write_file` (and `delete_file`). Keep the `protected-paths` matcher in `agent/hooks.json` set to `"write_file|delete_file|write_to_file|replace_file_content"`.
5. **Target Repository Checkout Path (`/workspace/repo`)**:
   - `setup_gemini.py:sources()` mounts the target repository at `/workspace/repo`. Keep all skills (`agent/skills/*/SKILL.md`) and `agent/AGENTS.md` aligned with `/workspace/repo`.
6. **Final Line Contract (`RESULT: ...`)**:
   - `orchestrator/main.py:RESULT_RE` parses the final line of `interaction.output_text` (`RESULT: PR_OPENED <url>`, `RESULT: NEEDS_HUMAN <reason>`, `RESULT: FAILED <reason>`, or `RESULT: TRIAGE_DONE <count>`). Any new skill added under `agent/skills/` must emit one of these exact lines as its final output line.

---

## 3. Verification & Test Commands

Always run these checks after editing code or hooks:

```bash
# 1. Verify Python syntax across all modules and hook scripts
python3 -m py_compile setup_gemini.py orchestrator/*.py agent/hooks-scripts/*.py

# 2. Verify presets and pre-flight check CLI output
python3 setup_gemini.py presets
python3 setup_gemini.py check --offline --local-path .

# 3. Run the offline orchestrator, pre-flight compatibility, auth, cost & hook test suite (no GCP or API keys required)
python3 -m venv .venv && .venv/bin/pip install -q -r orchestrator/requirements.txt pytest
STORE=memory .venv/bin/pytest -q orchestrator/test_flow.py
```

If you modify any file inside `agent/`, remember that saved Gemini Managed Agents inline their sources at creation time—re-run `python3 setup_gemini.py agent` to push updated skills or hooks to the remote agent definition.
