import asyncio
from datetime import datetime, timedelta, timezone
from typing import Iterable, List

from ..services.signal_pipeline import process_run_logs_for_signals
from ..types.signal import RunContext, SignalPlugin

async def run_replay_fixtures(
    plugins: Iterable[SignalPlugin],
    correlator,
    broadcaster,
    db_path: str,
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
        )
        await asyncio.sleep(0.05)

    return emitted

def _fixtures() -> List[tuple[RunContext, List[dict]]]:
    logs = [
        {
            "job_name": "build",
            "log_text": "npm ERR! code E401\nnpm ERR! Unable to authenticate, need: Basic",
        }
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
