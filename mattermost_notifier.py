import argparse
import datetime
import hashlib
import os
import sys
from typing import List, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

import requests

from event import Event
from notifier_config import load_environment
from scrape import get_events, increment_month


TIME_ZONE = ZoneInfo("Europe/Warsaw")
REQUEST_TIMEOUT = 30
WEEK_KEY_PROPERTY = "lublin_district_week_key"
WEEK_HASH_PROPERTY = "lublin_district_week_hash"


class MattermostClient:
    def __init__(self, base_url: str, token: str, session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": "LublinDistrictCouncilNotifier/1.0",
            }
        )
        self.user_id = ""

    def request(self, method: str, path: str, **kwargs):
        response = self.session.request(
            method,
            f"{self.base_url}/api/v4{path}",
            timeout=REQUEST_TIMEOUT,
            **kwargs,
        )
        if not response.ok:
            try:
                detail = response.json().get("message", response.text)
            except ValueError:
                detail = response.text
            raise RuntimeError(f"Mattermost API {response.status_code}: {detail}")
        return response.json() if response.content else None

    def verify_token(self) -> Mapping[str, object]:
        user = self.request("GET", "/users/me")
        self.user_id = str(user["id"])
        return user

    def weekly_post(
        self, channel_id: str, week_key: str, maximum_pages: int = 20
    ) -> Optional[Mapping[str, object]]:
        if not self.user_id:
            raise RuntimeError("Verify the bot token before looking up weekly posts.")
        for page in range(maximum_pages):
            page_data = self.request(
                "GET",
                f"/channels/{channel_id}/posts",
                params={"page": page, "per_page": 200},
            )
            order = page_data.get("order", [])
            posts = page_data.get("posts", {})
            for post_id in order:
                post = posts.get(post_id, {})
                props = post.get("props") or {}
                if (
                    props.get(WEEK_KEY_PROPERTY) == week_key
                    and post.get("user_id") == self.user_id
                    and not post.get("delete_at")
                ):
                    return post
            if len(order) < 200:
                return None
        raise RuntimeError(
            "Channel history scan limit reached before finding the weekly post. "
            "Refusing to create a possible duplicate."
        )

    def create_post(self, channel_id: str, message: str, week_key: str, content_hash: str):
        return self.request(
            "POST",
            "/posts",
            json={
                "channel_id": channel_id,
                "message": message,
                "props": {
                    WEEK_KEY_PROPERTY: week_key,
                    WEEK_HASH_PROPERTY: content_hash,
                },
            },
        )

    def update_post(self, post_id: str, message: str, week_key: str, content_hash: str):
        return self.request(
            "PUT",
            f"/posts/{post_id}/patch",
            json={
                "message": message,
                "props": {
                    WEEK_KEY_PROPERTY: week_key,
                    WEEK_HASH_PROPERTY: content_hash,
                },
            },
        )


def week_start(now: datetime.datetime) -> datetime.date:
    today = now.astimezone(TIME_ZONE).date()
    return today - datetime.timedelta(days=today.weekday())


def publication_week(now: datetime.datetime) -> datetime.date:
    """Return the week whose Friday evening publication is most recently due."""
    local_now = now.astimezone(TIME_ZONE)
    monday = week_start(local_now)
    friday_evening = datetime.datetime.combine(
        monday + datetime.timedelta(days=4), datetime.time(18), tzinfo=TIME_ZONE
    )
    if local_now >= friday_evening:
        return monday + datetime.timedelta(days=7)
    return monday


def get_week_events(monday: datetime.date) -> List[Event]:
    next_monday = monday + datetime.timedelta(days=7)
    month, year = monday.month, monday.year
    events = []
    # A week may straddle a month/year boundary. Fetch both months even if the
    # first has no events, and retain earlier days so the digest lasts all week.
    while datetime.date(year, month, 1) < next_monday:
        events.extend(
            event for event in get_events(month, year)
            if monday <= event.datetime.date() < next_monday
        )
        month, year = increment_month(month, year)
    return events


def format_weekly_post(monday: datetime.date, events: Sequence[Event]) -> str:
    sunday = monday + datetime.timedelta(days=6)
    lines = [
        f"### Posiedzenia rad dzielnic: {monday:%d.%m.%Y}–{sunday:%d.%m.%Y}",
    ]
    if not events:
        lines.extend(["", "Brak posiedzeń w tym tygodniu w aktualnym kalendarzu."])
    for event in sorted(
        events, key=lambda item: (item.datetime, item.title, item.place, item.source_url)
    ):
        title = event.title
        if event.source_url:
            title = f"[{title}]({event.source_url})"
        lines.extend(["", f"- **{event.datetime:%d.%m, %H:%M}** — {title}"])
        if event.place:
            lines.extend(["", f"  Miejsce: {event.place}"])
    return "\n".join(lines)


def sync_week(
    mattermost: MattermostClient,
    channel_id: str,
    monday: datetime.date,
    events: Sequence[Event],
    dry_run: bool = False,
    allow_create: bool = True,
) -> str:
    key = monday.isoformat()
    existing = mattermost.weekly_post(channel_id, key)
    if not events and not existing:
        return "empty"
    if not existing and not allow_create:
        return "not_published"

    message = format_weekly_post(monday, events)
    content_hash = hashlib.sha256(message.encode("utf-8")).hexdigest()
    if (
        existing
        and (existing.get("props") or {}).get(WEEK_HASH_PROPERTY) == content_hash
        and existing.get("message") == message
    ):
        return "unchanged"

    action = "update" if existing else "create"
    if dry_run:
        print(f"[{action}] {message}\n")
    elif existing:
        mattermost.update_post(str(existing["id"]), message, key, content_hash)
    else:
        mattermost.create_post(channel_id, message, key, content_hash)
    return action


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish weekly Lublin council digests on Friday evenings and refresh them."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print intended actions without posting.")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    load_environment()
    url = os.environ.get("MATTERMOST_URL", "").strip()
    token = os.environ.get("MATTERMOST_BOT_TOKEN", "")
    channel_id = os.environ.get("MATTERMOST_CHANNEL_ID", "")
    if not url or not token or not channel_id:
        print(
            "MATTERMOST_URL, MATTERMOST_BOT_TOKEN and MATTERMOST_CHANNEL_ID are required.",
            file=sys.stderr,
        )
        return 2

    mattermost = MattermostClient(url, token)
    bot_user = mattermost.verify_token()

    now = datetime.datetime.now(TIME_ZONE)
    current_week = week_start(now)
    publish_week = publication_week(now)
    # Finish scraping all relevant weeks before making any changes in Mattermost.
    events_by_week = {
        monday: get_week_events(monday)
        for monday in sorted({current_week, publish_week})
    }
    for monday, events in events_by_week.items():
        action = sync_week(
            mattermost, channel_id, monday, events, dry_run=args.dry_run,
            allow_create=(monday == publish_week),
        )
        mode = "Dry run: " if args.dry_run else ""
        print(
            f"{mode}Bot @{bot_user.get('username')} checked {len(events)} events "
            f"for the week starting {monday.isoformat()}: {action}."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
