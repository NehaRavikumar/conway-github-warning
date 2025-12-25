import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # keep placeholders now; we’ll use these in Step 2+
    DB_PATH = os.getenv("DB_PATH", "../data/app.db")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
    DEV_MODE = os.getenv("DEV_MODE", "false").lower() == "true"
    POLL_EVENTS_SECONDS = int(os.getenv("POLL_EVENTS_SECONDS", "10"))
    CHECK_RUNS_SECONDS = int(os.getenv("CHECK_RUNS_SECONDS", "20"))
    MAX_REPOS_PER_CYCLE = int(os.getenv("MAX_REPOS_PER_CYCLE", "8"))
    RUNS_PER_REPO = int(os.getenv("RUNS_PER_REPO", "5"))
    HIGH_TRAFFIC_REPOS = [x.strip() for x in os.getenv("HIGH_TRAFFIC_REPOS", "").split(",") if x.strip()]


settings = Settings()

