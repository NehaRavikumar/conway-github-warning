from typing import Any, Dict, Iterable, List

from ..incidents import insert_incident
from ..services.osv_enrichment import maybe_enqueue_enrichment
from ..incident_fields import apply_incident_fields
from ..types.signal import RunContext, SignalPlugin

async def process_run_logs_for_signals(
    run_context: RunContext,
    logs: List[Dict[str, Any]],
    plugins: Iterable[SignalPlugin],
    correlator,
    db_path: str,
    broadcaster,
    source: str,
    summary_queue,
    enrichment_queue,
    ) -> int:
    emitted = 0
    for entry in logs:
        job_name = entry.get("job_name")
        log_text = entry.get("log_text") or ""
        ctx = RunContext(
            repo_full_name=run_context.repo_full_name,
            owner=run_context.owner,
            run_id=run_context.run_id,
            html_url=run_context.html_url,
            workflow_name=run_context.workflow_name,
            conclusion=run_context.conclusion,
            updated_at=run_context.updated_at,
            job_name=job_name,
        )

        for plugin in plugins:
            match = plugin.match(ctx, log_text)
            if not match:
                continue
            incident_bundle = correlator.ingest(
                match=match,
                repo_full_name=ctx.repo_full_name,
                owner=ctx.owner,
                occurred_at=ctx.updated_at,
                source_ids={"run_id": ctx.run_id, "job_name": job_name},
                source=source,
            )
            if not incident_bundle:
                continue

            incident = incident_bundle["incident"]
            summary = incident_bundle["summary"]
            apply_incident_fields(incident)
            inserted = await insert_incident(db_path, incident)
            if not inserted:
                continue
            await summary_queue.enqueue(incident["incident_id"])
            await maybe_enqueue_enrichment(incident, enrichment_queue, db_path)

            card = {
                "incident_id": incident["incident_id"],
                "kind": incident["kind"],
                "repo_full_name": incident["repo_full_name"],
                "title": incident["title"],
                "workflow_name": incident["workflow_name"],
                "run_id": incident["run_id"],
                "run_number": incident["run_number"],
                "conclusion": incident["conclusion"],
                "status": incident["status"],
                "html_url": incident["html_url"],
                "created_at": incident["created_at"],
                "tags": incident["_tags"],
                "evidence": incident["_evidence"],
                "scope": incident.get("scope"),
                "surface": incident.get("surface"),
                "actor": incident.get("actor"),
            }
            await broadcaster.publish(card)
            emitted += 1
    return emitted
