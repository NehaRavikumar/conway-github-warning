import asyncio
import json
from contextlib import suppress

import pytest

from app.check_runs import run_to_incident
from app.config import settings
from app.incidents import insert_incident
from app.db import connect, init_db
from app.summary_queue import SummaryQueue, summary_worker_loop

class DummyBroadcaster:
    def __init__(self):
        self.cards = []

    async def publish(self, incident):
        self.cards.append(incident)

@pytest.mark.asyncio
async def test_summary_worker_persists_summary(tmp_path):
    db_path = tmp_path / "app.db"
    await init_db(str(db_path))

    run = {
        "id": 123,
        "name": "CI",
        "conclusion": "failure",
        "status": "completed",
        "html_url": "https://example.com/runs/123",
        "run_number": 7,
        "created_at": "2024-01-01T00:00:00Z",
        "updated_at": "2024-01-01T00:00:00Z",
    }
    inc = run_to_incident(run, "owner/repo")
    inserted = await insert_incident(str(db_path), inc)
    assert inserted is True

    settings.ANTHROPIC_API_KEY = ""
    queue = SummaryQueue()
    await queue.enqueue(inc["incident_id"])
    broadcaster = DummyBroadcaster()

    task = asyncio.create_task(summary_worker_loop(str(db_path), queue, broadcaster))

    summary_json = None
    for _ in range(20):
        async with connect(str(db_path)) as db:
            cur = await db.execute(
                "SELECT summary_json FROM incidents WHERE incident_id = ?",
                (inc["incident_id"],),
            )
            row = await cur.fetchone()
            summary_json = row[0] if row else None
        if summary_json:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    with suppress(asyncio.CancelledError):
        await task

    assert summary_json is not None
    summary = json.loads(summary_json)
    assert "root_cause" in summary
    assert "impact" in summary
    assert "next_steps" in summary
    assert broadcaster.cards

@pytest.mark.asyncio
async def test_summary_queue_fifo():
    queue = SummaryQueue()
    await queue.enqueue("a")
    await queue.enqueue("b")
    assert await queue.dequeue() == "a"
    assert await queue.dequeue() == "b"
