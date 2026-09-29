#!/usr/bin/env python3
"""pre_tool_execution gate for code_execution: deny commands that break the agent's security or platform rules."""
import json
import re
import sys

DENY = [
    (r"git\s+push\b(?!.*\bagent/issue-\d+\b)", "Push only to branches named agent/issue-<n>."),
    (r"git\s+push\b.*(--force|-f\b|\+)", "Force-push is not allowed."),
    (r"\b(dpgaspar/Flask-AppBuilder|getredash/redash|tobymao/sqlglot|tiangolo/fastapi)\b.*\b(pulls|issues|comments)\b",
     "Never write to an upstream open-source repository."),
    (r"\bgh\s+(pr|issue)\s+\w+.*-R\s+(apache|dpgaspar|getredash|tobymao|tiangolo)/",
     "Never write to an upstream open-source repository."),
    (r"rm\s+-rf\s+(/|~|\.\s*$)", "Destructive delete blocked."),
    (r"\bprintenv\b|(^|[;&|]\s*)env\s*($|[;&|])", "Do not dump the environment."),
    (r"curl[^|]*\|\s*(ba)?sh", "Piping remote scripts to a shell is blocked."),
    (r"(^|/)\.(github|agents)/|(^|/)\.asf\.yaml\b|(^|/)(LICENSE|NOTICE)\b|(^|/)RELEASING/",
     "Changes to protected paths (.github/, .agents/, .asf.yaml, LICENSE, NOTICE, RELEASING/) are not allowed."),
    (r"(^|[;&|\s])(msbuild(\.exe)?|devenv(\.exe)?|powershell\.exe|wscript(\.exe)?|reg\.exe)\b",
     "Unsupported native Windows build/runtime tool in Ubuntu Linux sandbox: stop and report RESULT: NEEDS_HUMAN."),
    (r"(^|[;&|\s])(xcodebuild|xcrun|osascript)\b",
     "Unsupported macOS/iOS Xcode tool in Ubuntu Linux sandbox: stop and report RESULT: NEEDS_HUMAN."),
    (r"(^|[;&|\s])(insmod|modprobe|rmmod)\b|docker\s+run\b[^\n]*--privileged",
     "Kernel modules and privileged containers are not supported in the OS-isolated sandbox: report RESULT: NEEDS_HUMAN."),
]

data = json.load(sys.stdin)
args = data.get("tool_call", {}).get("args", {})
cmd = args.get("code") if isinstance(args.get("code"), str) else json.dumps(args)
for pattern, reason in DENY:
    if re.search(pattern, cmd):
        print(json.dumps({"decision": "deny", "reason": reason}))
        sys.exit(0)
print(json.dumps({"decision": "allow"}))
