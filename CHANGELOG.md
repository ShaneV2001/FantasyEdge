# Changelog

All notable changes to FantasyEdge. Dates are when the work was pushed.

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
