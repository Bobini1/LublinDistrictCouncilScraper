from pathlib import Path

from dotenv import load_dotenv


PROJECT_DIR = Path(__file__).resolve().parent
ENV_FILE = PROJECT_DIR / ".env"


def load_environment() -> None:
    """Read only this project's .env; explicit environment variables win."""
    load_dotenv(ENV_FILE, override=False, interpolate=False, encoding="utf-8-sig")
