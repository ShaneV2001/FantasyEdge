"""ESPN league scoring → our rule dict (Sleeper key names), and ESPN stat lines → our stat columns.

ESPN lists `scoringItems` keyed by stat ID. An item has base `points` and optional
`pointsOverrides` keyed by ESPN position ID (1 QB, 2 RB, 3 WR, 4 TE, 5 K, 16 D/ST); a league whose
QB passing rules are set per position stores them only as overrides. Like a Sleeper league, an ESPN
league scores exactly what it lists: anything it doesn't list is worth 0.

ESPN's yardage-bonus brackets are exclusive (a 250-yard game earns the 200+ bonus only) while ours
are cumulative (it earns the 100 and the 200 bonus), so the 200+ value is stored as the difference.
Rules we can't model are returned, never silently dropped.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from scoring.rules import PTS_ALLOW, RULE_KEYS, YDS_ALLOW

QB, RB, WR, TE, K, DST = 1, 2, 3, 4, 5, 16
POSITION = {QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DST: "DEF"}

# stat ID -> (our rule key, ESPN position whose value we use)
DIRECT: dict[int, tuple[str, int]] = {
    0: ("pass_att", QB), 1: ("pass_cmp", QB), 2: ("pass_inc", QB), 3: ("pass_yd", QB),
    4: ("pass_td", QB), 19: ("pass_2pt", QB), 20: ("pass_int", QB), 64: ("pass_sack", QB),
    23: ("rush_att", RB), 24: ("rush_yd", RB), 25: ("rush_td", RB), 26: ("rush_2pt", RB),
    42: ("rec_yd", WR), 43: ("rec_td", WR), 44: ("rec_2pt", WR),
    68: ("fum", RB), 72: ("fum_lost", RB),
    77: ("fgm_40_49", K), 74: ("fgm_50p", K), 198: ("fgm_50_59", K), 201: ("fgm_60p", K),
    83: ("fgm", K), 85: ("fgmiss", K), 86: ("xpm", K), 88: ("xpmiss", K),
    99: ("sack", DST), 95: ("int", DST), 96: ("fum_rec", DST), 106: ("ff", DST),
    98: ("safe", DST), 97: ("blk_kick", DST), 205: ("def_2pt", DST), 206: ("def_2pt", DST),
    89: ("espn_pts_allow_0", DST), 90: ("espn_pts_allow_1_6", DST),
    91: ("espn_pts_allow_7_13", DST), 92: ("espn_pts_allow_14_17", DST),
    121: ("espn_pts_allow_18_21", DST), 122: ("espn_pts_allow_22_27", DST),
    123: ("espn_pts_allow_28_34", DST), 124: ("espn_pts_allow_35_45", DST),
    125: ("espn_pts_allow_46p", DST),
    128: ("yds_allow_0_100", DST), 129: ("yds_allow_100_199", DST),
    130: ("yds_allow_200_299", DST), 131: ("yds_allow_300_349", DST),
    132: ("yds_allow_350_399", DST), 133: ("yds_allow_400_449", DST),
    134: ("yds_allow_450_499", DST), 135: ("yds_allow_500_549", DST),
    136: ("yds_allow_550p", DST),
}  # fmt: skip
# Under-40 field goals are one ESPN stat; our rules split them by distance (same value each).
UNDER_40 = 80
# Exclusive ESPN yardage brackets: (low-bracket stat, high-bracket stat, our low key, our high key)
YARD_BONUSES = (
    (17, 18, "bonus_pass_yd_300", "bonus_pass_yd_400", QB),
    (37, 38, "bonus_rush_yd_100", "bonus_rush_yd_200", RB),
    (56, 57, "bonus_rec_yd_100", "bonus_rec_yd_200", WR),
)
RECEPTIONS = (53, 41)  # both are "receptions" in ESPN's stat table
DEF_TD = (103, 104, 93, 94)  # INT / fumble return, blocked-kick and generic defensive TDs
RETURN_TD = (101, 102)  # kickoff / punt return TDs (D/ST)
TWO_PT_ANY = 62  # "2-point conversions" without a play type

# Names for rules we can't model, so the UI can say what's missing.
NAMES: dict[int, str] = {
    15: "40+ yard passing TD bonus", 16: "50+ yard passing TD bonus",
    35: "40+ yard rushing TD bonus", 36: "50+ yard rushing TD bonus",
    45: "40+ yard receiving TD bonus", 46: "50+ yard receiving TD bonus",
    58: "targets", 63: "offensive fumble recovered for TD", 73: "turnovers",
    75: "50+ yard FG attempts", 76: "50+ yard FG misses", 78: "40-49 yard FG attempts",
    79: "40-49 yard FG misses", 81: "under-40 FG attempts", 82: "under-40 FG misses",
    84: "FG attempts", 87: "extra-point attempts", 107: "assisted tackles", 108: "solo tackles",
    109: "total tackles", 113: "passes defended", 114: "kick return yards",
    115: "punt return yards", 120: "points allowed (per point)",
    127: "yards allowed (per yard)", 209: "1-point safety",
}  # fmt: skip


def _value(item: Mapping, pos: int) -> float:
    """Points this item gives a player at ESPN position `pos`."""
    overrides = item.get("pointsOverrides") or {}
    if str(pos) in overrides:
        return float(overrides[str(pos)])
    return float(item.get("points") or 0.0)


def _nonzero(item: Mapping) -> bool:
    return bool(item.get("points")) or any((item.get("pointsOverrides") or {}).values())


def from_espn(scoring_items: Iterable[Mapping]) -> tuple[dict[str, float], list[str]]:
    """(rules, unmodeled): our rules for an ESPN league, plus the rules we couldn't model."""
    items = {int(i["statId"]): i for i in scoring_items}
    rules = dict.fromkeys(RULE_KEYS, 0.0)
    if not items:
        raise ValueError("ESPN league has no scoring settings")
    used: set[int] = set()
    unmodeled: list[str] = []

    for sid, (key, pos) in DIRECT.items():
        if sid in items:
            rules[key] = _value(items[sid], pos)
            used.add(sid)
    if UNDER_40 in items:
        v = _value(items[UNDER_40], K)
        rules["fgm_0_19"] = rules["fgm_20_29"] = rules["fgm_30_39"] = v
        used.add(UNDER_40)
    for lo, hi, lo_key, hi_key, pos in YARD_BONUSES:
        lo_v = _value(items[lo], pos) if lo in items else 0.0
        hi_v = _value(items[hi], pos) if hi in items else 0.0
        rules[lo_key] = lo_v
        rules[hi_key] = hi_v - lo_v if lo_v or hi_v else 0.0
        used.update({lo, hi} & items.keys())

    rec = next((items[s] for s in RECEPTIONS if s in items), None)
    if rec is not None:
        rules["rec"] = _value(rec, WR)
        rules["bonus_rec_rb"] = _value(rec, RB) - rules["rec"]
        rules["bonus_rec_te"] = _value(rec, TE) - rules["rec"]
        used.update(set(RECEPTIONS) & items.keys())

    def first_nonzero(ids: tuple[int, ...]) -> float:
        vals = [_value(items[s], DST) for s in ids if s in items]
        used.update(set(ids) & items.keys())
        nz = [v for v in vals if v]
        if len(set(nz)) > 1:
            unmodeled.append("different points for different kinds of defensive TD (using one)")
        return nz[0] if nz else 0.0

    rules["def_td"] = first_nonzero(DEF_TD)
    rules["def_st_td"] = first_nonzero(RETURN_TD)
    if any(_value(items[s], p) for s in RETURN_TD if s in items for p in (RB, WR)):
        unmodeled.append("kick/punt return TDs by individual players")
    if TWO_PT_ANY in items:
        v = _value(items[TWO_PT_ANY], RB)
        for key in ("pass_2pt", "rush_2pt", "rec_2pt"):
            rules[key] = rules[key] or v
        used.add(TWO_PT_ANY)

    # Sleeper's points-allowed ranges are never what an ESPN league uses.
    for key, _ in PTS_ALLOW:
        rules[key] = 0.0
    assert all(k in rules for k, _ in YDS_ALLOW)

    for sid, item in sorted(items.items()):
        if sid not in used and _nonzero(item):
            unmodeled.append(NAMES.get(sid, f"ESPN stat #{sid}"))
    return rules, unmodeled


# ───────── stat lines (ESPN box score → our player_week_stats columns) ─────────

STAT_COLUMN: dict[int, str] = {
    0: "pass_att", 1: "pass_cmp", 3: "pass_yds", 4: "pass_td", 20: "interceptions",
    64: "sacks_taken", 19: "pass_2pt", 23: "carries", 24: "rush_yds", 25: "rush_td",
    26: "rush_2pt", 53: "receptions", 42: "rec_yds", 43: "rec_td", 44: "rec_2pt",
    68: "fumbles", 72: "fumbles_lost",
    80: "fgm_30_39", 77: "fgm_40_49", 198: "fgm_50_59", 201: "fgm_60p", 85: "fgmiss",
    86: "xpm", 88: "xpmiss",
    99: "def_sack", 95: "def_int", 96: "def_fum_rec", 106: "def_ff", 98: "def_safe",
    97: "def_blk_kick", 206: "def_2pt", 120: "pts_allow", 127: "yds_allow",
}  # fmt: skip


def stat_line(stats: Mapping[str, float], position: str) -> dict[str, float | str]:
    """One ESPN weekly stat line as our stat columns (used to check scoring against ESPN)."""
    s = {int(k): float(v) for k, v in stats.items()}
    row: dict[str, float | str] = {col: s.get(sid, 0.0) for sid, col in STAT_COLUMN.items()}
    row["def_td"] = sum(s.get(i, 0.0) for i in (103, 104, 93))
    row["def_st_td"] = sum(s.get(i, 0.0) for i in RETURN_TD)
    if position != "DEF":
        row["pts_allow"] = row["yds_allow"] = None  # type: ignore[assignment]
    row["position"] = position
    return row
