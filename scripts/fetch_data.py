"""Refresh data/contributions.json and data/repos.json from the GitHub GraphQL API.

Runs in the daily Action. Locally:  GH_TOKEN=ghp_xxx python scripts/fetch_data.py
Only the standard library is used.

The Action's built-in GITHUB_TOKEN can read your public contribution calendar.
Private contributions are counted only if "Include private contributions on my
profile" is on in your GitHub settings; for repos you don't own, use a PAT
stored as the CARDS_TOKEN secret.
"""
import datetime as dt
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "https://api.github.com/graphql"

CAL_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      contributionCalendar { weeks { contributionDays { date contributionCount } } }
    }
  }
}"""

REPO_QUERY = """
query($owner: String!, $name: String!) {
  repository(owner: $owner, name: $name) {
    name nameWithOwner description url stargazerCount forkCount
    primaryLanguage { name color }
  }
}"""


def gql(query: str, variables: dict, token: str) -> dict:
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "readme-cards"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if payload.get("errors"):
        sys.exit(f"GraphQL error: {payload['errors']}")
    return payload["data"]


def main() -> None:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        sys.exit("Set GH_TOKEN (a token that can read your profile).")
    cfg = json.loads((ROOT / "config.json").read_text())
    login = cfg["login"]

    today = dt.date.today()
    # 54 weeks covers both the 12-month chart and the 53-column heatmap.
    start = today - dt.timedelta(weeks=54)
    days: dict[str, int] = {}
    # The API allows at most one year per query, so ask in chunks.
    cursor = start
    while cursor <= today:
        end = min(cursor + dt.timedelta(days=360), today)
        data = gql(CAL_QUERY, {
            "login": login,
            "from": f"{cursor.isoformat()}T00:00:00Z",
            "to": f"{end.isoformat()}T23:59:59Z",
        }, token)
        for week in data["user"]["contributionsCollection"]["contributionCalendar"]["weeks"]:
            for d in week["contributionDays"]:
                days[d["date"]] = d["contributionCount"]
        cursor = end + dt.timedelta(days=1)

    out = {
        "login": login,
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "days": [{"date": k, "count": days[k]} for k in sorted(days)],
    }
    (ROOT / "data").mkdir(exist_ok=True)
    (ROOT / "data" / "contributions.json").write_text(json.dumps(out, indent=1))
    print(f"contributions: {len(out['days'])} days, {sum(days.values())} total")

    repos = []
    for entry in cfg.get("repos", []):
        # "owner/name" or {"repo": "owner/name", "description": "...override..."}
        full = entry if isinstance(entry, str) else entry["repo"]
        owner, name = full.split("/", 1)
        r = gql(REPO_QUERY, {"owner": owner, "name": name}, token)["repository"]
        if r:
            if isinstance(entry, dict) and entry.get("description"):
                r["description"] = entry["description"]
            repos.append(r)
        else:
            print(f"warning: repo {full} not found or not visible to this token")
    (ROOT / "data" / "repos.json").write_text(json.dumps(repos, indent=1))
    print(f"repos: {len(repos)}")


if __name__ == "__main__":
    main()
