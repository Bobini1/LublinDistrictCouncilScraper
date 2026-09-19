import argparse
import getpass
import json
import os
import sys
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Set

from mattermost_notifier import MattermostClient


CHANNEL_TYPES = {
    "O": "public",
    "P": "private",
    "D": "direct message",
    "G": "group message",
}

COMMON_ACTIONS = {
    "read messages": {"read_channel"},
    "post messages": {"create_post", "create_post_public"},
    "upload files": {"upload_file"},
    "add reactions": {"add_reaction"},
    "use @channel/@all": {"use_channel_mentions"},
    "edit own posts": {"edit_post"},
    "delete own posts": {"delete_post"},
    "manage channel members": {
        "manage_public_channel_members",
        "manage_private_channel_members",
    },
    "manage channel properties": {
        "manage_public_channel_properties",
        "manage_private_channel_properties",
    },
}


def split_roles(value: object) -> List[str]:
    return [role for role in str(value or "").split() if role]


def permissions_for_roles(
    role_names: Iterable[str], role_definitions: Mapping[str, Mapping[str, object]]
) -> Set[str]:
    permissions: Set[str] = set()
    for role_name in role_names:
        role = role_definitions.get(role_name, {})
        permissions.update(str(permission) for permission in role.get("permissions", []))
    return permissions


def summarize_actions(permissions: Set[str], archived: bool = False) -> Dict[str, bool]:
    actions = {
        label: bool(required_permissions & permissions)
        for label, required_permissions in COMMON_ACTIONS.items()
    }
    if archived:
        actions["post messages"] = False
        actions["upload files"] = False
    return actions


def channel_label(channel: Mapping[str, object]) -> str:
    channel_type = str(channel.get("type") or "")
    if channel_type in {"D", "G"}:
        return CHANNEL_TYPES[channel_type]
    return str(channel.get("display_name") or channel.get("name") or "unnamed channel")


def collect_snapshot(client: MattermostClient) -> Dict[str, object]:
    user = client.verify_token()
    user_id = str(user["id"])
    warnings = []

    ping = client.request("GET", "/system/ping")
    teams = client.request("GET", f"/users/{user_id}/teams")
    team_memberships = client.request("GET", f"/users/{user_id}/teams/members")
    team_memberships_by_id = {
        str(membership["team_id"]): membership for membership in team_memberships
    }

    try:
        channels = client.request(
            "GET",
            f"/users/{user_id}/channels",
            params={"include_deleted": "true"},
        )
    except RuntimeError as error:
        warnings.append(f"Could not use the all-channels endpoint: {error}")
        channels = []
        for team in teams:
            channels.extend(
                client.request(
                    "GET",
                    f"/users/{user_id}/teams/{team['id']}/channels",
                    params={"include_deleted": "true"},
                )
            )

    channels_by_id = {str(channel["id"]): channel for channel in channels}
    channel_memberships_by_id: Dict[str, Mapping[str, object]] = {}
    for team in teams:
        memberships = client.request(
            "GET", f"/users/{user_id}/teams/{team['id']}/channels/members"
        )
        for membership in memberships:
            channel_memberships_by_id[str(membership["channel_id"])] = membership

    for channel_id in channels_by_id.keys() - channel_memberships_by_id.keys():
        try:
            membership = client.request(
                "GET", f"/channels/{channel_id}/members/{user_id}"
            )
            channel_memberships_by_id[channel_id] = membership
        except RuntimeError as error:
            warnings.append(
                f"Could not read membership for channel {channel_id}: {error}"
            )

    system_roles = split_roles(user.get("roles"))
    all_role_names = set(system_roles)
    for membership in team_memberships_by_id.values():
        all_role_names.update(split_roles(membership.get("roles")))
    for membership in channel_memberships_by_id.values():
        all_role_names.update(split_roles(membership.get("roles")))

    role_definitions: Dict[str, Mapping[str, object]] = {}
    if all_role_names:
        try:
            roles = client.request("POST", "/roles/names", json=sorted(all_role_names))
            role_definitions = {str(role["name"]): role for role in roles}
        except RuntimeError as error:
            warnings.append(f"Could not resolve role permissions: {error}")

    global_permissions = permissions_for_roles(system_roles, role_definitions)
    team_results = []
    teams_by_id = {str(team["id"]): team for team in teams}
    for team_id, team in sorted(
        teams_by_id.items(), key=lambda item: str(item[1].get("display_name") or "").casefold()
    ):
        team_membership = team_memberships_by_id.get(team_id, {})
        team_roles = split_roles(team_membership.get("roles"))
        team_permissions = global_permissions | permissions_for_roles(
            team_roles, role_definitions
        )
        team_channels = []

        for channel_id, channel in sorted(
            channels_by_id.items(), key=lambda item: channel_label(item[1]).casefold()
        ):
            if str(channel.get("team_id") or "") != team_id:
                continue
            channel_membership = channel_memberships_by_id.get(channel_id, {})
            channel_roles = split_roles(channel_membership.get("roles"))
            effective_permissions = team_permissions | permissions_for_roles(
                channel_roles, role_definitions
            )
            archived = bool(channel.get("delete_at"))
            team_channels.append(
                {
                    "id": channel_id,
                    "name": channel_label(channel),
                    "type": CHANNEL_TYPES.get(str(channel.get("type") or ""), "unknown"),
                    "archived": archived,
                    "roles": channel_roles,
                    "actions": summarize_actions(effective_permissions, archived),
                    "effective_permissions": sorted(effective_permissions),
                }
            )

        team_results.append(
            {
                "id": team_id,
                "name": str(team.get("display_name") or team.get("name") or "unnamed team"),
                "roles": team_roles,
                "effective_permissions": sorted(team_permissions),
                "channels": team_channels,
            }
        )

    unscoped_channels = []
    known_team_ids = set(teams_by_id)
    for channel_id, channel in sorted(
        channels_by_id.items(), key=lambda item: channel_label(item[1]).casefold()
    ):
        if str(channel.get("team_id") or "") in known_team_ids:
            continue
        channel_membership = channel_memberships_by_id.get(channel_id, {})
        channel_roles = split_roles(channel_membership.get("roles"))
        effective_permissions = global_permissions | permissions_for_roles(
            channel_roles, role_definitions
        )
        archived = bool(channel.get("delete_at"))
        unscoped_channels.append(
            {
                "id": channel_id,
                "name": channel_label(channel),
                "type": CHANNEL_TYPES.get(str(channel.get("type") or ""), "unknown"),
                "archived": archived,
                "roles": channel_roles,
                "actions": summarize_actions(effective_permissions, archived),
                "effective_permissions": sorted(effective_permissions),
            }
        )

    return {
        "server": {
            "url": client.base_url,
            "status": ping.get("status") if isinstance(ping, dict) else None,
        },
        "account": {
            "id": user_id,
            "username": str(user.get("username") or ""),
            "is_bot": bool(user.get("is_bot")),
            "active": not bool(user.get("delete_at")),
            "roles": system_roles,
            "effective_permissions": sorted(global_permissions),
        },
        "roles": {
            name: {
                "display_name": str(role.get("display_name") or ""),
                "permissions": sorted(str(item) for item in role.get("permissions", [])),
            }
            for name, role in sorted(role_definitions.items())
        },
        "teams": team_results,
        "other_channels": unscoped_channels,
        "warnings": warnings,
    }


def yes_no(value: bool) -> str:
    return "yes" if value else "no"


def print_channel(channel: Mapping[str, object], show_ids: bool) -> None:
    archived = ", archived" if channel["archived"] else ""
    identifier = f" ({channel['id']})" if show_ids else ""
    print(f"    - {channel['name']}{identifier} [{channel['type']}{archived}]")
    print(f"      roles: {' '.join(channel['roles']) or '(none returned)'}")
    actions = channel["actions"]
    print(
        "      common actions: "
        + ", ".join(f"{name}={yes_no(bool(allowed))}" for name, allowed in actions.items())
    )


def print_snapshot(snapshot: Mapping[str, object], show_ids: bool) -> None:
    server = snapshot["server"]
    account = snapshot["account"]
    identifier = f" ({account['id']})" if show_ids else ""
    print(f"Server: {server['url']} (status: {server['status'] or 'unknown'})")
    print(
        f"Account: @{account['username']}{identifier}; "
        f"bot={yes_no(bool(account['is_bot']))}; active={yes_no(bool(account['active']))}"
    )
    print(f"System roles: {' '.join(account['roles']) or '(none returned)'}")
    print(
        f"System-level permissions ({len(account['effective_permissions'])}): "
        + (", ".join(account["effective_permissions"]) or "(none resolved)")
    )

    print("\nAssigned role definitions:")
    if not snapshot["roles"]:
        print("  (role permissions unavailable)")
    for role_name, role in snapshot["roles"].items():
        permissions = ", ".join(role["permissions"]) or "(none)"
        print(f"  - {role_name}: {permissions}")

    print("\nTeams and channels:")
    if not snapshot["teams"]:
        print("  (the bot is not a member of any team)")
    for team in snapshot["teams"]:
        identifier = f" ({team['id']})" if show_ids else ""
        print(f"  {team['name']}{identifier}")
        print(f"    roles: {' '.join(team['roles']) or '(none returned)'}")
        if not team["channels"]:
            print("    (no channels returned)")
        for channel in team["channels"]:
            print_channel(channel, show_ids)

    if snapshot["other_channels"]:
        print("\nDirect/group or otherwise unscoped channels:")
        for channel in snapshot["other_channels"]:
            print_channel(channel, show_ids)

    if snapshot["warnings"]:
        print("\nWarnings:")
        for warning in snapshot["warnings"]:
            print(f"  - {warning}")

    print(
        "\nThese capabilities are derived from the server's role definitions. "
        "Server configuration, licensing, channel state, and resource-specific rules may narrow them."
    )


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect a Mattermost bot token using non-mutating API calls."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("MATTERMOST_URL", ""),
        help="Mattermost base URL (required here or through MATTERMOST_URL).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "--show-ids", action="store_true", help="Include account, team, and channel IDs."
    )
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="Fail instead of prompting when MATTERMOST_BOT_TOKEN is unset.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    args.url = args.url.strip()
    if not args.url:
        print("MATTERMOST_URL or --url is required.", file=sys.stderr)
        return 2
    token = os.environ.get("MATTERMOST_BOT_TOKEN")
    if not token:
        if args.no_prompt or not sys.stdin.isatty():
            print(
                "MATTERMOST_BOT_TOKEN is required when input is non-interactive.",
                file=sys.stderr,
            )
            return 2
        token = getpass.getpass("Mattermost bot token (input hidden): ")
    if not token:
        print("No token supplied.", file=sys.stderr)
        return 2

    try:
        snapshot = collect_snapshot(MattermostClient(args.url, token))
    except Exception as error:
        print(f"Inspection failed: {error}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
    else:
        print_snapshot(snapshot, args.show_ids)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
