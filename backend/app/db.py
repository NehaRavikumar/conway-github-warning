import aiosqlite
from pathlib import Path

SCHEMA_SQL = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS events (
  event_id       TEXT PRIMARY KEY,
  event_type     TEXT NOT NULL,
  repo_full_name TEXT,
  actor_login    TEXT,
  created_at     TEXT NOT NULL,
  raw_json       TEXT NOT NULL,
  inserted_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_repo ON events(repo_full_name);

CREATE TABLE IF NOT EXISTS incidents (
  incident_id    TEXT PRIMARY KEY,
  kind           TEXT NOT NULL,
  run_id         INTEGER NOT NULL UNIQUE,
  dedupe_key     TEXT UNIQUE,
  repo_full_name TEXT NOT NULL,
  workflow_name  TEXT,
  run_number     INTEGER,
  status         TEXT,
  conclusion     TEXT,
  html_url       TEXT,
  created_at     TEXT,
  updated_at     TEXT,
  title          TEXT NOT NULL,
  tags_json      TEXT NOT NULL,
  evidence_json  TEXT NOT NULL,
  summary_json   TEXT,
  enrichment_json TEXT,
  why_this_fired TEXT,
  risk_trajectory TEXT,
  risk_trajectory_reason TEXT,
  scope          TEXT,
  surface        TEXT,
  actor_json     TEXT,
  inserted_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_incidents_repo ON incidents(repo_full_name);
CREATE INDEX IF NOT EXISTS idx_incidents_inserted ON incidents(inserted_at);
"""

async def init_db(db_path: str) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.executescript(SCHEMA_SQL)
        # Ensure new columns exist when upgrading an existing DB.
        cur = await db.execute("PRAGMA table_info(incidents)")
        cols = {row[1] for row in await cur.fetchall()}
        if "summary_json" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN summary_json TEXT")
        if "dedupe_key" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN dedupe_key TEXT")
        if "enrichment_json" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN enrichment_json TEXT")
        if "why_this_fired" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN why_this_fired TEXT")
        if "risk_trajectory" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN risk_trajectory TEXT")
        if "risk_trajectory_reason" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN risk_trajectory_reason TEXT")
        if "scope" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN scope TEXT")
        if "surface" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN surface TEXT")
        if "actor_json" not in cols:
            await db.execute("ALTER TABLE incidents ADD COLUMN actor_json TEXT")
        await db.commit()

def connect(db_path: str):
    return aiosqlite.connect(db_path)
