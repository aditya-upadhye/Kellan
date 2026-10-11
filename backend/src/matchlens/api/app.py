from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

from matchlens.api.matches import (
    MatchControlRequest,
    MatchManager,
    StartMatchRequest,
    session_stream,
)
from matchlens.config import get_settings
from matchlens.obs import configure_console_tracing
from matchlens.sim.scenarios import load_scenario, scenario_names


def create_app() -> FastAPI:
    settings = get_settings()
    manager = MatchManager(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        configure_console_tracing()
        yield
        await manager.close()

    app = FastAPI(title="MatchLens API", lifespan=lifespan)
    app.state.match_manager = manager

    @app.get("/healthz")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/scenarios")
    async def scenarios() -> list[dict[str, str]]:
        return [
            {
                "name": name,
                "description": load_scenario(name, settings.scenarios_dir).description,
            }
            for name in scenario_names(settings.scenarios_dir)
        ]

    @app.post("/api/matches", status_code=202)
    async def start_match(request: StartMatchRequest) -> dict[str, str]:
        try:
            session = await manager.start(request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"match_id": session.metadata.match_id, "status": session.state}

    @app.get("/api/matches/{match_id}")
    async def get_match(match_id: str) -> dict[str, Any]:
        session = _get_session(manager, match_id)
        return {
            "metadata": session.metadata.model_dump(mode="json"),
            "status": session.state,
            "clock": session.clock,
            "score": session.score,
            "speed": session.speed,
            "error": session.error,
        }

    @app.get("/api/matches/{match_id}/state")
    async def get_match_state(match_id: str) -> dict[str, Any]:
        session = _get_session(manager, match_id)
        metrics = [item.model_dump(mode="json") for item in session.latest_metrics.values()]
        return {
            "match_id": match_id,
            "status": session.state,
            "clock": session.clock,
            "score": session.score,
            "metrics": metrics,
        }

    @app.get("/api/matches/{match_id}/events")
    async def get_events(
        match_id: str, since_seq: int = Query(default=0, ge=0)
    ) -> dict[str, list[dict[str, Any]]]:
        session = _get_session(manager, match_id)
        return {
            "events": [
                event.model_dump(mode="json") for event in session.events if event.seq > since_seq
            ]
        }

    @app.post("/api/matches/{match_id}/control")
    async def control_match(match_id: str, request: MatchControlRequest) -> dict[str, Any]:
        session = _get_session(manager, match_id)
        try:
            await manager.control(session, request)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"match_id": match_id, "status": session.state, "speed": session.speed}

    @app.websocket("/ws/matches/{match_id}")
    async def stream_match(websocket: WebSocket, match_id: str) -> None:
        try:
            session = manager.get(match_id)
        except LookupError:
            await websocket.close(code=4404, reason="Match not found")
            return
        await websocket.accept()
        try:
            async for message in session_stream(session):
                await websocket.send_text(message.model_dump_json())
        except WebSocketDisconnect:
            pass

    return app


def _get_session(manager: MatchManager, match_id: str):
    try:
        return manager.get(match_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


app = create_app()
