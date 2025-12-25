import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # keep placeholders now; we’ll use these in Step 2+
    DB_PATH = os.getenv("DB_PATH", "../data/app.db")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

settings = Settings()

