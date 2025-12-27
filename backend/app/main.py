import json
import uuid
import asyncio
from .check_runs import check_runs_loop
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from .config import settings
from .db import init_db, connect
from fastapi.responses import StreamingResponse
from .sse import IncidentBroadcaster
from .poll_events import poll_events_loop, RECENT_REPOS
from .github import GitHubClient
from .check_runs import run_to_incident, FAIL_CONCLUSIONS
from .incidents import insert_incident
from .summary_queue import SummaryQueue, RedisSummaryQueue, summary_worker_loop
from .services.osv_enrichment import EnrichmentQueue, osv_worker_loop, maybe_enqueue_enrichment
from .services.correlator import EcosystemCorrelator
from .plugins.npm_auth_token_expired import NpmAuthTokenExpiredPlugin
from .replay.fixtures import run_replay_fixtures





app = FastAPI(title="Conway GitHub Warning System (v1)")
broadcaster = IncidentBroadcaster()
summary_queue = (
    RedisSummaryQueue(settings.REDIS_URL)
    if settings.REDIS_URL
    else SummaryQueue()
)
enrichment_queue = EnrichmentQueue()
correlator = EcosystemCorrelator(
    settings.WINDOW_MINUTES,
    settings.MIN_REPOS,
    settings.MIN_OWNERS,
    settings.COOLDOWN_MINUTES,
)
signal_plugins = [NpmAuthTokenExpiredPlugin()]

@app.get("/stream")
async def stream():
    async def gen():
        # initial comment so client knows it's connected
        yield ": connected\n\n"
        async for card in broadcaster.subscribe():
            event_name = card.get("_event", "incident")
            yield f"event: {event_name}\n"
            yield f"data: {json.dumps(card)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )

@app.get("/debug/runs_sample")
async def debug_runs_sample(repo: str = "vercel/next.js", per_page: int = 5):
    owner, name = repo.split("/", 1)
    gh = GitHubClient(settings.GITHUB_TOKEN)
    data = await gh.list_workflow_runs(owner, name, per_page=per_page)
    runs = data.get("workflow_runs", []) or []
    return {
        "repo": repo,
        "count": len(runs),
        "runs": [
            {
                "id": r.get("id"),
                "name": r.get("name"),
                "status": r.get("status"),
                "conclusion": r.get("conclusion"),
                "created_at": r.get("created_at"),
                "html_url": r.get("html_url"),
            }
            for r in runs
        ],
    }

@app.post("/debug/check_repo_once")
async def debug_check_repo_once(repo: str = "vercel/next.js"):
    owner, name = repo.split("/", 1)
    gh = GitHubClient(settings.GITHUB_TOKEN)
    data = await gh.list_workflow_runs(owner, name, per_page=10)
    runs = data.get("workflow_runs", []) or []

    failures = []
    inserted = 0
    for run in runs:
        if run.get("conclusion") in FAIL_CONCLUSIONS:
            inc = run_to_incident(run, repo)
            ok = await insert_incident(settings.DB_PATH, inc)
            failures.append({"run_id": run.get("id"), "conclusion": run.get("conclusion"), "inserted": ok})
            if ok:
                inserted += 1

    return {"repo": repo, "runs_checked": len(runs), "failures": failures, "inserted": inserted}

@app.on_event("startup")
async def on_startup():
    await init_db(settings.DB_PATH)
    asyncio.create_task(poll_events_loop(broadcaster, summary_queue, enrichment_queue))
    asyncio.create_task(check_runs_loop(broadcaster, summary_queue, enrichment_queue, correlator, signal_plugins))
    asyncio.create_task(summary_worker_loop(settings.DB_PATH, summary_queue, broadcaster))
    asyncio.create_task(osv_worker_loop(settings.DB_PATH, enrichment_queue, broadcaster))
    if settings.REPLAY_FIXTURES:
        asyncio.create_task(run_replay_fixtures(signal_plugins, correlator, broadcaster, settings.DB_PATH, summary_queue, enrichment_queue))

@app.get("/debug/recent_repos")
async def debug_recent_repos(limit: int = 20):
    return {"recent_repos": list(reversed(RECENT_REPOS[-limit:]))}

@app.get("/health")
async def health():
    return {"ok": True}

@app.get("/summary")
async def summary(
    since: str = Query(..., description="SQLite datetime string OR ISO string; v1 uses inserted_at >= since"),
    limit: int = Query(100, ge=1, le=500),
):
    async with connect(settings.DB_PATH) as db:
        cur = await db.execute(
            """
            SELECT
              incident_id, kind, run_id, repo_full_name, workflow_name, run_number,
              status, conclusion, html_url, created_at, updated_at, title,
              tags_json, evidence_json, summary_json, enrichment_json, inserted_at
            FROM incidents
            WHERE inserted_at >= ?
            ORDER BY inserted_at DESC
            LIMIT ?
            """,
            (since, limit),
        )
        rows = await cur.fetchall()

    cards = []
    for r in rows:
        (
            incident_id, kind, run_id, repo_full_name, workflow_name, run_number,
            status, conclusion, html_url, created_at, updated_at, title,
            tags_json, evidence_json, summary_json, enrichment_json, inserted_at
        ) = r

        cards.append({
            "incident_id": incident_id,
            "kind": kind,
            "run_id": run_id,
            "repo_full_name": repo_full_name,
            "workflow_name": workflow_name,
            "run_number": run_number,
            "status": status,
            "conclusion": conclusion,
            "html_url": html_url,
            "created_at": created_at,
            "updated_at": updated_at,
            "title": title,
            "tags": json.loads(tags_json),
            "evidence": json.loads(evidence_json),
            "summary": json.loads(summary_json) if summary_json else None,
            "enrichment": json.loads(enrichment_json) if enrichment_json else None,
            "inserted_at": inserted_at,
        })

    return {"cards": cards}
@app.post("/dev/seed_failure")
async def seed_failure():
    if not settings.DEV_MODE:
        return {"error": "DEV_MODE is false"}

    incident_id = str(uuid.uuid4())
    run_id = int(datetime.now().timestamp())  # unique enough for dev

    repo_full_name = "vercel/next.js"
    workflow_name = "CI"
    conclusion = "failure"
    status = "completed"
    html_url = "https://github.com/vercel/next.js/actions"

    created_at = datetime.now(timezone.utc).isoformat()

    title = f"{workflow_name} failed in {repo_full_name}"
    tags = [
        "workflow",
        "failure",
        f"conclusion:{conclusion}",
        f"status:{status}",
    ]

    evidence = {
        "repo": repo_full_name,
        "run": {
            "id": run_id,
            "name": workflow_name,
            "status": status,
            "conclusion": conclusion,
            "html_url": html_url,
            "created_at": created_at,
        },
        "detected_at": created_at,
        "source": "dev_seed",
    }

    # 1) Insert into DB
    async with connect(settings.DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO incidents(
                incident_id, kind, run_id, dedupe_key, repo_full_name, workflow_name, run_number,
                status, conclusion, html_url,
                created_at, updated_at,
                title, tags_json, evidence_json, enrichment_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                incident_id,
                "workflow_failure",
                run_id,
                None,
                repo_full_name,
                workflow_name,
                1,
                status,
                conclusion,
                html_url,
                created_at,
                created_at,
                title,
                json.dumps(tags),
                json.dumps(evidence),
                None,
            ),
        )
        await db.commit()

    # 2) Queue summary generation
    await summary_queue.enqueue(incident_id)
    await maybe_enqueue_enrichment(
        {
            "incident_id": incident_id,
            "kind": "workflow_failure",
            "repo_full_name": repo_full_name,
            "tags": tags,
            "evidence": evidence,
        },
        enrichment_queue,
        settings.DB_PATH,
    )

    # 3) Build SSE card
    card = {
        "incident_id": incident_id,
        "kind": "workflow_failure",
        "run_id": run_id,
        "repo_full_name": repo_full_name,
        "workflow_name": workflow_name,
        "run_number": 1,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "created_at": created_at,
        "title": title,
        "tags": tags,
        "evidence": evidence,
    }

    # 4) Publish to SSE
    await broadcaster.publish(card)

    return {
        "ok": True,
        "incident_id": incident_id,
        "run_id": run_id,
    }

@app.post("/debug/replay_now")
async def replay_now():
    emitted = await run_replay_fixtures(signal_plugins, correlator, broadcaster, settings.DB_PATH, summary_queue, enrichment_queue)
    return {"ok": True, "emitted": emitted}
