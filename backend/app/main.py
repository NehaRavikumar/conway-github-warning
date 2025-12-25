import json
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Query
from .config import settings
from .db import init_db, connect
from fastapi.responses import StreamingResponse
from .sse import IncidentBroadcaster


app = FastAPI(title="Conway GitHub Warning System (v1)")
broadcaster = IncidentBroadcaster()

@app.get("/stream")
async def stream():
    async def gen():
        # initial comment so client knows it's connected
        yield ": connected\n\n"
        async for card in broadcaster.subscribe():
            yield "event: incident\n"
            yield f"data: {json.dumps(card)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.on_event("startup")
async def on_startup():
    await init_db(settings.DB_PATH)

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
              tags_json, evidence_json, inserted_at
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
            tags_json, evidence_json, inserted_at
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
                incident_id, kind, run_id, repo_full_name, workflow_name, run_number,
                status, conclusion, html_url,
                created_at, updated_at,
                title, tags_json, evidence_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                incident_id,
                "workflow_failure",
                run_id,
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
            ),
        )
        await db.commit()

    # 2) Build SSE card
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

    # 3) Publish to SSE
    await broadcaster.publish(card)

    return {
        "ok": True,
        "incident_id": incident_id,
        "run_id": run_id,
    }


