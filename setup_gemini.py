"""
One-time setup & pre-flight compatibility CLI for gemini-code-guru: the autonomous
software engineering & security platform powered by Gemini Managed Agents (Public Preview).

Works with ANY GitHub repository (private enterprise, commercial, internal service, or open-source fork):
  python setup_gemini.py presets                                   # list built-in reference presets
  python setup_gemini.py check [--repo OWNER/REPO] [--local-path .]# run pre-flight compatibility checks
  python setup_gemini.py credentials [--repo OWNER/REPO]           # validate GH_TOKEN & egress proxy rules
  python setup_gemini.py agent [--repo OWNER/REPO | --preset NAME] # create (or replace) the managed agent
  python setup_gemini.py webhook --url URL                         # register the static webhook -> orchestrator
  python setup_gemini.py trigger [--repo OWNER/REPO]               # weekly triage trigger (Mon 08:00 IST)
  python setup_gemini.py triage-now                                # fire the triage trigger once, now
  python setup_gemini.py status                                    # list agent, network proxy rules, webhooks, triggers

Env: GEMINI_API_KEY, GH_TOKEN (fine-grained PAT scoped to target repo), REPO (optional), PRESET (optional).
"""
import argparse
import base64
import json
import os
import pathlib
import sys
import urllib.request

ROOT = pathlib.Path(__file__).parent
HERE = ROOT / "agent"
sys.path.insert(0, str(ROOT / "orchestrator"))

from compatibility import (  # noqa: E402
    PLATFORM_LIMITS,
    check_issue_compatibility,
    check_repo_compatibility,
)

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
AGENT_ID = os.environ.get("AGENT_ID", "code-guru")
BASE_AGENT = os.environ.get("BASE_AGENT", "antigravity-preview-05-2026")
MODEL = os.environ.get("AGENT_MODEL", "gemini-3.8-flash")
MAX_TOTAL_TOKENS = int(os.environ.get("MAX_TOTAL_TOKENS", "3000000"))  # per-run budget
TRIGGER_NAME = os.environ.get("TRIGGER_NAME", "code-guru-weekly-triage")
WEBHOOK_NAME = os.environ.get("WEBHOOK_NAME", "code-guru")


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
    """Mount the target repository plus AGENTS.md, all skills, and hooks into every sandbox."""
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
    explicit = getattr(args, "repo", None)
    if explicit:
        return explicit
    preset = getattr(args, "preset", None)
    if preset:
        return PRESETS[preset]["repo"]
    return REPO


def _fetch_github_repo_meta(repo: str) -> tuple[int | None, list[str]]:
    """Best-effort fetch of GitHub repo size (KB) and root file paths when GH_TOKEN is set."""
    token = os.environ.get("GH_TOKEN", "")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "gemini-code-guru"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    size_kb = None
    paths: list[str] = []
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{repo}", headers=headers)
        with urllib.request.urlopen(req, timeout=8) as resp:
            meta = json.loads(resp.read().decode())
            size_kb = meta.get("size")
        req_tree = urllib.request.Request(f"https://api.github.com/repos/{repo}/contents", headers=headers)
        with urllib.request.urlopen(req_tree, timeout=8) as resp:
            items = json.loads(resp.read().decode())
            if isinstance(items, list):
                paths = [item.get("path", "") for item in items if isinstance(item, dict)]
    except Exception:
        pass
    return size_kb, paths


def cmd_presets(_):
    print("Built-in reference presets (any custom repo can also be used via --repo OWNER/REPO or REPO=OWNER/REPO):")
    for name, info in PRESETS.items():
        marker = "*" if name == PRESET else " "
        print(f"{marker} {name:18s} target={info['repo']:30s} upstream={info['upstream']} ({info['description']})")


def cmd_check(args):
    """Run pre-flight Gemini Managed Agents compatibility checks on the target repository & issue."""
    repo = _resolve_repo(args)
    srcs = sources(repo)
    repo_url = srcs[0]["source"]
    allowlist = network("placeholder-token")["allowlist"]
    size_kb, remote_paths = (None, [])
    if not getattr(args, "offline", False):
        size_kb, remote_paths = _fetch_github_repo_meta(repo)

    report = check_repo_compatibility(
        repo_url=repo_url,
        repo_size_kb=size_kb,
        file_paths=remote_paths,
        local_dir=getattr(args, "local_path", None),
        inline_sources=srcs[1:],
        allowlist=allowlist,
    )

    print(f"=== Gemini Managed Agents (Preview) Pre-Flight Compatibility Check: {repo} ===")
    print(f"Release Stage : {PLATFORM_LIMITS['release_stage']}")
    print(f"Sandbox Spec  : {PLATFORM_LIMITS['sandbox_os']} · {PLATFORM_LIMITS['cpu_cores']} vCPU · "
          f"{PLATFORM_LIMITS['memory_gb']} GB RAM · GPU/TPU={PLATFORM_LIMITS['gpu_or_tpu']}")
    print(f"Source Caps   : Git <= {PLATFORM_LIMITS['max_git_repo_mb']} MB · "
          f"GCS <= {PLATFORM_LIMITS['max_gcs_source_mb']} MB · "
          f"Inline <= {PLATFORM_LIMITS['max_inline_total_bytes'] // 1_000_000} MB total")
    if size_kb is not None:
        print(f"Detected Size : {round(size_kb / 1024, 1)} MB on GitHub")

    issue_title = getattr(args, "issue_title", None)
    issue_body = getattr(args, "issue_body", "") or ""
    issue_ok = True
    if issue_title:
        ic = check_issue_compatibility(issue_title, issue_body)
        issue_ok = ic["compatible"]
        if not ic["compatible"]:
            report["blockers"].append(f"Issue pre-flight blocked ({ic['category']}): {ic['reason']}")

    for w in report["warnings"]:
        print(f"  [WARN]    {w}")
    for b in report["blockers"]:
        print(f"  [BLOCKER] {b}")

    if report["compatible"] and issue_ok:
        print("Result: COMPATIBLE — ready for Gemini Managed Agent execution.")
    else:
        sys.exit("Result: INCOMPATIBLE — resolve blockers above or route workload to a custom runner.")


def cmd_credentials(args):
    """Validate GH_TOKEN and configure egress-proxy header transforms (recreates agent if already present)."""
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        sys.exit("GH_TOKEN is not set. Export a fine-grained GitHub PAT scoped to your target repository first.")
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
    srcs = sources(repo)
    net = network()
    size_kb, remote_paths = _fetch_github_repo_meta(repo)
    preflight = check_repo_compatibility(
        repo_url=srcs[0]["source"],
        repo_size_kb=size_kb,
        file_paths=remote_paths,
        inline_sources=srcs[1:],
        allowlist=net["allowlist"],
    )
    for w in preflight["warnings"]:
        print(f"[pre-flight warning] {w}")
    if not preflight["compatible"]:
        for b in preflight["blockers"]:
            print(f"[pre-flight blocker] {b}", file=sys.stderr)
        sys.exit("Aborted agent creation due to Gemini Managed Agents platform compatibility blockers.")

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
            f"You are a senior software and application-security engineer maintaining the repository {repo}. "
            "Follow /.agents/AGENTS.md strictly. Use vuln-triage for scans, vuln-fix for security remediation, "
            "feature-build for feature requests, and code-modernize for code modernization. "
            "If a task requires an unsupported OS/runtime (native Windows, macOS/Xcode, GPU, kernel modules), "
            "stop immediately and emit RESULT: NEEDS_HUMAN. End with the RESULT line defined in AGENTS.md."
        ),
        tools=[{"type": "code_execution"}, {"type": "url_context"}, {"type": "google_search"}],
        base_environment={"type": "remote", "sources": srcs, "network": net},
    )
    print(f"created agent {agent.id} for {repo} on {BASE_AGENT} / {MODEL}")


def cmd_webhook(args):
    client = get_client()
    target_uri = args.url.rstrip("/") + "/gemini-webhook"
    for existing in client.webhooks.list().webhooks or []:
        if getattr(existing, "name", None) == WEBHOOK_NAME or getattr(existing, "uri", None) == target_uri:
            client.webhooks.delete(id=existing.id)
            print(f"replaced existing webhook {existing.id}")
    wh = client.webhooks.create(
        name=WEBHOOK_NAME,
        subscribed_events=["interaction.completed", "interaction.failed", "interaction.requires_action"],
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
        execution_timeout_seconds=600,
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
    for w in client.webhooks.list().webhooks or []:
        print("webhook:", w.id, w.uri, w.subscribed_events)
    t = _find_trigger(client)
    if t:
        print("trigger:", t.id, t.status, "next", t.next_run_time, "failures", t.consecutive_failure_count)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("presets").set_defaults(fn=cmd_presets)
    chk = sub.add_parser("check", help="run pre-flight Gemini Managed Agents compatibility checks")
    chk.add_argument("--preset", choices=list(PRESETS), help="built-in repository preset")
    chk.add_argument("--repo", help="target GitHub repository (owner/repo) — enterprise, private, or OSS")
    chk.add_argument("--local-path", help="optional local checkout directory to scan for incompatible project files")
    chk.add_argument("--issue-title", help="optional issue title to test against the issue pre-flight gate")
    chk.add_argument("--issue-body", default="", help="optional issue body to test against the issue pre-flight gate")
    chk.add_argument("--offline", action="store_true", help="skip live GitHub API metadata lookup")
    chk.set_defaults(fn=cmd_check)
    c_p = sub.add_parser("credentials")
    c_p.add_argument("--preset", choices=list(PRESETS), help="built-in repository preset")
    c_p.add_argument("--repo", help="target GitHub repository (owner/repo)")
    c_p.set_defaults(fn=cmd_credentials)
    a_p = sub.add_parser("agent")
    a_p.add_argument("--preset", choices=list(PRESETS), help="built-in repository preset")
    a_p.add_argument("--repo", help="target GitHub repository (owner/repo)")
    a_p.set_defaults(fn=cmd_agent)
    w = sub.add_parser("webhook")
    w.add_argument("--url", required=True, help="orchestrator base URL, e.g. https://gemini-code-guru-xyz.a.run.app")
    w.set_defaults(fn=cmd_webhook)
    t_p = sub.add_parser("trigger")
    t_p.add_argument("--preset", choices=list(PRESETS), help="built-in repository preset")
    t_p.add_argument("--repo", help="target GitHub repository (owner/repo)")
    t_p.set_defaults(fn=cmd_trigger)
    sub.add_parser("triage-now").set_defaults(fn=cmd_triage_now)
    sub.add_parser("status").set_defaults(fn=cmd_status)
    a = p.parse_args()
    a.fn(a)
