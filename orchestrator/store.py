"""Run store: Firestore in production, in-memory for local runs and tests."""
from __future__ import annotations

import os
import threading
from datetime import datetime, timezone

ACTIVE = ("queued", "running")
TERMINAL = ("pr_opened", "needs_human", "failed", "cancelled", "timeout")


def now() -> datetime:
    return datetime.now(timezone.utc)


class MemoryStore:
    def __init__(self):
        self._runs: dict[str, dict] = {}
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def put(self, run_id: str, data: dict) -> None:
        with self._lock:
            self._runs.setdefault(run_id, {}).update(data)

    def get(self, run_id: str) -> dict | None:
        r = self._runs.get(run_id)
        return dict(r, id=run_id) if r else None

    def all(self) -> list[dict]:
        return [dict(v, id=k) for k, v in self._runs.items()]

    def by_status(self, *statuses: str) -> list[dict]:
        return [r for r in self.all() if r.get("status") in statuses]

    def by_issue(self, issue: int) -> list[dict]:
        return sorted((r for r in self.all() if r.get("issue") == issue), key=lambda r: r.get("attempt", 0))

    def by_interaction(self, interaction_id: str) -> dict | None:
        return next((r for r in self.all() if r.get("interaction_id") == interaction_id), None)

    def first_delivery(self, delivery_id: str) -> bool:
        """At-least-once webhooks: True only the first time an id is seen."""
        with self._lock:
            if delivery_id in self._seen:
                return False
            self._seen.add(delivery_id)
            return True


class FirestoreStore(MemoryStore):
    def __init__(self, collection: str = "runs"):
        from google.cloud import firestore  # imported lazily so local runs need no GCP

        self.db = firestore.Client()
        self.col = self.db.collection(collection)
        self.deliveries = self.db.collection(collection + "_deliveries")

    def put(self, run_id, data):
        self.col.document(run_id).set(data, merge=True)

    def get(self, run_id):
        d = self.col.document(run_id).get()
        return dict(d.to_dict(), id=d.id) if d.exists else None

    def all(self):
        return [dict(d.to_dict(), id=d.id) for d in self.col.stream()]

    def by_status(self, *statuses):
        return [dict(d.to_dict(), id=d.id) for d in self.col.where("status", "in", list(statuses)).stream()]

    def by_issue(self, issue):
        docs = [dict(d.to_dict(), id=d.id) for d in self.col.where("issue", "==", issue).stream()]
        return sorted(docs, key=lambda r: r.get("attempt", 0))

    def by_interaction(self, interaction_id):
        for d in self.col.where("interaction_id", "==", interaction_id).limit(1).stream():
            return dict(d.to_dict(), id=d.id)
        return None

    def first_delivery(self, delivery_id):
        from google.api_core.exceptions import AlreadyExists

        try:
            self.deliveries.document(delivery_id).create({"at": now()})
            return True
        except AlreadyExists:
            return False


def make_store():
    return FirestoreStore() if os.environ.get("STORE", "firestore") == "firestore" else MemoryStore()
