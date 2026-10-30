# Changelog

All notable changes to FantasyEdge. Dates are when the work was pushed.

## [Unreleased]

### Added
- **Accepted ESPN trades waiting to process.** ESPN holds an accepted trade for league review
  before the players move. My Team and the Bye-week planner now list those trades, and the
  planner's **After accepted trades** view shows each remaining week's lineup once they go
  through: the weakest weeks first, who's out and why, and the slots nobody can fill.
- **Advisor and My Team: Current roster | After accepted trades.** With pending ESPN trades, both
  pages can show everything as if they had gone through. The Advisor's moves, the team grades,
  needs and surplus, the roster (incoming players marked NEW), starter points and the regression
  list are all recomputed on the new rosters, the trade partner's included. Grades that change
  say what they were ("▲ was D · #8").
- **Week-by-week lineups on every trade card.** Opens both teams' lineups before and after the
  deal, with the same week grid as the Bye-week planner.
- An empty slot in the week grid names the starter it's missing ("for Kraft · bye").

### Fixed
- The sidebar shows a team's new name after it is renamed on ESPN or Sleeper. It used to keep
  the name from when the team was first connected.
- Bye-week streaming suggestions and the waiver shortlist skip players who can't play that week
  (out for the season, or still on IR). A season-ending injury no longer gets a player
  recommended because of his old points per game.

## [0.3.0] — 2026-10-20

### Changed
- **Trades are fair by market value.** "Trade for X", "Shop him", Find a trade, Trade ideas and
  the Advisor only suggest deals where each side gets at least 85% of the value it gives up (a
  player at the other team's weak position counts 10% more to them). Deals grow to 3 players, or
  pick up a small throw-in, to even the values out; waiver filler never balances a star. When
  nothing is fair, you see how close your best package gets. No more "a backup receiver for a
  top-5 WR".
- Trade cards say why a team would likely say no: **Below their value**, **You overpay**, or
  **Doesn't help their lineup**, instead of one "Unlikely to accept" for everything.
- **Bye-week planner:** only bye and injury changes are colored (amber: a backup fills in, with
  who he replaces; red: nobody can fill the slot). Week headers show the points lost, and weeks
  with no change are tucked behind "Show all weeks".

### Added
- Settings **Trade: fair value band** (default 0.15) and **Trade: need bonus** (default 0.10),
  under "Advisor & trades".
- API: trades include `fair_value` and `market_gap`; Find a trade returns `message` when nothing
  is fair; bye cells include `replaces`, `why` and `hole`, and weeks include `points_lost`.

## [0.2.1] — 2026-10-18

Fixes from a code review of forced drops (F1–F9). Details: `docs/fix-summary-review-findings.md`.

### Fixed
- **"Free to drop" now depends on weeks left.** A bench player is free to cut when he costs your
  lineup less than 0.5 points per remaining week, instead of a fixed 5 points for the rest of the
  season. Late in the season, starters no longer look free; early on, bench filler no longer looks
  costly. This week's starters are never free.
- **A missing market price no longer counts as 0.** An unpriced player (a rookie, a kicker) is
  compared by our own projection, and the reason says so. If the whole league has no market
  values, drops go by lineup cost, and the trade card shows "Market values unavailable; drops
  based on projections only."
- **Flex slots count once.** Surplus depth used to count every flex slot for every position it
  accepts, so a superflex league never showed a surplus. Each flex now counts for the player the
  lineup puts there.
- Players on IR are never dropped (now tested).
- README screenshots wait for the page's own content, not the sidebar, and fail with a clear
  message when the demo league has no regression rows.

### Added
- Settings **Bench backups per position** (default 1) and **Free to drop under** (default 0.5
  pts/week), under "Advisor & trades".

### Changed
- **API:** a trade side's `drops` is now a list of `{player, reason}`, and `drop_reasons` is gone.
  Trade responses add `market_values_missing`.

## [0.2.0] — 2026-10-18

### Added
- **ESPN leagues**, including private ones (your `espn_s2` / `SWID` cookies stay on your computer).
  ESPN scoring is converted exactly, including per-position rules and D/ST brackets.
- **Players page:** every player, searchable, filterable by position, NFL team and who owns him,
  and sortable by projection, rest-of-season points, value, market value or verdict. Filters live
  in the URL.
- **Waivers page:** free agents ranked by how much they'd add to your lineup for the rest of the
  season, after dropping the player you'd miss least. It also suggests a FAAB bid range (formula
  shown and tunable in Settings) and shows Sleeper's trending adds.
- **Start/Sit planner:** this week's best lineup vs your real one, plus a drag-and-drop board that
  allows only valid moves. It has undo/redo, "Reset to my real lineup" and "Copy lineup". It never
  changes your lineup on ESPN or Sleeper.
- **Trades:**
  - Roster spots and both teams' bye weeks are counted.
  - "Show different ideas" gives a fresh set.
  - **Find a trade** ("these players for a running back").
  - Trades built around any player from his page.
- **Saved teams and a team switcher** in the sidebar, with rename (manual teams) and
  delete/forget. The last team you used is remembered.
- **Injury what-ifs:** on any player's page, mark him "Out for the season" or "Back in week N".
  This changes FantasyEdge's projections only.
- **Rankings:** top 10, 15, 20 or 30 per position.
- **Demo league** (`python tasks.py demo`) and browser tests (`python tasks.py e2e`, run in CI).

### Changed
- This week's lineup advice (My Team, Advisor, Start/Sit) uses matchup-adjusted projections, so all
  three agree. Starters whose game is already final stay locked in their slot.
- Forced drops (trades and Waivers) now cut who a manager would: an extra K or D/ST first, then
  surplus depth at an over-stocked position (e.g. a 4th QB), then the bench player with the
  lowest market value. Each drop says why, so a valuable bench player is no longer cut ahead of
  waiver fodder.
- Rosters refresh themselves when a team is loaded and its saved copy is over 10 minutes old.
- **Regression report:** the 20 strongest flags first, then "Show more". It adds position,
  direction and team filters, a filter bar that stays visible while you scroll, and a back-to-top
  button.
- The README is now a short guide for fantasy players.

### Fixed
- **Season-ending injuries:** a player on IR with a torn ACL or Achilles (from Sleeper's injury
  details) is out for the season, not "back in 4 weeks". He no longer tops Waivers.
- **Bye weeks:** players on bye no longer appear in this week's best lineup.
- **Phones:** the sidebar now closes after you tap a link or switch teams, so the page underneath
  scrolls again. Escape closes it too.

## [0.1.0] — 2026-10-12

First public release:
- Sleeper and manual leagues; Advisor, My Team, Byes, Rankings, Buy targets, player pages with
  analytics, Trade analyzer, Settings.
- Backtest-tuned projections, schedule adjustment, one buy/hold/sell verdict per player, and
  regression flags.
