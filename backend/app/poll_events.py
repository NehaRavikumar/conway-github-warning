import json
import asyncio
from typing import Any, Dict, Optional
from datetime import datetime, timezone

from .config import settings
from .db import connect
from .github import GitHubClient
from .incidents import insert_incident
from .signals.workflow_exfiltration import detect_ghostaction_risk, detect_personalized_exfiltration, FetchBudget
from .services.osv_enrichment import maybe_enqueue_enrichment

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def normalize_event(ev: Dict[str, Any]) -> Dict[str, Any]:
    repo = ev.get("repo") or {}
    actor = ev.get("actor") or {}
    return {
        "event_id": str(ev.get("id")),
        "event_type": ev.get("type") or "",
        "repo_full_name": repo.get("name"),
        "actor_login": actor.get("login"),
        "created_at": ev.get("created_at") or now_iso(),
        "raw_json": json.dumps(ev, separators=(",", ":")),
    }

async def insert_event(row: Dict[str, Any]) -> bool:
    # True if inserted (i.e., new), False if duplicate
    async with connect(settings.DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO events(event_id,event_type,repo_full_name,actor_login,created_at,raw_json) VALUES (?,?,?,?,?,?)",
                (
                    row["event_id"],
                    row["event_type"],
                    row["repo_full_name"],
                    row["actor_login"],
                    row["created_at"],
                    row["raw_json"],
                ),
            )
            await db.commit()
            return True
        except Exception:
            return False

# simple in-memory “recent repos” buffer for next step
RECENT_REPOS: list[str] = []

def add_recent_repo(repo_full_name: Optional[str]) -> None:
    if not repo_full_name or "/" not in repo_full_name:
        return
    RECENT_REPOS.append(repo_full_name)
    # cap size
    if len(RECENT_REPOS) > 500:
        del RECENT_REPOS[:250]

async def poll_events_loop(broadcaster, summary_queue, enrichment_queue):
    gh = GitHubClient(settings.GITHUB_TOKEN)

    while True:
        try:
            budget = FetchBudget(settings.MAX_WORKFLOW_FETCHES_PER_CYCLE)
            events = await gh.list_global_events()
            new_count = 0
            for ev in events:
                row = normalize_event(ev)
                if not row["event_id"]:
                    continue
                inserted = await insert_event(row)
                if inserted:
                    new_count += 1
                    add_recent_repo(row.get("repo_full_name"))

                    incidents = []
                    incidents.extend(await detect_ghostaction_risk(ev, gh, budget))
                    incidents.extend(await detect_personalized_exfiltration(ev, gh, budget))
                    for inc in incidents:
                        ok = await insert_incident(settings.DB_PATH, inc)
                        if ok:
                            card = {
                                "incident_id": inc["incident_id"],
                                "kind": inc["kind"],
                                "repo_full_name": inc["repo_full_name"],
                                "title": inc["title"],
                                "workflow_name": inc["workflow_name"],
                                "run_id": inc["run_id"],
                                "run_number": inc["run_number"],
                                "conclusion": inc["conclusion"],
                                "status": inc["status"],
                                "html_url": inc["html_url"],
                                "created_at": inc["created_at"],
                                "tags": inc["_tags"],
                                "evidence": inc["_evidence"],
                            }
                            await broadcaster.publish(card)
                            await summary_queue.enqueue(inc["incident_id"])
                            await maybe_enqueue_enrichment(inc, enrichment_queue, settings.DB_PATH)
            # small visible signal in logs
            if new_count:
                print(f"[poll] inserted {new_count} new events; recent_repos={len(RECENT_REPOS)}")
        except Exception as e:
            # keep logs light; no secrets
            print(f"[poll] error: {type(e).__name__}")

        await asyncio.sleep(settings.POLL_EVENTS_SECONDS)
