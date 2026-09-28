"""Minimal GitHub REST client for labels, comments and issue listing."""
import hashlib
import hmac
import os

import httpx

API = "https://api.github.com"


def verify_signature(secret: str, body: bytes, header: str | None) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header)


class GitHub:
    def __init__(self, repo: str, token: str | None = None):
        self.repo = repo
        self.http = httpx.Client(
            base_url=f"{API}/repos/{repo}",
            headers={
                "Authorization": f"Bearer {token or os.environ['GH_TOKEN']}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20,
        )

    def comment(self, issue: int, body: str) -> None:
        self.http.post(f"/issues/{issue}/comments", json={"body": body}).raise_for_status()

    def add_labels(self, issue: int, *labels: str) -> None:
        self.http.post(f"/issues/{issue}/labels", json={"labels": list(labels)}).raise_for_status()

    def remove_label(self, issue: int, label: str) -> None:
        r = self.http.delete(f"/issues/{issue}/labels/{label}")
        if r.status_code not in (200, 404):
            r.raise_for_status()

    def issues_with_label(self, label: str) -> list[dict]:
        r = self.http.get("/issues", params={"labels": label, "state": "open", "per_page": 100})
        r.raise_for_status()
        return [i for i in r.json() if "pull_request" not in i]
