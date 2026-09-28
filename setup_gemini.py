"""
One-time setup of the Gemini side of the autonomous engineering & remediation system.

  python setup_gemini.py presets                 # list built-in open-source repo presets
  python setup_gemini.py credentials             # validate GH_TOKEN and refresh agent network proxy rules
  python setup_gemini.py agent [--preset NAME]   # create (or replace) the managed agent
  python setup_gemini.py webhook --url URL       # register the static webhook -> orchestrator
  python setup_gemini.py trigger                 # weekly triage trigger (Mon 08:00 IST)
  python setup_gemini.py triage-now              # fire the triage trigger once, now
  python setup_gemini.py status                  # list agent, network proxy rules, webhooks, triggers

Env: GEMINI_API_KEY, GH_TOKEN (fine-grained PAT scoped to your fork), REPO (optional), PRESET (optional).
"""
import argparse
import base64
import os
import pathlib
import sys

GITHUB_OWNER = os.environ.get("GITHUB_OWNER", "cmanikandan")

PRESETS = {
    "flask-appbuilder": {
        "upstream": "dpgaspar/Flask-AppBuilder",
        "repo": f"{GITHUB_OWNER}/Flask-AppBuilder",
        "default_branch": "master",
        "description": "Flask-AppBuilder (Python Flask/SQLAlchemy auth & CRUD framework, ~20s sandbox tests)",
    },
    "redash": {
        "upstream": "getredash/redash",
        "repo": f"{GITHUB_OWNER}/redash",
        "default_branch": "master",
        "description": "Redash (Python Flask + React/TS query & dashboard tool, ~45s sandbox tests)",
    },
    "sqlglot": {
        "upstream": "tobymao/sqlglot",
        "repo": f"{GITHUB_OWNER}/sqlglot",
        "default_branch": "main",
        "description": "SQLGlot (Zero-dependency Python SQL parser & transpiler, <5s sandbox tests)",
    },
    "fastapi": {
        "upstream": "tiangolo/fastapi",
        "repo": f"{GITHUB_OWNER}/fastapi",
        "default_branch": "master",
        "description": "FastAPI (Modern async Python web framework & OpenAPI toolkit, ~15s unit tests)",
    },
}

PRESET = os.environ.get("PRESET", "flask-appbuilder")
if PRESET not in PRESETS:
    raise SystemExit(f"Unknown PRESET={PRESET!r}. Choose from: {', '.join(PRESETS)}")

REPO = os.environ.get("REPO", PRESETS[PRESET]["repo"])
AGENT_ID = os.environ.get("AGENT_ID", "gemini-oss-steward")
BASE_AGENT = os.environ.get("BASE_AGENT", "antigravity-preview-05-2026")
MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")
MAX_TOTAL_TOKENS = int(os.environ.get("MAX_TOTAL_TOKENS", "3000000"))  # per-run budget
TRIGGER_NAME = os.environ.get("TRIGGER_NAME", "oss-steward-weekly-triage")
WEBHOOK_NAME = os.environ.get("WEBHOOK_NAME", "gemini-oss-steward")

HERE = pathlib.Path(__file__).parent / "agent"


def get_client():
    from google import genai
    return genai.Client()


def network(gh_token: str | None = None) -> dict:
    """Egress allowlist: GitHub (with egress-proxy header transform) and package registries only."""
    token = gh_token or os.environ.get("GH_TOKEN", "")
    if not token:
        raise RuntimeError("GH_TOKEN environment variable is required to configure egress proxy transform headers.")
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return {
        "allowlist": [
            {
                "domain": "api.github.com",
                "transform": {"Authorization": f"Bearer {token}"},
            },
            {
                "domain": "github.com",
                "transform": {"Authorization": f"Basic {basic}"},
            },
            {"domain": "codeload.github.com"},
            {"domain": "objects.githubusercontent.com"},
            {"domain": "pypi.org"},
            {"domain": "files.pythonhosted.org"},
            {"domain": "registry.npmjs.org"},
            {"domain": "api.osv.dev"},
        ]
    }


def sources(repo: str = REPO) -> list:
    """Mount the fork plus AGENTS.md, all skills, and hooks into every sandbox."""
    inline = {
        ".agents/AGENTS.md": HERE / "AGENTS.md",
        ".agents/skills/vuln-triage/SKILL.md": HERE / "skills/vuln-triage/SKILL.md",
        ".agents/skills/vuln-fix/SKILL.md": HERE / "skills/vuln-fix/SKILL.md",
        ".agents/skills/feature-build/SKILL.md": HERE / "skills/feature-build/SKILL.md",
        ".agents/skills/code-modernize/SKILL.md": HERE / "skills/code-modernize/SKILL.md",
        ".agents/hooks.json": HERE / "hooks.json",
        ".agents/hooks-scripts/gate.py": HERE / "hooks-scripts/gate.py",
        ".agents/hooks-scripts/paths.py": HERE / "hooks-scripts/paths.py",
    }
    out = [{"type": "repository", "source": f"https://github.com/{repo}", "target": "/workspace/repo"}]
    out += [{"type": "inline", "target": t, "content": p.read_text()} for t, p in inline.items()]
    return out


def _resolve_repo(args) -> str:
    preset = getattr(args, "preset", None)
    if preset:
        return PRESETS[preset]["repo"]
    return REPO


def cmd_presets(_):
    for name, info in PRESETS.items():
        marker = "*" if name == PRESET else " "
        print(f"{marker} {name:18s} fork={info['repo']:30s} upstream={info['upstream']} ({info['description']})")


def cmd_credentials(args):
    """Validate GH_TOKEN and configure egress-proxy header transforms (recreates agent if already present)."""
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        sys.exit("GH_TOKEN is not set. Export a fine-grained GitHub PAT scoped to your fork first.")
    net = network(token)
    domains = [entry["domain"] for entry in net["allowlist"] if "transform" in entry]
    print(f"validated GH_TOKEN for egress proxy header transform on: {', '.join(domains)}")
    client = get_client()
    try:
        client.agents.get(id=AGENT_ID)
        cmd_agent(args)
        print(f"rotated egress proxy credentials on agent {AGENT_ID}")
    except Exception:
        print(f"ready: run `python setup_gemini.py agent` next to create {AGENT_ID} with these proxy transforms")


def cmd_agent(args):
    repo = _resolve_repo(args)
    client = get_client()
    try:
        client.agents.delete(id=AGENT_ID)  # preview has no versioning: replace in place
        print(f"deleted old agent {AGENT_ID}")
    except Exception:
        pass
    agent = client.agents.create(
        id=AGENT_ID,
        description=f"Autonomous security remediation, feature development, and modernization for {repo}",
        base_agent=BASE_AGENT,
        agent_config={"type": "antigravity", "model": MODEL, "max_total_tokens": MAX_TOTAL_TOKENS},
        system_instruction=(
            f"You are a senior software and application-security engineer maintaining the fork {repo}. "
            "Follow /.agents/AGENTS.md strictly. Use vuln-triage for scans, vuln-fix for security remediation, "
            "feature-build for feature requests, and code-modernize for code modernization. "
            "End with the RESULT line defined in AGENTS.md."
        ),
        tools=[{"type": "code_execution"}, {"type": "url_context"}, {"type": "google_search"}],
        base_environment={"type": "remote", "sources": sources(repo), "network": network()},
    )
    print(f"created agent {agent.id} for {repo} on {BASE_AGENT} / {MODEL}")


def cmd_webhook(args):
    client = get_client()
    target_uri = args.url.rstrip("/") + "/gemini-webhook"
    for existing in client.webhooks.list() or []:
        if getattr(existing, "name", None) == WEBHOOK_NAME or getattr(existing, "uri", None) == target_uri:
            client.webhooks.delete(id=existing.id)
            print(f"replaced existing webhook {existing.id}")
    wh = client.webhooks.create(
        name=WEBHOOK_NAME,
        subscribed_events=["interaction.completed", "interaction.failed",
                           "interaction.cancelled", "interaction.requires_action"],
        uri=target_uri,
    )
    print(f"webhook {wh.id} -> {wh.uri}")
    print("SIGNING SECRET (shown once, store it in Secret Manager as gemini-webhook-secret):")
    print(wh.new_signing_secret)


def _triage_prompt(repo: str) -> str:
    return (
        f"Use the vuln-triage skill on {repo}. File issues for new findings only. "
        "Label critical and high findings that have a fixed version with agent:remediate."
    )


def _find_trigger(client):
    for t in client.triggers.list().triggers or []:
        if t.display_name == TRIGGER_NAME:
            return t
    return None


def cmd_trigger(args):
    repo = _resolve_repo(args)
    client = get_client()
    old = _find_trigger(client)
    if old:
        client.triggers.delete(id=old.id)
    t = client.triggers.create(
        schedule="0 8 * * 1",
        time_zone="Asia/Kolkata",
        display_name=TRIGGER_NAME,
        max_consecutive_failures=3,
        execution_timeout_seconds=3600,
        interaction={"agent": AGENT_ID, "input": _triage_prompt(repo), "environment": "remote"},
    )
    print(f"trigger {t.id} next run {t.next_run_time}")


def cmd_triage_now(_):
    client = get_client()
    t = _find_trigger(client)
    if not t:
        sys.exit("no trigger yet: run `python setup_gemini.py trigger` first")
    client.triggers.run(trigger_id=t.id)
    print(f"fired {t.id}; watch the dashboard or: gh issue list -R {REPO} -l security-remediation")


def cmd_status(_):
    client = get_client()
    a = client.agents.get(id=AGENT_ID)
    print("agent:", a.id, "repo:", REPO, "base_agent:", BASE_AGENT, "model:", MODEL)
    for w in client.webhooks.list() or []:
        print("webhook:", w.id, w.uri, w.subscribed_events)
    t = _find_trigger(client)
    if t:
        print("trigger:", t.id, t.status, "next", t.next_run_time, "failures", t.consecutive_failure_count)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    c_p = sub.add_parser("credentials")
    c_p.add_argument("--preset", choices=list(PRESETS), help="open-source repository preset")
    c_p.set_defaults(fn=cmd_credentials)
    a_p = sub.add_parser("agent")
    a_p.add_argument("--preset", choices=list(PRESETS), help="open-source repository preset")
    a_p.set_defaults(fn=cmd_agent)
    w = sub.add_parser("webhook")
    w.add_argument("--url", required=True, help="orchestrator base URL, e.g. https://gemini-oss-steward-xyz.a.run.app")
    w.set_defaults(fn=cmd_webhook)
    t_p = sub.add_parser("trigger")
    t_p.add_argument("--preset", choices=list(PRESETS), help="open-source repository preset")
    t_p.set_defaults(fn=cmd_trigger)
    sub.add_parser("triage-now").set_defaults(fn=cmd_triage_now)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)
