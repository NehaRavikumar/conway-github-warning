import asyncio
import json
from typing import Any, Dict, Optional, List

import redis.asyncio as redis
import httpx

from .db import connect
from .config import settings

class SummaryQueue:
    def __init__(self, maxsize: int = 1000):
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=maxsize)

    async def enqueue(self, incident_id: str) -> None:
        try:
            self._queue.put_nowait(incident_id)
        except asyncio.QueueFull:
            # Drop if overloaded; queueing is best-effort in v1.
            pass

    async def dequeue(self) -> str:
        return await self._queue.get()

class RedisSummaryQueue:
    def __init__(self, redis_url: str, queue_name: str = "summary_jobs"):
        self._redis = redis.Redis.from_url(redis_url, decode_responses=True)
        self._queue_name = queue_name

    async def enqueue(self, incident_id: str) -> None:
        await self._redis.lpush(self._queue_name, incident_id)

    async def dequeue(self) -> Optional[str]:
        item = await self._redis.brpop(self._queue_name, timeout=30)
        if not item:
            return None
        _queue, value = item
        return value

def get_summary_queue() -> "SummaryQueue | RedisSummaryQueue":
    redis_url = (settings.REDIS_URL or "").strip()
    if redis_url.startswith("redis://") or redis_url.startswith("rediss://"):
        print("[startup] Using RedisSummaryQueue")
        return RedisSummaryQueue(redis_url)
    print("[startup] REDIS_URL missing/invalid; using in-memory SummaryQueue")
    return SummaryQueue()

async def _fetch_incident(db_path: str, incident_id: str) -> Optional[Dict[str, Any]]:
    async with connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT
              incident_id, kind, run_id, repo_full_name, workflow_name, run_number,
              status, conclusion, html_url, created_at, updated_at, title,
              tags_json, evidence_json, summary_json,
              why_this_fired, risk_trajectory, risk_trajectory_reason,
              scope, surface, actor_json, inserted_at
            FROM incidents
            WHERE incident_id = ?
            """,
            (incident_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None

    (
        incident_id, kind, run_id, repo_full_name, workflow_name, run_number,
        status, conclusion, html_url, created_at, updated_at, title,
        tags_json, evidence_json, summary_json,
        why_this_fired, risk_trajectory, risk_trajectory_reason,
        scope, surface, actor_json, inserted_at
    ) = row

    return {
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
        "why_this_fired": why_this_fired,
        "risk_trajectory": risk_trajectory,
        "risk_trajectory_reason": risk_trajectory_reason,
        "scope": scope,
        "surface": surface,
        "actor": json.loads(actor_json) if actor_json else None,
        "inserted_at": inserted_at,
    }

async def _build_summary(incident: Dict[str, Any]) -> Dict[str, Any]:
    if settings.ANTHROPIC_API_KEY:
        llm = await _llm_summary(incident)
        if llm:
            return llm

    repo = incident.get("repo_full_name") or "unknown repo"
    workflow = incident.get("workflow_name") or "Workflow"
    conclusion = incident.get("conclusion") or "unknown"
    run_number = incident.get("run_number")

    run_label = f"run #{run_number}" if run_number else "a recent run"

    root_cause = [
        f"{workflow} reported {conclusion} for {repo}.",
        f"The failing signal comes from {run_label} on GitHub Actions.",
        "No additional diagnostics were captured yet.",
    ]
    impact = [
        "Recent changes may be blocked from clean CI validation.",
        "Downstream workflows could be delayed until this clears.",
        "Confidence in the latest commit state is reduced.",
    ]
    next_steps = [
        "Open the run logs and identify the first failing step.",
        "Check recent commits or configuration changes in the repo.",
        "Re-run the workflow after applying a fix or rollback.",
    ]

    return {
        "root_cause": root_cause,
        "impact": impact,
        "next_steps": next_steps,
        "why_this_fired": "",
        "risk_trajectory": "stable",
        "risk_trajectory_reason": "Insufficient trend data; defaulting to stable.",
    }

def _validate_trajectory(payload: Dict[str, Any]) -> Dict[str, Any]:
    traj = payload.get("risk_trajectory")
    reason = payload.get("risk_trajectory_reason")
    if traj not in ("increasing", "stable", "recovering"):
        traj = "stable"
    if not reason or not isinstance(reason, str):
        reason = "Insufficient trend data; defaulting to stable."
    return {
        "risk_trajectory": traj,
        "risk_trajectory_reason": reason,
    }

def _validate_why(payload: Dict[str, Any]) -> str:
    why = payload.get("why_this_fired")
    if not why or not isinstance(why, str):
        return ""
    return why[:120]

async def _fetch_recent_repo_incidents(db_path: str, repo_full_name: str, limit: int = 5) -> List[Dict[str, Any]]:
    async with connect(db_path) as db:
        cur = await db.execute(
            """
            SELECT incident_id, created_at, kind, conclusion, summary_json, evidence_json
            FROM incidents
            WHERE repo_full_name = ? AND created_at >= datetime('now','-1 hour')
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (repo_full_name, limit),
        )
        rows = await cur.fetchall()

    recent = []
    for incident_id, created_at, kind, conclusion, summary_json, evidence_json in rows:
        recent.append({
            "incident_id": incident_id,
            "created_at": created_at,
            "kind": kind,
            "conclusion": conclusion,
            "summary": json.loads(summary_json) if summary_json else None,
            "evidence": json.loads(evidence_json) if evidence_json else None,
        })
    return recent

async def _llm_summary(incident: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    prompt = {
        "title": incident.get("title"),
        "kind": incident.get("kind"),
        "repo_full_name": incident.get("repo_full_name"),
        "workflow_name": incident.get("workflow_name"),
        "status": incident.get("status"),
        "conclusion": incident.get("conclusion"),
        "tags": incident.get("tags"),
        "evidence": incident.get("evidence"),
    }
    if incident.get("_recent_repo_incidents") is not None:
        prompt["recent_repo_incidents"] = incident.get("_recent_repo_incidents")

    system = (
        "You are a security incident summarizer. Return ONLY JSON with keys "
        "root_cause, impact, next_steps (arrays of 3-5 bullets), plus "
        "why_this_fired (1 concise sentence, max 120 chars), "
        "risk_trajectory (increasing|stable|recovering) and risk_trajectory_reason (1 sentence). "
        "Do not include secrets or token values. Keep each bullet under 20 words."
    )
    user = f"Summarize this incident:\n{json.dumps(prompt)}"

    headers = {
        "x-api-key": settings.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.ANTHROPIC_MODEL,
        "max_tokens": 450,
        "temperature": 0.2,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=body)
            if resp.status_code != 200:
                err = None
                try:
                    err = resp.json().get("error", {}).get("message")
                except Exception:
                    err = None
                print(f"[summary] LLM error status={resp.status_code} msg={err}")
                return None
            data = resp.json()
            text = ""
            for block in data.get("content", []):
                if block.get("type") == "text":
                    text += block.get("text", "")
            parsed = json.loads(text)
            if not all(k in parsed for k in ("root_cause", "impact", "next_steps")):
                print("[summary] LLM response missing expected keys")
                return None
            traj = _validate_trajectory(parsed)
            parsed.update(traj)
            parsed["why_this_fired"] = _validate_why(parsed)
            print("[summary] LLM summary generated")
            return parsed
    except Exception as e:
        print(f"[summary] LLM exception: {type(e).__name__}")
        return None

async def _store_summary(db_path: str, incident_id: str, summary: Dict[str, Any]) -> None:
    async with connect(db_path) as db:
        await db.execute(
            "UPDATE incidents SET summary_json = ? WHERE incident_id = ?",
            (json.dumps(summary), incident_id),
        )
        await db.commit()

async def summary_worker_loop(db_path: str, queue: Any, broadcaster) -> None:
    while True:
        incident_id = await queue.dequeue()
        if not incident_id:
            continue
        incident = await _fetch_incident(db_path, incident_id)
        if not incident:
            continue

        recent = await _fetch_recent_repo_incidents(db_path, incident.get("repo_full_name"), limit=5)
        incident["_recent_repo_incidents"] = recent

        summary = await _build_summary(incident)
        await _store_summary(db_path, incident_id, summary)

        # Emit updated card with summary for live clients.
        card = dict(incident)
        card["summary"] = summary
        card["why_this_fired"] = summary.get("why_this_fired")
        card["risk_trajectory"] = summary.get("risk_trajectory")
        card["risk_trajectory_reason"] = summary.get("risk_trajectory_reason")
        await broadcaster.publish(card)
