import pytest

from app.db import init_db, connect
from app.plugins.npm_auth_token_expired import NpmAuthTokenExpiredPlugin
from app.replay.fixtures import run_replay_fixtures
from app.services.correlator import EcosystemCorrelator

class DummyBroadcaster:
    def __init__(self):
        self.cards = []

    async def publish(self, card):
        self.cards.append(card)

@pytest.mark.asyncio
async def test_replay_fixtures_emit_single_incident(tmp_path):
    db_path = tmp_path / "app.db"
    await init_db(str(db_path))

    correlator = EcosystemCorrelator(
        window_minutes=60,
        min_repos=5,
        min_owners=3,
        cooldown_minutes=30,
    )
    plugins = [NpmAuthTokenExpiredPlugin()]
    broadcaster = DummyBroadcaster()

    emitted = await run_replay_fixtures(plugins, correlator, broadcaster, str(db_path))
    assert emitted == 1

    async with connect(str(db_path)) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM incidents WHERE kind = ?",
            ("ecosystem_incident",),
        )
        row = await cur.fetchone()
    assert row[0] == 1
