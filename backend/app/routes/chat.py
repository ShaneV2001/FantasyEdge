"""The Claude advisor chat. Needs ANTHROPIC_API_KEY in .env; read-only, like the rest of the app."""

from __future__ import annotations

from collections.abc import Iterator

import anthropic
import duckdb
from fastapi import APIRouter, Body, Depends
from fastapi.responses import StreamingResponse

from app import deps
from app.config import Settings
from app.deps import get_ai, get_ai_settings, get_con, write_lock
from app.errors import NotFound, NotReady
from app.routes.team import team_ctx
from app.schemas import models as m
from app.services.assistant import chat
from app.services.assistant.tools import ToolEnv
from app.services.context import LeagueContext

router = APIRouter(tags=["chat"])

SSE_DOC = (
    "Server-sent events: `meta` {conversation_id, model}, `text` {text} as it streams, `tool` "
    "{name, label?, status: start|done|error}, `error` {message}, then `done` {stop_reason, usage}."
)


@router.post(
    "/team/{team_id}/chat",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": SSE_DOC}},
)
def send_chat(
    team_id: str,
    body: m.ChatRequest = Body(...),
    ctx: LeagueContext = Depends(team_ctx),
    con: duckdb.DuckDBPyConnection = Depends(get_con),
    ai: anthropic.Anthropic | None = Depends(get_ai),
    settings: Settings = Depends(get_ai_settings),
) -> StreamingResponse:
    """Ask the advisor about this team. Claude answers from FantasyEdge's own numbers by calling
    its views as tools; the reply streams as server-sent events."""
    if ai is None:
        raise NotReady("The advisor chat needs ANTHROPIC_API_KEY in .env (see .env.example).")
    if body.conversation_id:
        if chat.conversation_team(con, body.conversation_id) != team_id:
            raise NotFound("conversation", "That conversation belongs to another team.")
        cid = body.conversation_id
    else:
        cid = chat.create_conversation(con, team_id, body.message, settings.ai_model)

    def stream() -> Iterator[str]:
        cur = deps.new_cursor()  # the request's own cursor closes before the stream ends
        try:
            yield from chat.answer(ai, settings, cur, ToolEnv(ctx, cur, team_id), cid, body.message)
        finally:
            cur.close()

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/team/{team_id}/chats", response_model=list[m.ChatSummaryOut])
def list_chats(
    team_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> list[m.ChatSummaryOut]:
    """This team's conversations, most recent first."""
    rows = con.execute(
        "SELECT id, title, model, updated_at FROM ai_conversations WHERE team_id = ?"
        " ORDER BY updated_at DESC",
        [team_id],
    ).fetchall()
    return [m.ChatSummaryOut(id=i, title=t, model=mo, updated_at=u) for i, t, mo, u in rows]


@router.get("/chats/{conversation_id}", response_model=m.ChatOut)
def get_chat(conversation_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)) -> m.ChatOut:
    """One conversation as the chat shows it, with its total token use."""
    row = con.execute(
        "SELECT team_id, title, model, input_tokens, output_tokens, cache_read_tokens,"
        " cache_write_tokens FROM ai_conversations WHERE id = ?",
        [conversation_id],
    ).fetchone()
    if row is None:
        raise NotFound("conversation", f"Conversation not found: {conversation_id}")
    team_id, title, model, i, o, cr, cw = row
    usage = chat.Usage(i, o, cr, cw)
    return m.ChatOut(
        id=conversation_id,
        team_id=team_id,
        title=title,
        model=model,
        messages=[
            m.ChatMessageOut(**x) for x in chat.transcript(chat.load_messages(con, conversation_id))
        ],
        usage=m.ChatUsageOut(
            input_tokens=i,
            output_tokens=o,
            cache_read_tokens=cr,
            cache_write_tokens=cw,
            cost_usd=usage.cost(model or ""),
        ),  # fmt: skip
    )


@router.delete("/chats/{conversation_id}", response_model=m.ChatDeletedOut)
def delete_chat(
    conversation_id: str, con: duckdb.DuckDBPyConnection = Depends(get_con)
) -> m.ChatDeletedOut:
    """Delete a conversation and its messages."""
    chat.conversation_team(con, conversation_id)  # 404 if unknown
    with write_lock:
        con.execute("DELETE FROM ai_messages WHERE conversation_id = ?", [conversation_id])
        con.execute("DELETE FROM ai_conversations WHERE id = ?", [conversation_id])
    return m.ChatDeletedOut(deleted=conversation_id)
