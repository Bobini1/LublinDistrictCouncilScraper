"""Windowless Task Scheduler entry point with bounded, redacted UTF-8 logs."""

import io
import logging
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from logging.handlers import RotatingFileHandler
from typing import Optional, Sequence

import mattermost_notifier
from notifier_config import PROJECT_DIR, load_environment


LOG_FILE = PROJECT_DIR / ".logs" / "mattermost.log"


class SecretRedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        for name in ("MATTERMOST_BOT_TOKEN", "MATTERMOST_URL", "MATTERMOST_CHANNEL_ID"):
            value = os.environ.get(name)
            if value:
                message = message.replace(value, f"<{name}>")
        return message


def main(argv: Optional[Sequence[str]] = None) -> int:
    load_environment()
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(SecretRedactingFormatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("mattermost.scheduled")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)
    output = io.StringIO()
    try:
        logger.info("Run started.")
        with redirect_stdout(output), redirect_stderr(output):
            try:
                result = mattermost_notifier.main(argv)
            except Exception:
                traceback.print_exc()
                result = 1
        if output.getvalue():
            logger.log(logging.ERROR if result else logging.INFO, "%s", output.getvalue().rstrip())
        logger.info("Run finished with exit code %s.", result)
        return result
    finally:
        logger.removeHandler(handler)
        handler.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
