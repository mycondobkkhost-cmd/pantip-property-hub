import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    BASE_DIR = BASE_DIR

    GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_SHEET_NAME: str = os.getenv("GOOGLE_SHEET_NAME", "Properties")
    GOOGLE_CREDENTIALS_PATH: Path = BASE_DIR / os.getenv(
        "GOOGLE_CREDENTIALS_PATH", "credentials/service_account.json"
    )

    FACEBOOK_EMAIL: str = os.getenv("FACEBOOK_EMAIL", "")
    FACEBOOK_PASSWORD: str = os.getenv("FACEBOOK_PASSWORD", "")
    FACEBOOK_GROUP_URL: str = os.getenv("FACEBOOK_GROUP_URL", "")

    BROWSER_USER_DATA_DIR: Path = BASE_DIR / os.getenv(
        "BROWSER_USER_DATA_DIR", "cookies/facebook_session"
    )
    COOKIES_PATH: Path = BASE_DIR / os.getenv(
        "COOKIES_PATH", "cookies/facebook_cookies.json"
    )

    POST_INTERVAL_MINUTES: int = int(os.getenv("POST_INTERVAL_MINUTES", "120"))
    MAX_POSTS_PER_RUN: int = int(os.getenv("MAX_POSTS_PER_RUN", "3"))
    HEADLESS: bool = os.getenv("HEADLESS", "false").lower() == "true"

    IMAGE_CACHE_DIR: Path = BASE_DIR / os.getenv("IMAGE_CACHE_DIR", "data/images")
    LOGS_DIR: Path = BASE_DIR / "logs"


settings = Settings()
