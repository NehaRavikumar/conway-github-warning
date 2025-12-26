import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict

from .config import settings
from .incidents import insert_incident
from .github import GitHubClient
from .poll_events import RECENT_REPOS
from .repos import RepoScheduler
from .sse import IncidentBroadcaster
from .summary_queue import SummaryQueue
from .services.run_logs import RunLogFetcher
from .services.signal_pipeline import process_run_logs_for_signals
from .types.signal import RunContext

FAIL_CONCLUSIONS = {"failure", "timed_out"}

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def run_to_incident(run: Dict[str, Any], repo_full_name: str) -> Dict[str, Any]:
    run_id = int(run["id"])
    workflow_name = run.get("name") or run.get("workflow_name")
    conclusion = run.get("conclusion")
    status = run.get("status")
    html_url = run.get("html_url")
    run_number = run.get("run_number")

    tags = ["workflow", "failure", f"conclusion:{conclusion}", f"status:{status}"]
    title = f"{workflow_name or 'Workflow'} failed in {repo_full_name}"

    evidence = {
        "repo": repo_full_name,
        "run": run,
        "detected_at": now_iso(),
        "source": "actions_runs",
    }

    return {
        "incident_id": str(uuid.uuid4()),
        "kind": "workflow_failure",
        "run_id": run_id,
        "dedupe_key": None,
        "repo_full_name": repo_full_name,
        "workflow_name": workflow_name,
        "run_number": run_number,
        "status": status,
        "conclusion": conclusion,
        "html_url": html_url,
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
        "title": title,
        "tags_json": json.dumps(tags),
        "evidence_json": json.dumps(evidence),
        # also return these parsed for SSE card convenience
        "_tags": tags,
        "_evidence": evidence,
    }

async def check_runs_loop(
    broadcaster: IncidentBroadcaster,
    summary_queue: SummaryQueue,
    correlator,
    plugins,
):
    print("[runs] loop started")
    gh = GitHubClient(settings.GITHUB_TOKEN)
    scheduler = RepoScheduler(settings.HIGH_TRAFFIC_REPOS, min_interval_seconds=30)
    log_fetcher = RunLogFetcher(gh, per_minute=settings.LOG_FETCH_PER_MIN)
    
    while True:
        # feed scheduler from the live RECENT_REPOS buffer
        # (copy snapshot to avoid weirdness)
        #recent_snapshot = RECENT_REPOS[-50:]
        #for r in recent_snapshot:
            #scheduler.add_recent_repo(r)

        #repos = scheduler.next_batch(settings.MAX_REPOS_PER_CYCLE)
        repos = settings.HIGH_TRAFFIC_REPOS[: settings.MAX_REPOS_PER_CYCLE]
        print("[runs] checking HIGH_TRAFFIC only:", repos)

        #print(f"[runs] cycle checking {len(repos)} repos: {repos[:3]}{'...' if len(repos)>3 else ''}")

        emitted = 0
        
        for repo_full_name in repos:
            if "/" not in repo_full_name:
                continue
            owner, repo = repo_full_name.split("/", 1)

            try:
                data = await gh.list_workflow_runs(owner, repo, per_page=settings.RUNS_PER_REPO)
                runs = data.get("workflow_runs", []) or []

                for run in runs:
                    if run.get("conclusion") in FAIL_CONCLUSIONS:
                        inc = run_to_incident(run, repo_full_name)

                        inserted = await insert_incident(settings.DB_PATH, inc)
                        if inserted:
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
                            emitted += 1

                        run_ctx = RunContext(
                            repo_full_name=repo_full_name,
                            owner=owner,
                            run_id=inc["run_id"],
                            html_url=inc["html_url"],
                            workflow_name=inc["workflow_name"],
                            conclusion=inc["conclusion"],
                            updated_at=inc["updated_at"],
                        )
                        logs = await log_fetcher.fetch_run_logs(owner, repo, inc["run_id"]) or []
                        if logs:
                            await process_run_logs_for_signals(
                                run_ctx,
                                logs,
                                plugins,
                                correlator,
                                settings.DB_PATH,
                                broadcaster,
                                source="live",
                            )

                        # v1: single failure card per repo per cycle
                        break

            except Exception as e:
                # keep it quiet; optional for now:
                # print(f"[runs] {repo_full_name} error: {type(e).__name__}: {e}")
                print(f"[runs] {repo_full_name} error: {type(e).__name__}: {e}")

        if emitted:
            print(f"[runs] emitted {emitted} incidents (checked {len(repos)} repos)")

        await asyncio.sleep(settings.CHECK_RUNS_SECONDS)
