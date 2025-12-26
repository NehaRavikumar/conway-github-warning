from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Callable

from ..types.signal import SignalMatch

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _parse_time(value: Optional[str]) -> datetime:
    if not value:
        return _now_utc()
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except Exception:
        return _now_utc()

def _stable_run_id(key: str) -> int:
    digest = hashlib.sha1(key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big", signed=False)
    return -int(value % (2**63))

@dataclass
class CorrelatorEntry:
    repo_full_name: str
    owner: str
    occurred_at: datetime
    match: SignalMatch
    source_ids: Dict[str, Any]

class EcosystemCorrelator:
    def __init__(
        self,
        window_minutes: int,
        min_repos: int,
        min_owners: int,
        cooldown_minutes: int,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.window = timedelta(minutes=window_minutes)
        self.min_repos = min_repos
        self.min_owners = min_owners
        self.cooldown = timedelta(minutes=cooldown_minutes)
        self._entries: Dict[str, List[CorrelatorEntry]] = defaultdict(list)
        self._last_emit: Dict[str, datetime] = {}
        self._now = now_fn or _now_utc

    def ingest(
        self,
        match: SignalMatch,
        repo_full_name: str,
        owner: str,
        occurred_at: Optional[str],
        source_ids: Dict[str, Any],
        source: str,
    ) -> Optional[Dict[str, Any]]:
        ts = _parse_time(occurred_at)
        signature = match.signature

        entries = self._entries[signature]
        cutoff = self._now() - self.window
        entries[:] = [e for e in entries if e.occurred_at >= cutoff]

        entries.append(
            CorrelatorEntry(
                repo_full_name=repo_full_name,
                owner=owner,
                occurred_at=ts,
                match=match,
                source_ids=source_ids,
            )
        )

        unique_repos = {e.repo_full_name for e in entries}
        unique_owners = {e.owner for e in entries}

        if len(unique_repos) < self.min_repos or len(unique_owners) < self.min_owners:
            return None

        last_emit = self._last_emit.get(signature)
        now = self._now()
        if last_emit and (now - last_emit) < self.cooldown:
            return None

        self._last_emit[signature] = now
        return self._build_incident(signature, entries, source, now)

    def _build_incident(
        self,
        signature: str,
        entries: List[CorrelatorEntry],
        source: str,
        now: datetime,
    ) -> Dict[str, Any]:
        unique_repos = sorted({e.repo_full_name for e in entries})
        unique_owners = sorted({e.owner for e in entries})
        sample_repos = unique_repos[:10]

        evidence_samples = []
        for e in entries[:5]:
            sample = {
                "repo": e.repo_full_name,
                "matched_line": e.match.evidence.get("matched_line"),
                "run_id": e.match.evidence.get("run_id"),
                "job_name": e.match.evidence.get("job_name"),
            }
            evidence_samples.append(sample)

        confidence = max((e.match.confidence for e in entries), default=0.0)

        root_cause_hypothesis = (
            "Widespread npm authentication failures consistent with token expiration/revocation "
            "(often from tokens stored in .npmrc or short-lived tokens in CI)."
        )
        impact = "CI fails during npm install / npm ci across multiple repositories in a short window."
        next_steps = [
            "Rotate/regenerate npm token used in CI secrets.",
            "Avoid committing tokens to .npmrc; use CI secrets or automation tokens.",
            "Re-run failed workflows after updating credentials.",
        ]

        payload = {
            "type": "ECOSYSTEM_INCIDENT",
            "signature": signature,
            "plugin": signature,
            "confidence": confidence,
            "window_minutes": int(self.window.total_seconds() / 60),
            "affected_repos_count": len(unique_repos),
            "unique_owners_count": len(unique_owners),
            "sample_repos": sample_repos,
            "evidence_samples": evidence_samples,
            "root_cause_hypothesis": root_cause_hypothesis,
            "impact": impact,
            "next_steps": next_steps,
            "source": source,
        }

        summary = {
            "root_cause": [root_cause_hypothesis],
            "impact": [impact],
            "next_steps": next_steps,
        }

        dedupe_key = f"ecosystem:{signature}:{int(now.timestamp() // self.cooldown.total_seconds())}"
        run_id = _stable_run_id(dedupe_key)
        tags = [
            "ecosystem",
            "incident",
            f"signature:{signature}",
            f"repos:{len(unique_repos)}",
            f"owners:{len(unique_owners)}",
            f"source:{source}",
        ]

        incident = {
            "incident_id": hashlib.sha1(dedupe_key.encode("utf-8")).hexdigest(),
            "kind": "ecosystem_incident",
            "run_id": run_id,
            "dedupe_key": dedupe_key,
            "repo_full_name": "ecosystem",
            "workflow_name": signature,
            "run_number": None,
            "status": "detected",
            "conclusion": "high",
            "html_url": "https://www.npmjs.com/",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "title": f"Ecosystem incident: {signature}",
            "tags_json": json.dumps(tags),
            "evidence_json": json.dumps(payload),
            "_tags": tags,
            "_evidence": payload,
        }

        return {"incident": incident, "summary": summary}
