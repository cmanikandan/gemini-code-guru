---
name: vuln-triage
description: Scan the target repository (enterprise, private, or open-source) for known vulnerabilities and file one GitHub issue per new finding.
---
# Vulnerability triage

1. `cd /workspace/repo && git pull --ff-only && mkdir -p /workspace/out`.
2. `pip install pip-audit bandit`, then:
   - `pip-audit -r requirements/base.txt -f json -o /workspace/out/pip-audit.json` (or `pip-audit -f json -o /workspace/out/pip-audit.json` if `requirements/base.txt` is not present)
   - `bandit -r . -lll -iii -f json -o /workspace/out/bandit.json` (high severity, high confidence only)
3. If `package.json` or `client/package.json` exists: run `npm audit --omit=dev --json > /workspace/out/npm-audit.json`.
4. Normalise findings to: id (CVE/GHSA/rule), package or file:line, current version, fixed version,
   severity. Deduplicate across scanners. Drop findings with no fixed version unless critical.
5. List open AND closed issues labeled `security-remediation` through the GitHub API
   (`GET /repos/<owner>/<repo>/issues?labels=security-remediation&state=all&per_page=100`).
   Skip any finding whose id already appears in an issue title.
6. Create at most 10 issues per run, highest severity first. For each:
   - title: `[vuln] <package or file>: <id>`
   - labels: `security-remediation`, `severity:<critical|high|medium>`
   - body: advisory link, component and current vs fixed version (or file:line), scanner name,
     suggested fix in one line, acceptance: "scanner no longer reports it; unit tests pass".
7. For severity critical or high with a fixed version available, ALSO add the label
   `agent:remediate` (this starts remediation automatically).
8. Write `/workspace/out/triage-summary.md` with a table of created and skipped findings.
9. Last line: `RESULT: TRIAGE_DONE <count created>`.
