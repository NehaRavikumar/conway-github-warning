from datetime import datetime, timezone, timedelta

from app.services.correlator import EcosystemCorrelator
from app.types.signal import SignalMatch

def _match():
    return SignalMatch(
        signature="npm_auth_token_expired",
        evidence={"matched_line": "npm ERR! code E401", "run_id": 1},
        confidence=0.9,
    )

def test_correlator_threshold_triggers_once():
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    def now_fn():
        return now

    correlator = EcosystemCorrelator(
        window_minutes=60,
        min_repos=5,
        min_owners=3,
        cooldown_minutes=30,
        now_fn=now_fn,
    )

    repos = [
        ("org-a/repo1", "org-a"),
        ("org-b/repo2", "org-b"),
        ("org-c/repo3", "org-c"),
        ("org-a/repo4", "org-a"),
        ("org-b/repo5", "org-b"),
    ]
    incident = None
    for repo, owner in repos:
        incident = correlator.ingest(_match(), repo, owner, now.isoformat(), {"run_id": 1}, "live")

    assert incident is not None
    payload = incident["incident"]["_evidence"]
    assert payload["affected_repos_count"] >= 5
    assert payload["unique_owners_count"] >= 3

def test_correlator_cooldown_blocks_repeat():
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    def now_fn():
        return now

    correlator = EcosystemCorrelator(
        window_minutes=60,
        min_repos=2,
        min_owners=2,
        cooldown_minutes=30,
        now_fn=now_fn,
    )

    first = correlator.ingest(_match(), "org-a/repo1", "org-a", now.isoformat(), {"run_id": 1}, "live")
    assert first is None
    second = correlator.ingest(_match(), "org-b/repo2", "org-b", now.isoformat(), {"run_id": 2}, "live")
    assert second is not None

    now = now + timedelta(minutes=10)
    third = correlator.ingest(_match(), "org-c/repo3", "org-c", now.isoformat(), {"run_id": 3}, "live")
    assert third is None

    now = now + timedelta(minutes=31)
    fourth = correlator.ingest(_match(), "org-d/repo4", "org-d", now.isoformat(), {"run_id": 4}, "live")
    assert fourth is not None
