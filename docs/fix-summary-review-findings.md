# Review findings F1–F9: fix summary

## Overview

A code review found nine problems, most of them in how FantasyEdge picks the player a team must
drop when a trade or pickup overfills its roster. Those drops feed every trade score, so a wrong
drop made a trade look better or worse than it was. The fixes:

- "Free to drop" now depends on how many weeks are left, and a starter is never free.
- A player with no market price is no longer treated as worthless.
- Flex slots no longer hide surplus depth.
- Each drop now carries its own reason through the API.

Three smaller fixes make the README screenshots reliable and the drop code easier to follow. All
nine findings were checked by an independent reviewer that had not seen the implementation. It
re-ran each failure scenario, plus random-roster fuzzing, and marked every finding fixed.

## Findings

| # | Severity | Status | What changed | Tests added | Commit |
|---|---|---|---|---|---|
| F1 | High | Fixed | A bench player is free to drop when `ROS lineup cost / weeks left < free_drop_ppg` (new setting, default 0.5), not under a fixed 5 ROS points. This week's starters are never free. No weeks left is handled. | Week-16 starting FLEX not free; week-2 bench player under 0.5/week is free; same cost per week gives the same drop in weeks 2 and 16; bench WR covering 3 byes not free; the setting changes the cut; no weeks left | `de141f8` |
| F2 | High | Fixed | A missing price stays `None`. If anyone in the group has no price, the group is ranked by our own projection, and the reason says so. With no prices in the whole league, the market rule is skipped, and trade responses set `market_values_missing`, which the trade card shows as "Market values unavailable; drops based on projections only." | Unpriced rookie vs a WR priced at 300; unpriced surplus; no "market" in any reason when the league has no prices; IR player never dropped; API flag; two trade-card banner tests | `a4fbc5e` |
| F3 | High | Fixed | The API test's receiving team now has a full 16/16 roster, so a 1-for-2 forces exactly one drop. It checks the drop, its reason, the API field and the trade text. Added the opposite test (a roster with room drops nobody) and fixed the wrong comment. Checked that the test really guards the code: with the drop or reason wiring in `views.trade_out` removed, it fails. | `test_drops_come_with_reasons` (rewritten), `test_a_roster_with_room_drops_nobody` | `366f6fd`, `cf712e6` |
| F4 | Medium | Fixed | Capacity = dedicated slots + each flex slot once, for the position of the player this week's lineup puts there, + `bench_backups_per_position` (new setting, default 1) at QB/RB/WR/TE. | Superflex: 4 TEs and 6 RBs are a surplus; one flex counts for one position; an empty flex counts for nobody; end-to-end superflex drops | `785cfd7` |
| F9 | Medium | Fixed | One list of `Drop(player, reason)` replaces the parallel lists, and the `strict=False` zip is gone. The API, the trade card and the generated client changed in the same commit. | The trade text names every dropped player (a 1-for-3 forcing two drops) | `4054be2` |
| F6 | Medium | Fixed | The screenshot `settled()` helper only looks inside the page content, never the sidebar, and each page passes its own ready check. Byes waits for the "Bye-week planner" heading and `data-testid="bye-grid"`, then for no `aria-busy`. | Shown failing first: with the data held back, the old check matched the sidebar link. Screenshot suite passed 12/12 twice. | `53a9f7d` |
| F7 | Medium | Fixed | An empty regression list fails at once with "Demo league produced no regression rows; check demo data or filters." `nth()` never gets a negative index. | Shown failing first against an emptied API (it hung until the timeout); now fails in about 2 s with that message | `3d0e494` |
| F5 | Low | Fixed | `SKILL_POSITIONS` is defined once, in `signals/lineup.py`. `trade.py` and `views.py` import it, and the copies are gone. | `test_trade_spells_the_skill_positions_once` | `197df5d`, `e476cab` |
| F8 | Low | Fixed | The drop is chosen in explicit, commented passes. Each candidate is a `DropCandidate(player, rule, reason)`. | `test_drop_order_is_pinned` (8 rosters), passing unchanged before and after the rewrite; a fuzz over 3,000 random rosters found no difference | `f976058` |

Per the approved plan, F8's passes keep today's behaviour where it differs from the outline:

- A cut that costs nothing goes before one that costs points. So a free surplus player goes before
  a kicker or defense that still scores you points.
- A "cheapest bench player by value" pass sits between dead weight and "costs your lineup the
  least".

## What changes in the advice

These changes come from the demo league (week 6; the lineup is 2 RB, 2 WR, 1 TE and 1 FLEX). We
compared 27 hand-built trades, 3 pages of trade ideas, a "find a trade" search and the Advisor,
before and after the fixes. Re-running the old code reproduced the saved baseline exactly, so
every change below comes from the fixes. 19 drops changed:

- **Your side, 1-for-2 trades** (10 evaluated trades giving Jordan Mason, and 2 trade ideas
  giving Luther Burden). Before, Stefon Diggs was cut as the "6th WR", or T.J. Hockenson as the
  "lowest market value on your bench". Now Brian Robinson is cut, as the "4th RB" or "5th RB, more
  than your lineup can use". **F4:** the old rule counted the flex for every position and kept 2
  backups, so the roster could hold 5 RBs. This week the flex goes to a WR, so it now holds 3 RBs
  (2 starters plus 1 backup).
- **Your side, Luther Burden for Emanuel Wilson + Dalton Kincaid.** T.J. Hockenson is still the
  cut, but the reason is now "3rd TE, more than your lineup can use", not "lowest market value"
  (F4).
- **The other team's side** (3 trades, F4). Tyler Allgeier ("6th RB") is now Xavier Worthy ("5th
  WR"), and TreVeyon Henderson ("6th RB") is now Roman Wilson ("4th WR"). In one trade idea, Mike
  Washington ("lowest market value") became Emanuel Wilson ("5th RB"). RB capacity fell from 5 to
  3. These cuts cost the partner less, so their side of the deal looks up to 4 points better rest
  of season.
- **Jaylen Waddle is cut instead of Wan'Dale Robinson or Alvin Kamara** (3 trades; F4, then F1).
  After F4, the partner's surplus is at WR, not RB. Both Waddle and Wan'Dale Robinson are surplus
  WRs, but Wan'Dale Robinson starts this week, so under F1 he is not free to drop. Waddle is on the
  bench and costs the lineup 0.2 points a week. In two other trades, F4 alone had moved the cut to
  Romeo Doubs ("4th WR"). Under F1 he isn't free to drop, so the cut went back to Zach Charbonnet
  ("7th RB"), as on `main`.

F2, F3, F5, F8 and F9 changed no advice for the demo league. It has market prices for every
QB/RB/WR/TE, and those findings fix edge cases, tests or code structure. The Advisor's one
trade-based action changed with its trade (the Mike Washington case above). Nothing else in the
Advisor changed.

## New settings

Both are under **Settings → Advisor & trades**, with a description and a reset.

| Setting | Default | Range | Meaning |
|---|---|---|---|
| Bench backups per position (`bench_backups_per_position`) | 1 | 0–5 | Bench depth kept per QB/RB/WR/TE before extra players count as surplus. Kickers and defenses never count as backups. |
| Free to drop under (`free_drop_ppg`) | 0.5 pts/week | 0–5 | A bench player is free to cut when losing him costs the starting lineup less than this per remaining week, byes he covers included. |

## API change

- `TradeSideOut.drops` is now a list of `{player: PlayerRef, reason: string}` (`DropOut`).
- `TradeSideOut.drop_reasons` is removed.
- `TradeOut.market_values_missing: boolean` is new. It is true when nobody in the league has a
  market value.

The frontend and the generated client (`frontend/src/api`) were updated in the same commit.

## Leftovers and open questions

- **A starter can't be the surplus cut.** As a result, a more valuable bench player can go instead
  of a cheaper one who starts this week. In the demo, Waddle (market value 1260) goes instead of
  Wan'Dale Robinson (525). This is the approved F1 rule; worth a look if it feels wrong in your
  league.
- **Fewer backups by default.** `main` kept 2 backups at RB and WR; the new default is 1 for every
  skill position. More rosters will show a surplus at RB/WR. Set "Bench backups per position" to 2
  for the old feel.
- **Drop reason wording** (low). When anyone on the bench lacks a price, the whole bench is
  ranked by projection. A priced player can then be cut with "(our projection; no market price)",
  which reads as if he has no price. A clearer wording would be "not everyone on your bench has a
  market price"; changing it means updating the pinned tests.
- **Kickers and defenses never have market prices** (low). The market feed only covers QB to TE.
  So a non-starting kicker or defense counted as free would switch the bench to projection
  ranking. This is very unlikely, since it needs a lone K/DEF on bye who still costs under 0.5 a
  week. A fix would be to leave K/DEF out of the "everyone has a price" check.
- **The Waivers page doesn't show the no-market-values banner.** Its drop reasons already name the
  projection rule.
- `DropCandidate.rule` labels each pass but isn't read yet.
- Other hand-written QB/RB/WR/TE lists remain, outside F5's three named locations:
  `views.py` (regression filters), `advisor.py`, `ingest/market_values.py` and
  `ingest/nflverse.py`.
- **README screenshots were not retaken.** The drop shown in `trade-finder.png` and
  `player-trades.png` may differ from today's output. Retake them with `python tasks.py demo`, then
  `python tasks.py screenshots`.
