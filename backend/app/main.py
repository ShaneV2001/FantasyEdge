"""FantasyEdge API."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.errors import AuthRequired, InvalidInput, NotFound, NotReady
from app.routes import chat, league, meta, settings, team, trade
from ingest.http import SourceUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("fantasyedge.api")

app = FastAPI(
    generate_unique_id_function=lambda route: route.name,  # clean client names: getTeam, getAdvice…
    title="FantasyEdge API",
    version="0.1.0",
    description="Fantasy football team advisor. Data: Sleeper, nflverse (CC-BY 4.0), FantasyCalc, DynastyProcess.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (league.router, team.router, trade.router, meta.router, settings.router, chat.router):
    app.include_router(r)


@app.exception_handler(SourceUnavailable)
def _source_down(_: Request, exc: SourceUnavailable) -> JSONResponse:
    log.error("source unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={
            "detail": f"{exc.source} is unavailable right now. Try again shortly.",
            "source": exc.source,
        },
    )


@app.exception_handler(NotReady)
def _not_ready(_: Request, exc: NotReady) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc), "source": "local"})


@app.exception_handler(NotFound)
def _not_found(_: Request, exc: NotFound) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": exc.detail, "kind": exc.kind})


@app.exception_handler(AuthRequired)
def _auth_required(_: Request, exc: AuthRequired) -> JSONResponse:
    return JSONResponse(
        status_code=401, content={"detail": exc.detail, "kind": exc.kind, "source": "espn"}
    )


@app.exception_handler(InvalidInput)
def _invalid(_: Request, exc: InvalidInput) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"ok": True}
