# Lublin District Council Scraper

The project scrapes upcoming Lublin district council meetings. It can upload them to Google Calendar or post them to Mattermost.

## Install

```shell
python -m pip install -r requirements.txt
```

`python scrape.py` prints the scraped events. `python main.py` uploads them to Google Calendar; that command still needs the existing Google OAuth `credentials.json` and `token.json` setup.

## Mattermost notifier

`mattermost_notifier.py` performs one idempotent run:

1. scrapes meetings for the current Monday–Sunday week in `Europe/Warsaw`, and, from Friday at 18:00, for next week too; weeks crossing a month boundary include both months;
2. creates one digest containing all that week's meetings, ordered by date/time, with each meeting's title, place, and source link;
3. edits that same post when the list or displayed details change, and leaves it alone when unchanged.

The Monday date (for example, `2026-09-21`) is stored in the hidden `lublin_district_week_key` post property. The bot looks up its own post with that key on reruns; the rendered content hash is stored in `lublin_district_week_hash`. No local database is needed. If the weekly post cannot be found within the most recent 4,000 channel posts and older history remains, the run fails instead of risking a duplicate.

Next week's digest is published on **Friday at 18:00 Warsaw time**, then refreshed through the weekend and during that week. On Monday, the bot continues editing Friday's post using the same Monday-date key. The current week's existing digest also keeps receiving updates over the weekend. Past weekly posts are left as history.

Meetings from earlier days of the current week remain in the digest. Added, removed, or rescheduled meetings are reflected on the next successful scrape. If all meetings disappear from a previously posted week, its post is edited to say the current calendar has none; the bot does not infer that they were cancelled. A week that has no events and no existing post is skipped, but gets a post on a later run if events appear. Event descriptions/agendas are not included, so description-only changes do not cause an edit.

Any posts created by the older per-event notifier are left untouched; weekly digests use separate post properties.

### One-time bot setup

Ask a Mattermost system administrator to create a bot account on your server, copy its token, and add the bot to the destination channel. A normal member bot is sufficient; do not make it a system administrator.

Set these required environment variables:

```text
MATTERMOST_URL=https://mattermost.example
MATTERMOST_BOT_TOKEN=<secret bot token>
MATTERMOST_CHANNEL_ID=<26-character channel ID>
```

Replace the example URL with your Mattermost server's base URL, including `https://`. There is no default server address. Keep the token out of files committed to Git.

Inspect what a token can access using non-mutating API calls:

```shell
python inspect_mattermost_bot.py
```

The diagnostic script requires `MATTERMOST_URL` or an explicit `--url` argument. If `MATTERMOST_BOT_TOKEN` is not already set, the script prompts for it without echoing or saving it. It lists the bot's system roles, the server permissions granted by every assigned role, its teams and channels, and common channel capabilities such as posting and file uploads. Add `--show-ids` to include resource IDs or `--json` for machine-readable output.

Validate the integration without writing posts:

```shell
python mattermost_notifier.py --dry-run
```

The first live run creates at most one post: the current week's digest before Friday at 18:00, or next week's digest from Friday evening through Sunday. This also lets a delayed or missed Friday run catch up. During normal operation, later runs only edit the existing digest until the next Friday release.

### Unattended GitHub Actions schedule

The included workflow checks every four hours and has an additional Friday 18:00 schedule with `timezone: Europe/Warsaw`, so daylight saving changes are automatic. It can also be started manually. GitHub may delay scheduled jobs; the next run will catch up without creating another weekly post. See [GitHub's schedule documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule).

In the repository settings, add Actions secrets named `MATTERMOST_URL`, `MATTERMOST_BOT_TOKEN`, and `MATTERMOST_CHANNEL_ID`. Push the workflow to the default branch, enable Actions for the repository, and manually run **Notify Mattermost about council meetings** once to verify it.

The configured Mattermost server must be reachable from GitHub-hosted runners. If the server later becomes private or VPN-only, run the same command from a local scheduler instead.

## Tests

```shell
python -m unittest discover -s tests -v
```
