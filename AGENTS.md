# AGENTS.md — Developer & AI Agent Guide for `gemini-oss-steward`

This file provides context, architectural invariants, and verification commands for AI coding agents (Antigravity, Gemini CLI, etc.) working on the **`gemini-oss-steward`** repository.

> [!IMPORTANT]
> **Two `AGENTS.md` Files Exist in This Repository:**
> 1. **`/AGENTS.md` (this file)**: Instructions for developing, testing, and maintaining the `gemini-oss-steward` orchestrator and setup scripts.
> 2. **`/agent/AGENTS.md`**: The runtime instruction file uploaded via `InlineSource` into `/.agents/AGENTS.md` inside every remote **Gemini Managed Agent** Linux sandbox to govern how the autonomous agent modifies the target open-source fork at `/workspace/repo`.

---

## 1. System Overview

`gemini-oss-steward` is an event-driven open-source engineering and security remediation system built on **Gemini Managed Agents** (`google-genai >= 2.3.0`, Interactions API `/v1beta/`):

- **`setup_gemini.py`**: CLI that creates/replaces the saved Gemini Managed Agent (`id="gemini-oss-steward"`, `base_agent="antigravity-preview-05-2026"`, `model="gemini-3.8-flash"`), configures egress-proxy header transforms for GitHub authentication, registers the Gemini static webhook, and creates the weekly scheduled trigger (`0 8 * * 1` `Asia/Kolkata`).
- **`agent/`**: Declarative sandbox configuration mounted into `/.agents/` on every agent run:
  - `agent/AGENTS.md`: Hard rules, project test profiles (`flask-appbuilder`, `redash`, `sqlglot`, `fastapi`), PR template, and the final `RESULT:` line contract.
  - `agent/skills/vuln-triage/SKILL.md`: Weekly scheduled scanner (`pip-audit`, `bandit`, `npm audit`) that deduplicates and files up to 10 GitHub issues.
  - `agent/skills/vuln-fix/SKILL.md`: Single-issue vulnerability remediation (`agent:remediate`).
  - `agent/skills/feature-build/SKILL.md`: Test-driven feature implementation (`agent:feature`).
  - `agent/skills/code-modernize/SKILL.md`: Behavior-preserving code modernization (`agent:modernize`).
  - `agent/hooks.json`, `agent/hooks-scripts/gate.py`, `agent/hooks-scripts/paths.py`: Deterministic `pre_tool_execution` security gates.
- **`orchestrator/`**: FastAPI service deployed on Cloud Run:
  - `orchestrator/main.py`: Handles `POST /github-webhook`, `POST /gemini-webhook`, `POST /reconcile`, `GET /`, `GET /metrics`, and `GET /runs`. Routes labels via `SKILL_BY_LABEL`, enforces `MAX_CONCURRENT=3`, and retries transient failures once (`MAX_ATTEMPTS=2`).
  - `orchestrator/store.py`: Firestore state store (`STORE=firestore`) and in-memory test store (`STORE=memory`).
  - `orchestrator/github.py`: Minimal GitHub REST API wrapper and `X-Hub-Signature-256` HMAC verifier.
  - `orchestrator/dashboard.py`: Server-rendered HTML/SVG live observability dashboard.
  - `orchestrator/test_flow.py`: Offline end-to-end test suite using fake Gemini and GitHub backends plus subprocess tests for `gate.py` and `paths.py`.
- **`deploy.sh`**: Deploys `orchestrator/` to Cloud Run (`gemini-oss-steward`) and configures the 10-minute Cloud Scheduler reconciler (`oss-steward-reconcile`).

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
2. **Base Agent Identifier (`setup_gemini.py:BASE_AGENT`)**:
   - Default `BASE_AGENT` must remain `"antigravity-preview-05-2026"` (unless overridden via `BASE_AGENT` env var when a newer harness is released).
3. **Hook Tool Matchers (`agent/hooks.json`)**:
   - Inside the remote Linux sandbox, the filesystem write tool is named `write_file` (and `delete_file`). Keep the `protected-paths` matcher in `agent/hooks.json` set to `"write_file|delete_file|write_to_file|replace_file_content"`.
4. **Target Repository Checkout Path (`/workspace/repo`)**:
   - `setup_gemini.py:sources()` mounts the target fork at `/workspace/repo`. Keep all skills (`agent/skills/*/SKILL.md`) and `agent/AGENTS.md` aligned with `/workspace/repo`.
5. **Final Line Contract (`RESULT: ...`)**:
   - `orchestrator/main.py:RESULT_RE` parses the final line of `interaction.output_text` (`RESULT: PR_OPENED <url>`, `RESULT: NEEDS_HUMAN <reason>`, `RESULT: FAILED <reason>`, or `RESULT: TRIAGE_DONE <count>`). Any new skill added under `agent/skills/` must emit one of these exact lines as its final output line.

---

## 3. Verification & Test Commands

Always run these checks after editing code or hooks:

```bash
# 1. Verify Python syntax across all modules and hook scripts
python3 -m py_compile setup_gemini.py orchestrator/*.py agent/hooks-scripts/*.py

# 2. Verify presets CLI output
python3 setup_gemini.py presets

# 3. Run the offline orchestrator & hook test suite (no GCP or API keys required)
STORE=memory pytest -q orchestrator/test_flow.py
# Or with uv:
uv run --with-requirements orchestrator/requirements.txt --with pytest pytest -q orchestrator/test_flow.py
```

If you modify any file inside `agent/`, remember that saved Gemini Managed Agents inline their sources at creation time—re-run `python3 setup_gemini.py agent` to push updated skills or hooks to the remote agent definition.
