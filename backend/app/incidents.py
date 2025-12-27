import json
from typing import Any, Dict

from .db import connect

async def insert_incident(db_path: str, inc: Dict[str, Any]) -> bool:
    async with connect(db_path) as db:
        try:
            cur = await db.execute(
                """INSERT OR IGNORE INTO incidents(
                    incident_id, kind, run_id, dedupe_key, repo_full_name, workflow_name, run_number,
                    status, conclusion, html_url, created_at, updated_at,
                    title, tags_json, evidence_json, enrichment_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    inc["incident_id"], inc["kind"], inc["run_id"], inc.get("dedupe_key"),
                    inc["repo_full_name"], inc["workflow_name"], inc["run_number"],
                    inc["status"], inc["conclusion"], inc["html_url"], inc["created_at"], inc["updated_at"],
                    inc["title"], inc["tags_json"], inc["evidence_json"], inc.get("enrichment_json"),
                ),
            )
            await db.commit()
            return (cur.rowcount or 0) > 0   # 1 if inserted, 0 if ignored
        except Exception as e:
            print(f"[incidents] insert failed: {type(e).__name__}: {e}")
            return False

async def set_summary(db_path: str, incident_id: str, summary: Dict[str, Any]) -> None:
    async with connect(db_path) as db:
        await db.execute(
            "UPDATE incidents SET summary_json = ? WHERE incident_id = ?",
            (json.dumps(summary), incident_id),
        )
        await db.commit()

async def set_enrichment(db_path: str, incident_id: str, enrichment: Dict[str, Any]) -> None:
    async with connect(db_path) as db:
        await db.execute(
            "UPDATE incidents SET enrichment_json = ? WHERE incident_id = ?",
            (json.dumps(enrichment), incident_id),
        )
        await db.commit()
