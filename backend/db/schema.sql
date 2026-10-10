-- ───────── Reference ─────────
CREATE TABLE IF NOT EXISTS players (
  player_id      VARCHAR PRIMARY KEY,   -- internal = nflverse gsis_id when available
  sleeper_id     VARCHAR UNIQUE,
  espn_id        VARCHAR,
  yahoo_id       VARCHAR,
  fantasycalc_id VARCHAR,
  full_name      VARCHAR NOT NULL,
  position       VARCHAR NOT NULL,      -- QB/RB/WR/TE/K/DEF
  nfl_team       VARCHAR,
  birth_date     DATE,
  years_exp      INTEGER,
  status         VARCHAR,               -- Active / IR / FA ...
  depth_chart_order INTEGER,
  injury_status  VARCHAR,               -- Sleeper injury_status: Questionable / Out / IR ...
  updated_at     TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nfl_games (
  game_id   VARCHAR PRIMARY KEY,
  season    INTEGER, week INTEGER,
  home_team VARCHAR, away_team VARCHAR,
  kickoff   TIMESTAMP,
  home_score INTEGER, away_score INTEGER
);

-- ───────── Raw stats (from nflverse) ─────────
CREATE TABLE IF NOT EXISTS player_week_stats (
  player_id VARCHAR, season INTEGER, week INTEGER,
  game_id VARCHAR, team VARCHAR, opponent VARCHAR,
  snaps INTEGER, snap_pct DOUBLE, routes INTEGER,
  pass_att INTEGER, pass_cmp INTEGER, pass_yds INTEGER, pass_td INTEGER, interceptions INTEGER,
  carries INTEGER, rush_yds INTEGER, rush_td INTEGER,
  targets INTEGER, receptions INTEGER, rec_yds INTEGER, rec_td INTEGER,
  air_yards INTEGER, target_share DOUBLE, air_yards_share DOUBLE, wopr DOUBLE,
  rz_carries INTEGER, rz_targets INTEGER, gl_carries INTEGER,
  rz_td INTEGER,                                   -- rushing+receiving TDs on red-zone plays
  fumbles_lost INTEGER, two_pt INTEGER,
  epa_total DOUBLE,
  PRIMARY KEY (player_id, season, week)
);

CREATE TABLE IF NOT EXISTS injuries (
  player_id VARCHAR, season INTEGER, week INTEGER,
  report_status VARCHAR,     -- Out / Doubtful / Questionable
  practice_status VARCHAR,   -- DNP / Limited / Full
  body_part VARCHAR,
  PRIMARY KEY (player_id, season, week)
);

-- ───────── Market (FantasyCalc / DynastyProcess) ─────────
CREATE TABLE IF NOT EXISTS market_values (
  player_id VARCHAR, source VARCHAR,           -- 'fantasycalc' | 'dynastyprocess'
  snapshot_date DATE,
  format VARCHAR,                              -- 'redraft_1qb_12_ppr1' etc.
  value DOUBLE, overall_rank INTEGER, position_rank INTEGER,
  trend_30d DOUBLE,
  PRIMARY KEY (player_id, source, snapshot_date, format)
);

CREATE TABLE IF NOT EXISTS trending (
  player_id VARCHAR, kind VARCHAR,             -- 'add' | 'drop'
  count INTEGER, lookback_hours INTEGER, fetched_at TIMESTAMP
);

-- ───────── Scoring ─────────
CREATE TABLE IF NOT EXISTS scoring_profiles (
  scoring_profile_id VARCHAR PRIMARY KEY,      -- hash of rules JSON
  name VARCHAR,                                -- 'Half PPR default', 'My Sleeper league'
  rules JSON                                   -- {"rec":0.5,"pass_td":4,...}
);

-- ───────── Features / ML ─────────
CREATE TABLE IF NOT EXISTS player_week_features (
  player_id VARCHAR, season INTEGER, week INTEGER,   -- features known BEFORE this week
  feature_version VARCHAR,
  features JSON,                                     -- or wide columns once stable
  target_next4_ppg DOUBLE,                           -- NULL for future weeks
  PRIMARY KEY (player_id, season, week, feature_version)
);

CREATE TABLE IF NOT EXISTS model_runs (
  run_id VARCHAR PRIMARY KEY,
  trained_at TIMESTAMP,
  model_version VARCHAR, feature_version VARCHAR,
  train_seasons VARCHAR, valid_season INTEGER,
  metrics JSON,                 -- MAE / Spearman by position + baselines
  feature_importance JSON,
  artifact_path VARCHAR,
  is_active BOOLEAN
);

CREATE TABLE IF NOT EXISTS projections (
  run_id VARCHAR, player_id VARCHAR, scoring_profile_id VARCHAR,
  season INTEGER, week INTEGER,
  proj_next4_ppg DOUBLE, p10 DOUBLE, p90 DOUBLE,
  proj_ros_points DOUBLE,
  ros_value_par DOUBLE,          -- points above replacement
  PRIMARY KEY (run_id, player_id, scoring_profile_id, season, week)
);

CREATE TABLE IF NOT EXISTS signals (
  player_id VARCHAR, scoring_profile_id VARCHAR, season INTEGER, week INTEGER,
  buy_sell_score DOUBLE,         -- -100 (sell) .. +100 (buy)
  market_gap DOUBLE, td_over_expected DOUBLE,
  usage_trend DOUBLE, efficiency_z DOUBLE, playoff_sos DOUBLE,
  reasons JSON,                  -- ["Usage up 3 straight weeks", ...]
  PRIMARY KEY (player_id, scoring_profile_id, season, week)
);

-- ───────── Leagues / "Add your team" ─────────
CREATE TABLE IF NOT EXISTS leagues (
  league_id VARCHAR PRIMARY KEY,               -- internal
  platform VARCHAR,                            -- 'sleeper' | 'espn' | 'yahoo' | 'manual'
  external_id VARCHAR, season INTEGER, name VARCHAR,
  num_teams INTEGER,
  roster_positions JSON,                       -- ["QB","RB","RB","WR","WR","TE","FLEX","BN",...]
  scoring_profile_id VARCHAR,
  trade_deadline_week INTEGER, uses_faab BOOLEAN, faab_budget INTEGER,
  playoff_week_start INTEGER,
  last_synced_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS teams (
  team_id VARCHAR PRIMARY KEY,
  league_id VARCHAR, external_roster_id VARCHAR,
  owner_name VARCHAR, team_name VARCHAR,
  is_mine BOOLEAN,
  wins INTEGER, losses INTEGER, points_for DOUBLE,
  faab_remaining INTEGER
);

CREATE TABLE IF NOT EXISTS roster_spots (
  team_id VARCHAR, player_id VARCHAR,
  slot VARCHAR,                                -- 'starter' | 'bench' | 'ir' | 'taxi'
  synced_at TIMESTAMP,
  PRIMARY KEY (team_id, player_id)
);

CREATE TABLE IF NOT EXISTS transactions (
  league_id VARCHAR, external_id VARCHAR, kind VARCHAR,  -- trade/waiver/free_agent
  week INTEGER, created_at TIMESTAMP,
  payload JSON,
  PRIMARY KEY (league_id, external_id)
);

CREATE TABLE IF NOT EXISTS saved_trades (
  trade_id VARCHAR PRIMARY KEY, league_id VARCHAR, created_at TIMESTAMP,
  give JSON, receive JSON, result JSON
);

-- ───────── Ops ─────────
CREATE TABLE IF NOT EXISTS sync_log (
  source VARCHAR PRIMARY KEY,                  -- 'sleeper_players' | 'nflverse' | 'market' | 'league:<id>'
  last_synced_at TIMESTAMP,
  status VARCHAR,                              -- 'ok' | 'stale' | 'error'
  detail VARCHAR
);
