import polars as pl

from signals.byes import RosterEntry, bye_grid, bye_overlap
from signals.schedule import build_schedule
from tests.builders import schedule

SLOTS = ["QB", "RB", "WR", "TE", "FLEX"]
VIABLE = {"QB": 12.0, "RB": 7.0, "WR": 7.0, "TE": 5.0}


def _roster():
    return [
        RosterEntry("qb1", "QB One", "QB", "AAA", 20),
        RosterEntry("rb1", "RB One", "RB", "AAA", 15),
        RosterEntry("rb2", "RB Two", "RB", "CCC", 9),
        RosterEntry("wr1", "WR One", "WR", "BBB", 14),
        RosterEntry("wr2", "WR Two", "WR", "BBB", 10),
        RosterEntry("te1", "TE One", "TE", "CCC", 8),
    ]


def test_bye_derived_from_missing_schedule_week():
    games = pl.DataFrame(
        {
            "season": [2026] * 3,
            "week": [1, 2, 3],
            "home_team": ["AAA", "AAA", "BBB"],
            "away_team": ["BBB", "CCC", "CCC"],
            "home_score": [10, None, None],
        }
    )
    s = build_schedule(games, 2026)
    assert s.byes == {"AAA": 3, "BBB": 2, "CCC": 1}
    assert not s.plays("AAA", 1) and s.has_game("AAA", 1)  # week 1 already final
    assert s.plays("AAA", 2)


def test_bye_week_creates_danger_with_weeks_away():
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10, byes={"AAA": 7, "BBB": 9, "CCC": 4})
    rows = {r.week: r for r in bye_grid(_roster(), SLOTS, sched, 5, 10, VIABLE)}

    assert not rows[5].danger
    wk7 = rows[7]  # QB + RB1 on bye: QB slot empty → danger
    assert wk7.danger and "QB" in wk7.danger_slots
    assert wk7.weeks_away == 2
    assert set(wk7.starters_on_bye) == {"QB One", "RB One"}
    qb_cell = next(c for c in wk7.cells if c.slot == "QB")
    assert qb_cell.status == "empty"
    assert wk7.lineup_points < wk7.full_strength_points


def test_flex_absorbs_bye_without_danger():
    # WR bye: RB2 slides from FLEX to... WR slot can't take RB → WR slot empty → danger
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10, byes={"BBB": 6})
    wk6 = next(r for r in bye_grid(_roster(), SLOTS, sched, 5, 10, VIABLE) if r.week == 6)
    assert "WR" in wk6.danger_slots
    # with a third WR on another team, the WR bye is covered
    roster = [*_roster(), RosterEntry("wr3", "WR Three", "WR", "AAA", 8)]
    wk6b = next(r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE) if r.week == 6)
    assert not wk6b.danger


def test_thin_replacement_is_flagged():
    roster = [*_roster(), RosterEntry("te2", "TE Two", "TE", "AAA", 2.0)]  # below viable 5.0
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10, byes={"CCC": 8})
    wk8 = next(r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE) if r.week == 8)
    te = next(c for c in wk8.cells if c.slot == "TE")
    assert te.status == "thin" and te.name == "TE Two"
    assert "TE" in wk8.danger_slots


def test_injured_out_player_counts_as_hole_this_week_only():
    roster = _roster()
    roster[0] = RosterEntry("qb1", "QB One", "QB", "AAA", 20, injury_status="Out")
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10)
    rows = {r.week: r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE)}
    assert rows[5].danger and not rows[6].danger


def test_bye_overlap_counts_only_upcoming():
    assert bye_overlap([7, 7, 9, None], 7, start_week=5) == 2
    assert bye_overlap([7, 7], 4, start_week=5) == 0
    assert bye_overlap([7], None, start_week=5) == 0


def test_fill_ins_name_who_they_replace_and_why():
    roster = [*_roster(), RosterEntry("te2", "TE Two", "TE", "AAA", 2.0)]
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10, byes={"CCC": 8})
    rows = {r.week: r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE)}
    te = next(c for c in rows[8].cells if c.slot == "TE")
    assert (te.name, te.replaces, te.why, te.hole) == ("TE Two", "TE One", "bye", False)
    # a normal week changes nothing, however weak a starter is
    assert all(c.replaces is None and not c.hole for c in rows[5].cells)


def test_an_injured_starter_shows_injury_as_the_reason():
    roster = [
        *_roster()[1:],
        RosterEntry("qb1", "QB One", "QB", "AAA", 20, injury_status="Out"),
        RosterEntry("qb2", "QB Two", "QB", "BBB", 14),
    ]
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10)
    wk5 = next(r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE) if r.week == 5)
    qb = next(c for c in wk5.cells if c.slot == "QB")
    assert (qb.name, qb.replaces, qb.why) == ("QB Two", "QB One", "injury")


def test_a_hole_is_only_a_slot_empty_this_week():
    sched = schedule(["AAA", "BBB", "CCC"], weeks=10, byes={"AAA": 7})
    rows = {r.week: r for r in bye_grid(_roster(), SLOTS, sched, 5, 10, VIABLE)}
    qb = next(c for c in rows[7].cells if c.slot == "QB")
    assert qb.status == "empty" and qb.hole  # QB One on bye, nobody else
    assert (qb.replaces, qb.why) == ("QB One", "bye")  # the hole says who it is missing
    # no TE on the roster at all: empty every week, but that's not a bye hole
    no_te = [e for e in _roster() if e.position != "TE"]
    rows = {r.week: r for r in bye_grid(no_te, SLOTS, sched, 5, 10, VIABLE)}
    te = next(c for c in rows[5].cells if c.slot == "TE")
    assert te.status == "empty" and not te.hole


def test_an_empty_slot_names_its_own_starter():
    """TE and two RBs out: the empty TE slot is the TE's, even though a WR filling the flex would
    otherwise be paired with the highest scorer still unaccounted for (the TE)."""
    roster = [
        RosterEntry("qb", "QB", "QB", "AAA", 20),
        RosterEntry("rb1", "RB One", "RB", "DDD", 15),
        RosterEntry("rb2", "RB Two", "RB", "DDD", 9),
        RosterEntry("rb3", "RB Three", "RB", "AAA", 6),
        RosterEntry("wr1", "WR One", "WR", "AAA", 14),
        RosterEntry("wr2", "WR Two", "WR", "AAA", 5),
        RosterEntry("te1", "TE One", "TE", "DDD", 10),
    ]
    sched = schedule(["AAA", "DDD"], weeks=10, byes={"DDD": 7})
    wk7 = next(r for r in bye_grid(roster, SLOTS, sched, 5, 10, VIABLE) if r.week == 7)
    cells = {c.slot: c for c in wk7.cells}
    assert cells["TE"].hole and cells["TE"].replaces == "TE One"
    assert (cells["RB"].name, cells["RB"].replaces) == ("RB Three", "RB One")
    assert (cells["FLEX"].name, cells["FLEX"].replaces) == ("WR Two", "RB Two")
