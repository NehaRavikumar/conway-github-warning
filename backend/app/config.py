import os
from dotenv import load_dotenv

if not os.getenv("FLY_APP_NAME"):
    load_dotenv(override=False)

class Settings:
    # keep placeholders now; we’ll use these in Step 2+
    DB_PATH = os.getenv("DB_PATH", "../data/app.db")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    REDIS_URL = os.getenv("REDIS_URL", "")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-haiku-20241022")
    DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
    POLL_EVENTS_SECONDS = int(os.getenv("POLL_EVENTS_SECONDS", "10"))
    CHECK_RUNS_SECONDS = int(os.getenv("CHECK_RUNS_SECONDS", "10"))
    MAX_REPOS_PER_CYCLE = int(os.getenv("MAX_REPOS_PER_CYCLE", "20"))
    RUNS_PER_REPO = int(os.getenv("RUNS_PER_REPO", "25"))
    HIGH_TRAFFIC_REPOS = [x.strip() for x in os.getenv("HIGH_TRAFFIC_REPOS", "").split(",") if x.strip()]
    MAX_WORKFLOW_FETCHES_PER_CYCLE = int(os.getenv("MAX_WORKFLOW_FETCHES_PER_CYCLE", "5"))
    GHOSTACTION_SCORE_THRESHOLD = int(os.getenv("GHOSTACTION_SCORE_THRESHOLD", "60"))
    WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "60"))
    MIN_REPOS = int(os.getenv("MIN_REPOS", "5"))
    MIN_OWNERS = int(os.getenv("MIN_OWNERS", "3"))
    COOLDOWN_MINUTES = int(os.getenv("COOLDOWN_MINUTES", "30"))
    LOG_FETCH_PER_MIN = int(os.getenv("LOG_FETCH_PER_MIN", "20"))
    REPLAY_FIXTURES = os.getenv("REPLAY_FIXTURES", "0") == "1"
    REPLAY_ALWAYS = os.getenv("REPLAY_ALWAYS", "0") == "1"


settings = Settings()
