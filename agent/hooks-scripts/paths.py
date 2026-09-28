#!/usr/bin/env python3
"""pre_tool_execution gate for file writes: keep the agent out of protected paths."""
import json
import sys

import re

PROTECTED_RE = re.compile(
    r"(^|/)\.(github|agents)(/|$)|(^|/)(\.asf\.yaml|LICENSE|NOTICE)$|(^|/)RELEASING(/|$)"
)

data = json.load(sys.stdin)
args = data.get("tool_call", {}).get("args", {})
path = str(args.get("path") or args.get("file_path") or args.get("target_file") or "")
norm = "/" + path.lstrip("/")
if PROTECTED_RE.search(norm):
    print(json.dumps({"decision": "deny",
                      "reason": f"{path} is protected; make the change elsewhere or report NEEDS_HUMAN."}))
else:
    print(json.dumps({"decision": "allow"}))
