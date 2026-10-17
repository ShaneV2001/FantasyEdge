"""Record a scrubbed ESPN league fixture for offline tests.

The repo is public, so a recording from a real (private) league is anonymised before it is written:
league / team / owner names, the league ID and every member GUID (SWID) are replaced with fakes,
and anything else that could identify the league (logos, draft details, creation info) is dropped.
Player names, stats and scoring settings are public NFL data and are kept so the scoring test can
check our conversion against the points ESPN awarded.

Run (cookies come from the local .env; nothing is printed):
    cd backend && uv run python ../scripts/record_espn_fixture.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from ingest.espn import Cookies  # noqa: E402
from ingest.run import make_clients  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "backend" / "tests" / "fixtures" / "espn_league.json"
FAKE_LEAGUE_ID = 12345678
KEEP_TEAMS = 4


def fake_guid(i: int) -> str:
    return "{00000000-0000-4000-8000-%012d}" % i


def trim_player(p: dict, season: int) -> dict:
    stats = [
        s
        for s in p.get("stats") or []
        if s.get("seasonId") == season and s.get("statSourceId") == 0 and s.get("statSplitTypeId") == 1
    ]
    return {
        "id": p["id"],
        "fullName": p.get("fullName"),
        "defaultPositionId": p.get("defaultPositionId"),
        "proTeamId": p.get("proTeamId"),
        "injuryStatus": p.get("injuryStatus"),
        "stats": [
            {k: s[k] for k in ("seasonId", "scoringPeriodId", "statSourceId", "statSplitTypeId", "stats", "appliedTotal")}
            for s in stats
        ],
    }


def scrub(raw: dict) -> tuple[dict, list[str]]:
    """(scrubbed league, original identifiers that must not appear in it)."""
    season = raw["seasonId"]
    s = raw["settings"]
    secrets = [str(raw["id"]), s.get("name") or ""]
    teams = sorted(raw["teams"], key=lambda t: t["id"])[:KEEP_TEAMS]
    member_ids = {m["id"] for m in raw.get("members") or []}
    secrets += list(member_ids)
    guid = {mid: fake_guid(i + 1) for i, mid in enumerate(sorted(member_ids))}
    for m in raw.get("members") or []:
        secrets += [m.get("displayName") or "", m.get("firstName") or "", m.get("lastName") or ""]
    out_teams = []
    for i, t in enumerate(teams, 1):
        secrets += [t.get("name") or "", t.get("abbrev") or "", t.get("location") or "", t.get("nickname") or ""]
        out_teams.append(
            {
                "id": t["id"],
                "name": f"Team {i}",
                "abbrev": f"T{i}",
                "owners": [guid[o] for o in t.get("owners") or []],
                "primaryOwner": guid.get(t.get("primaryOwner"), fake_guid(0)),
                "record": {"overall": {k: t["record"]["overall"][k] for k in ("wins", "losses", "ties", "pointsFor")}},
                "transactionCounter": {"acquisitionBudgetSpent": (t.get("transactionCounter") or {}).get("acquisitionBudgetSpent", 0)},
                "roster": {
                    "entries": [
                        {
                            "playerId": e["playerId"],
                            "lineupSlotId": e["lineupSlotId"],
                            "playerPoolEntry": {"player": trim_player(e["playerPoolEntry"]["player"], season)},
                        }
                        for e in t["roster"]["entries"]
                    ]
                },
            }
        )
    kept_owners = {o for t in teams for o in t.get("owners") or []}
    members = [
        {"id": guid[m["id"]], "displayName": f"owner{i}", "firstName": "Owner", "lastName": str(i)}
        for i, m in enumerate(sorted(raw.get("members") or [], key=lambda m: m["id"]), 1)
        if m["id"] in kept_owners
    ]
    settings = {
        "name": "Test League",
        "size": s.get("size"),
        "rosterSettings": {"lineupSlotCounts": s["rosterSettings"]["lineupSlotCounts"]},
        "scoringSettings": {"scoringItems": s["scoringSettings"]["scoringItems"]},
        "scheduleSettings": {
            k: s["scheduleSettings"].get(k)
            for k in ("matchupPeriodCount", "matchupPeriodLength", "playoffTeamCount", "playoffMatchupPeriodLength")
        },
        "tradeSettings": {"deadlineDate": s["tradeSettings"].get("deadlineDate")},
        "acquisitionSettings": {
            k: s["acquisitionSettings"].get(k) for k in ("acquisitionBudget", "acquisitionType", "isUsingAcquisitionBudget")
        },
        "draftSettings": {"keeperCount": (s.get("draftSettings") or {}).get("keeperCount", 0)},
    }
    league = {
        "id": FAKE_LEAGUE_ID,
        "seasonId": season,
        "scoringPeriodId": raw.get("scoringPeriodId"),
        "settings": settings,
        "status": {"finalScoringPeriod": (raw.get("status") or {}).get("finalScoringPeriod")},
        "members": members,
        "teams": out_teams,
    }
    return league, [x for x in secrets if x and len(x) >= 3]


def main() -> None:
    c = make_clients()
    st = c.settings
    if not (st.espn_s2 and st.espn_swid and st.espn_league_id):
        sys.exit("Set ESPN_S2, ESPN_SWID and ESPN_LEAGUE_ID in .env first.")
    raw = c.espn.league(st.espn_league_id, st.seasons[1], Cookies(st.espn_s2, st.espn_swid), force=True)
    league, secrets = scrub(raw)
    text = json.dumps(league, indent=1)
    # Owners can share a first or last name with an NFL player; player names are public, so check
    # everything except them.
    names = {e["playerPoolEntry"]["player"]["fullName"] for t in league["teams"] for e in t["roster"]["entries"]}
    checked = text
    for n in sorted(names, key=len, reverse=True):
        checked = checked.replace(json.dumps(n), '""')
    leaked = [x for x in secrets + [st.espn_s2, st.espn_swid] if x in checked]
    if leaked:
        sys.exit(f"Refusing to write: {len(leaked)} identifying value(s) survived the scrub.")
    OUT.write_text(text, encoding="utf-8")
    n = sum(len(t["roster"]["entries"]) for t in league["teams"])
    print(f"wrote {OUT.name}: {len(league['teams'])} teams, {n} roster entries")


if __name__ == "__main__":
    main()
