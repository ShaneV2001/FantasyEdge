"""User-adjustable model weights and thresholds, stored in data/settings.json.

Defaults are the values the app was tuned with (projection fields by the walk-forward backtest).
The file holds only values that differ from the defaults, so improved defaults still reach users
who never touched a field. A broken file never breaks the app: it falls back to the defaults with
a warning that the Settings page shows.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from projections.base import IR_WEEKS_MISSED, STATUS_THIS_WEEK, InjuryAssumptions
from projections.baseline import SHRINK_GAMES, W_USAGE
from signals import advisor, trade, waivers
from signals.schedule import MATCHUP_ALPHA
from signals.targets import TOP_N
from signals.verdict import GAP_MIN_POINTS, GAP_MIN_SHARE, STARTABLE_RANK

PROJ, VERDICT, INJ, ADV = "Projections", "Buy/sell & targets", "Injuries", "Advisor & trades"
WAIV = "Waivers & FAAB"
GROUPS = (PROJ, VERDICT, INJ, ADV, WAIV)


def _f(default, lo, hi, group: str, label: str, help: str, tuned: bool = False):  # noqa: A002
    return Field(
        default, ge=lo, le=hi, title=label, description=help,
        json_schema_extra={"group": group, "tuned": tuned},
    )  # fmt: skip


def _alpha(pos: str):
    return _f(
        MATCHUP_ALPHA[pos], 0, 1.5, PROJ, f"{pos} matchup strength",
        f"How much an easy or hard opponent moves a {pos}'s weekly projection (0 = ignore matchups).",
        tuned=True,
    )  # fmt: skip


def _startable(pos: str):
    return _f(
        STARTABLE_RANK[pos], 1, 100, VERDICT, f"{pos} startable depth",
        f"Only {pos}s we rank this high or better can be a buy (and only ones the market ranks this "
        "high can be a sell). Deeper players are always a hold.",
    )  # fmt: skip


class UserSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    usage_weight: float = _f(
        W_USAGE, 0, 1, PROJ, "Usage weight",
        "Share of a projection from usage (targets, carries, snaps); the rest is season scoring rate.",
        tuned=True,
    )  # fmt: skip
    shrink_games: int = _f(
        SHRINK_GAMES, 0, 17, PROJ, "Early-season shrink (games)",
        "How many games of last season this season's scoring rate is blended with. Higher = trust "
        "this season less early on.",
        tuned=True,
    )  # fmt: skip
    matchup_alpha_qb: float = _alpha("QB")
    matchup_alpha_rb: float = _alpha("RB")
    matchup_alpha_wr: float = _alpha("WR")
    matchup_alpha_te: float = _alpha("TE")
    matchup_alpha_k: float = _alpha("K")
    matchup_alpha_def: float = _alpha("DEF")

    gap_min_points: float = _f(
        GAP_MIN_POINTS, 0, 50, VERDICT, "Buy/sell gap (points)",
        "Minimum rest-of-season points between our projection and the market's price for a buy or sell.",
    )  # fmt: skip
    gap_min_share: float = _f(
        GAP_MIN_SHARE, 0, 0.5, VERDICT, "Buy/sell gap (share)",
        "Or this share of the market's price, whichever is larger (0.10 = 10%).",
    )  # fmt: skip
    startable_qb: int = _startable("QB")
    startable_rb: int = _startable("RB")
    startable_wr: int = _startable("WR")
    startable_te: int = _startable("TE")
    targets_per_tier: int = _f(
        TOP_N, 3, 25, VERDICT, "Buy targets per tier",
        "How many players the Buy targets page lists in each tier (starters, bench depth).",
    )  # fmt: skip

    play_chance_questionable: float = _f(
        STATUS_THIS_WEEK["Questionable"], 0, 1, INJ, "Questionable: chance he plays",
        "This week's projection for a Questionable player is multiplied by this.",
    )  # fmt: skip
    play_chance_doubtful: float = _f(
        STATUS_THIS_WEEK["Doubtful"], 0, 1, INJ, "Doubtful: chance he plays",
        "This week's projection for a Doubtful player is multiplied by this.",
    )  # fmt: skip
    ir_weeks_out: int = _f(
        IR_WEEKS_MISSED, 0, 17, INJ, "Weeks out on IR / PUP",
        "Weeks a player on IR, PUP or NFI is assumed to miss when there's no return date.",
    )  # fmt: skip

    waiver_min_gain: float = _f(
        advisor.WAIVER_MIN_GAIN, 0, 10, ADV, "Waiver pickup: minimum gain (pts/week)",
        "The Advisor suggests a free agent only if adding him (after the drop) raises your starting "
        "lineup by at least this many points per week for the rest of the season.",
    )  # fmt: skip
    start_sit_min_gain: float = _f(
        advisor.START_SIT_MIN_GAIN, 0, 10, ADV, "Start/sit: minimum gain (pts)",
        "Suggest a lineup swap only if it gains at least this many projected points this week.",
    )  # fmt: skip
    easy_schedule: float = _f(
        advisor.EASY_SCHEDULE, 1.0, 1.3, ADV, "Easy schedule cutoff",
        "Opponent index at or above this counts as an easy schedule (1.08 = 8% easier than average).",
    )  # fmt: skip
    tough_schedule: float = _f(
        advisor.TOUGH_SCHEDULE, 0.7, 1.0, ADV, "Tough schedule cutoff",
        "Opponent index at or below this counts as a tough schedule (0.92 = 8% harder than average).",
    )  # fmt: skip
    trade_accept_gain: float = _f(
        trade.ACCEPT_GAIN, 0, 50, ADV, "Trade: accept at (pts)",
        "A trade is an accept when your starting lineup gains at least this many ROS points.",
    )  # fmt: skip
    trade_lean_gain: float = _f(
        trade.LEAN_GAIN, 0, 50, ADV, "Trade: lean accept at (pts)",
        "Gains between this and the accept line are a lean accept; losses beyond it are a decline.",
    )  # fmt: skip

    faab_full_gain: float = _f(
        waivers.FAAB_FULL_GAIN, 5, 200, WAIV, "FAAB: gain worth a full bid (pts)",
        "Net rest-of-season lineup points at which a pickup gets the full aggression share of your "
        "remaining budget. Smaller gains get a proportional share.",
    )  # fmt: skip
    faab_aggression: float = _f(
        waivers.FAAB_AGGRESSION, 0.05, 1, WAIV, "FAAB: aggression",
        "Share of your remaining budget to bid on a pickup worth the full-bid gain or more "
        "(0.5 = half of what's left).",
    )  # fmt: skip
    faab_min_bid: int = _f(
        waivers.FAAB_MIN_BID, 0, 20, WAIV, "FAAB: minimum bid ($)",
        "Never suggest less than this for a pickup that helps your lineup.",
    )  # fmt: skip

    @model_validator(mode="after")
    def _lean_below_accept(self) -> UserSettings:
        if self.trade_lean_gain > self.trade_accept_gain:
            raise ValueError("trade_lean_gain must be at most trade_accept_gain")
        return self

    @property
    def alpha(self) -> dict[str, float]:
        return {
            "QB": self.matchup_alpha_qb, "RB": self.matchup_alpha_rb, "WR": self.matchup_alpha_wr,
            "TE": self.matchup_alpha_te, "K": self.matchup_alpha_k, "DEF": self.matchup_alpha_def,
        }  # fmt: skip

    @property
    def startable(self) -> dict[str, int]:
        return STARTABLE_RANK | {
            "QB": self.startable_qb, "RB": self.startable_rb,
            "WR": self.startable_wr, "TE": self.startable_te,
        }  # fmt: skip

    @property
    def injury(self) -> InjuryAssumptions:
        return InjuryAssumptions(
            self.play_chance_questionable, self.play_chance_doubtful, self.ir_weeks_out
        )

    def fingerprint(self) -> str:
        return self.model_dump_json()


def describe_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        e = exc.errors()[0]
        where = ".".join(str(x) for x in e["loc"]) or "settings"
        return f"{where}: {e['msg']}"
    return str(exc)


def load(path: Path) -> tuple[UserSettings, str | None]:
    if not path.exists():
        return UserSettings(), None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"{path.name} must contain a JSON object")
        return UserSettings.model_validate(raw), None
    except (OSError, ValueError) as exc:  # JSONDecodeError and ValidationError are ValueErrors
        return UserSettings(), (
            f"{path.name} couldn't be used ({describe_error(exc)}). Using defaults; "
            "saving will replace the file."
        )


def save(path: Path, s: UserSettings) -> None:
    """Write only non-default values, atomically (temp file + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(s.model_dump(exclude_defaults=True), f, indent=2, sort_keys=True)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def apply(current: UserSettings, changes: Mapping[str, float]) -> UserSettings:
    unknown = sorted(set(changes) - set(UserSettings.model_fields))
    if unknown:
        raise ValueError(f"unknown setting: {', '.join(unknown)}")
    return UserSettings.model_validate(current.model_dump() | dict(changes))


def _bound(info, attr: str) -> float:
    return next(getattr(m, attr) for m in info.metadata if hasattr(m, attr))


def field_schema(s: UserSettings) -> list[dict]:
    out = []
    for key, info in UserSettings.model_fields.items():
        extra = info.json_schema_extra or {}
        out.append(
            {
                "key": key,
                "group": extra["group"],
                "label": info.title,
                "help": info.description,
                "default": info.default,
                "min": _bound(info, "ge"),
                "max": _bound(info, "le"),
                "integer": info.annotation is int,
                "tuned": bool(extra.get("tuned")),
                "value": getattr(s, key),
            }
        )
    return out
