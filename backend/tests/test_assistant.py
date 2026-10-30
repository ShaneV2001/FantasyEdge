"""The Claude advisor chat, with a scripted fake Anthropic client (no network, no cost)."""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import replace
from types import SimpleNamespace

import pytest
from anthropic.types.beta import BetaTextBlock, BetaThinkingBlock, BetaToolUseBlock

from app import deps
from app.config import get_settings
from app.main import app
from app.services import context
from app.services.assistant import chat
from app.services.assistant import tools as at
from tests.test_api import LEAGUE, client, connect_and_pick  # noqa: F401  (fixture)

# ───────── a fake Anthropic client ─────────


def text(t):
    return BetaTextBlock.model_validate({"type": "text", "text": t})


def use(name, args, tid="tu1"):
    return BetaToolUseBlock.model_validate(
        {"type": "tool_use", "id": tid, "name": name, "input": args}
    )


def thinking():
    return BetaThinkingBlock.model_validate({"type": "thinking", "thinking": "", "signature": "s"})


class FakeStream:
    def __init__(self, blocks, stop):
        self.blocks, self.stop = blocks, stop

    def __iter__(self):
        for b in self.blocks:
            if b.type == "tool_use":
                yield SimpleNamespace(type="content_block_start", content_block=b)
            elif b.type == "text":
                yield SimpleNamespace(type="text", text=b.text)

    def get_final_message(self):
        usage = SimpleNamespace(input_tokens=1000, output_tokens=50, cache_read_input_tokens=800,
                                cache_creation_input_tokens=0)  # fmt: skip
        return SimpleNamespace(content=self.blocks, stop_reason=self.stop, usage=usage)


class FakeAnthropic:
    """Answers each request with the next scripted turn and records what it was sent."""

    def __init__(self, turns):
        self.turns, self.requests = list(turns), []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))

    @contextmanager
    def _stream(self, **kw):
        self.requests.append(json.loads(json.dumps(kw, default=str)))
        blocks, stop = self.turns.pop(0)
        yield FakeStream(blocks, stop)


def events(body: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in chunk.splitlines())
        out.append((lines["event"], json.loads(lines["data"])))
    return out


@pytest.fixture
def ai(client):  # noqa: F811
    """The API client with a fake Anthropic client and a key configured."""
    fake = FakeAnthropic([])
    settings = replace(get_settings(), anthropic_api_key="test-key", ai_max_steps=3)
    app.dependency_overrides[deps.get_ai] = lambda: fake
    app.dependency_overrides[deps.get_ai_settings] = lambda: settings
    yield client[0], fake
    app.dependency_overrides.pop(deps.get_ai, None)
    app.dependency_overrides.pop(deps.get_ai_settings, None)


# ───────── the chat over HTTP ─────────


def test_an_answer_runs_tools_streams_text_and_is_stored(ai):
    tc, fake = ai
    team_id = connect_and_pick(tc)
    fake.turns = [
        ([thinking(), text("Let me check."), use("my_team", {})], "tool_use"),
        ([text("Start your RB1.")], "end_turn"),
    ]
    r = tc.post(f"/team/{team_id}/chat", json={"message": "Who should I start?"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    ev = events(r.text)
    kinds = [k for k, _ in ev]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    assert ("tool", {"name": "my_team", "label": "Reading your roster", "status": "start"}) in ev
    assert ("tool", {"name": "my_team", "status": "done"}) in ev
    assert "".join(d["text"] for k, d in ev if k == "text") == "Let me check.Start your RB1."
    done = ev[-1][1]
    assert done["stop_reason"] == "end_turn" and done["usage"]["input_tokens"] == 2000
    assert done["usage"]["cost_usd"] > 0  # the default model has a price

    first, second = fake.requests
    assert first["model"] == "claude-opus-5-5" and first["fallbacks"] == "default"
    assert first["thinking"] == {"type": "adaptive"} and first["system"][0]["cache_control"]
    assert [t["name"] for t in first["tools"]] == [t.name for t in at.TOOLS]
    # the user's words, then the day's facts as a system message after them
    assert [m["role"] for m in first["messages"]] == ["user", "system"]
    assert "NFL week" in first["messages"][1]["content"]
    # the tool result went back with the thinking block replayed untouched
    assistant, results = second["messages"][2], second["messages"][3]
    assert assistant["content"][0] == {"type": "thinking", "thinking": "", "signature": "s"}
    (res,) = results["content"]
    assert res["type"] == "tool_result" and res["tool_use_id"] == "tu1" and not res["is_error"]
    roster = json.loads(res["content"])
    assert roster["team_id"] == team_id and roster["roster"] and "owner_name" not in res["content"]

    cid = ev[0][1]["conversation_id"]
    (summary,) = tc.get(f"/team/{team_id}/chats").json()
    assert summary["id"] == cid and summary["title"] == "Who should I start?"
    convo = tc.get(f"/chats/{cid}").json()
    assert convo["messages"] == [
        {"role": "user", "text": "Who should I start?", "tools": []},
        {"role": "assistant", "text": "Let me check.Start your RB1.", "tools": ["my_team"]},
    ]
    assert convo["usage"]["output_tokens"] == 100 and convo["usage"]["cache_read_tokens"] == 1600

    # a follow-up replays the history; the facts aren't repeated while they haven't changed
    fake.turns = [([text("Yes.")], "end_turn")]
    r = tc.post(f"/team/{team_id}/chat", json={"message": "Sure?", "conversation_id": cid})
    msgs = fake.requests[-1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "system", "assistant", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "Sure?"
    assert tc.delete(f"/chats/{cid}").json() == {"deleted": cid}
    assert tc.get(f"/chats/{cid}").status_code == 404


def test_tool_errors_go_back_to_the_model_and_steps_are_capped(ai):
    tc, fake = ai
    team_id = connect_and_pick(tc)
    fake.turns = [
        ([use("player", {"name": "Nobody Atall"})], "tool_use"),
        ([use("start_sit", {"week": 99})], "tool_use"),
        ([use("my_team", {})], "tool_use"),
        ([text("Here's what I found.")], "end_turn"),
    ]
    ev = events(tc.post(f"/team/{team_id}/chat", json={"message": "Tell me"}).text)
    assert ("tool", {"name": "player", "status": "error"}) in ev
    assert ("tool", {"name": "start_sit", "status": "error"}) in ev
    second, third, last = fake.requests[1], fake.requests[2], fake.requests[3]
    err = second["messages"][-1]["content"][0]
    assert err["is_error"] and "No player named" in err["content"]
    assert third["messages"][-1]["content"][0]["is_error"]  # week 99 fails validation
    assert "tool_choice" not in third and last["tool_choice"] == {"type": "none"}  # 3 steps max


def test_refusal_and_api_errors_end_the_answer_cleanly(ai):
    import anthropic
    import httpx

    tc, fake = ai
    team_id = connect_and_pick(tc)
    fake.turns = [([text("I can't")], "refusal")]
    ev = events(tc.post(f"/team/{team_id}/chat", json={"message": "x"}).text)
    assert ("error", {"message": "Claude declined to answer that."}) in ev and ev[-1][0] == "done"

    def boom(**kw):
        resp = httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com"))
        raise anthropic.AuthenticationError("bad key", response=resp, body=None)

    fake.beta.messages.stream = boom
    ev = events(tc.post(f"/team/{team_id}/chat", json={"message": "y"}).text)
    assert ev[1] == ("error", {"message": "Anthropic rejected the ANTHROPIC_API_KEY in .env."})


def test_without_a_key_the_chat_says_how_to_turn_it_on(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    app.dependency_overrides[deps.get_ai] = lambda: None
    try:
        r = tc.post(f"/team/{team_id}/chat", json={"message": "hi"})
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
        assert tc.get("/meta/status").json()["ai_enabled"] is False
    finally:
        app.dependency_overrides.pop(deps.get_ai, None)


def test_status_reports_the_chat_model(ai):
    tc, _ = ai
    s = tc.get("/meta/status").json()
    assert s["ai_enabled"] and s["ai_model"] == "claude-opus-5-5"


def test_a_conversation_belongs_to_its_team(ai):
    tc, fake = ai
    team_id = connect_and_pick(tc)
    fake.turns = [([text("ok")], "end_turn")]
    cid = events(tc.post(f"/team/{team_id}/chat", json={"message": "a"}).text)[0][1][
        "conversation_id"
    ]
    other = f"sl-{LEAGUE}-2" if not team_id.endswith("-2") else f"sl-{LEAGUE}-3"
    r = tc.post(f"/team/{other}/chat", json={"message": "b", "conversation_id": cid})
    assert r.status_code == 404


# ───────── every tool on a real league ─────────


def test_every_tool_runs_and_fits(client):  # noqa: F811
    tc, _ = client
    team_id = connect_and_pick(tc)
    ctx = context.get_context(deps._con, f"sl-{LEAGUE}")
    mine = ctx.team(team_id).player_ids
    other = next(t for t in ctx.teams if t.team_id != team_id).player_ids
    name = lambda pid: ctx.players[pid]["name"]  # noqa: E731
    skill = lambda ids: next(p for p in ids if ctx.players[p]["position"] in ("RB", "WR"))  # noqa: E731
    args = {
        "player": {"name": name(mine[0])},
        "search_players": {"query": name(mine[0]).split()[-1]},
        "evaluate_trade": {"give": [name(skill(mine))], "receive": [name(skill(other))]},
        "find_trade": {"give": [name(skill(mine))], "want_position": "WR"},
    }
    env = at.ToolEnv(ctx, deps._con.cursor(), team_id)
    for tool in at.TOOLS:
        out, is_error = at.run_tool(env, tool.name, args.get(tool.name, {}))
        assert not is_error, (tool.name, out)
        assert len(out) <= at.MAX_CHARS and json.loads(out)
        assert "owner_name" not in out and "headshot_url" not in out
        assert tool.schema()["input_schema"]["additionalProperties"] is False


# ───────── pieces ─────────


def _ctx(players, rostered=()):
    return SimpleNamespace(players=players, rostered=set(rostered))


def test_names_resolve_like_the_player_search():
    players = {
        "a": {"name": "Josh Allen", "position": "QB", "nfl_team": "BUF", "ppg": 24},
        "b": {"name": "Josh Allen", "position": "LB", "nfl_team": "JAX", "ppg": 0},
        "c": {"name": "Keenan Allen", "position": "WR", "nfl_team": "LAC", "ppg": 12},
        "d": {"name": "Amon-Ra St. Brown", "position": "WR", "nfl_team": "DET", "ppg": 18},
        "e": {"name": "José Bárcenas", "position": "RB", "nfl_team": "NYJ", "ppg": 3},
    }
    assert at.resolve(_ctx(players), "amon-ra st. brown") == "d"
    assert at.resolve(_ctx(players), "jose barcenas") == "e"  # accents ignored
    with pytest.raises(at.ToolError, match="matches several"):
        at.resolve(_ctx(players), "Josh Allen")  # two exact matches, neither rostered
    assert at.resolve(_ctx(players, rostered={"a"}), "Josh Allen") == "a"
    with pytest.raises(at.ToolError, match="matches several"):
        at.resolve(_ctx(players), "Allen")
    assert at.resolve(_ctx(players), "Allen", mine=frozenset({"c"})) == "c"
    with pytest.raises(at.ToolError, match="No player named"):
        at.resolve(_ctx(players), "Nobody")


def test_render_trims_lists_and_drops_noise():
    big = {"owner_name": "Real Person", "rows": [{"x": 1.23456, "y": None} for _ in range(40)]}
    out = json.loads(at.render(big))
    assert "owner_name" not in out and out["rows"][0] == {"x": 1.23}
    assert len(out["rows"]) == 16 and out["rows"][-1] == {"_more": 25}
    huge = {"rows": [{"t": "x" * 2000} for _ in range(40)]}
    assert len(at.render(huge)) <= at.MAX_CHARS


def test_to_api_merges_user_turns_and_folds_facts_when_needed():
    history = [
        {"role": "user", "content": "first"},
        {"role": "system", "content": "facts 1"},  # its answer failed: nothing followed it
        {"role": "user", "content": "again"},
        {"role": "system", "content": "facts 2"},
    ]
    out = chat.to_api(history, mid_system=True)
    assert [m["role"] for m in out] == ["user", "system"]
    assert [b["text"] for b in out[0]["content"]] == [
        "first",
        "<facts>\nfacts 1\n</facts>",
        "again",
    ]
    old = chat.to_api(history, mid_system=False)  # a model without mid-conversation system
    assert [m["role"] for m in old] == ["user"] and len(old[0]["content"]) == 4


def test_usage_cost_uses_list_prices():
    u = chat.Usage(input=1_000_000, output=100_000, cache_read=1_000_000, cache_write=0)
    assert u.cost("claude-opus-5-5") == round(4 + 2 + 0.2, 4)
    assert u.cost("some-future-model") is None
