from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect

from matchlens.api.matches import (
    MatchControlRequest,
    MatchManager,
    StartMatchRequest,
    session_stream,
)
from matchlens.config import Settings, get_settings
from matchlens.models.cues import OverlayCue
from matchlens.models.profiles import ViewerProfile
from matchlens.models.traces import AgentTrace
from matchlens.obs import configure_console_tracing
from matchlens.profiles import DEFAULT_PROFILES, get_profile
from matchlens.sim.scenarios import load_scenario, scenario_names


def create_app(settings: Settings | None = None) -> FastAPI:
    manager = MatchManager(settings or get_settings())

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
                "description": load_scenario(name, manager.settings.scenarios_dir).description,
            }
            for name in scenario_names(manager.settings.scenarios_dir)
        ]

    @app.get("/api/profiles", response_model=list[ViewerProfile])
    async def profiles() -> list[ViewerProfile]:
        return list(DEFAULT_PROFILES)

    @app.get("/api/profiles/{profile_id}", response_model=ViewerProfile)
    async def profile(profile_id: str) -> ViewerProfile:
        selected = get_profile(profile_id)
        if selected is None:
            raise HTTPException(status_code=404, detail=f"profile {profile_id!r} was not found")
        return selected

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
            "profiles": [profile.profile_id for profile in session.profiles],
            "llm_mode": session.llm_mode,
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
        return {
            "match_id": match_id,
            "status": session.state,
            "speed": session.speed,
            "llm_mode": session.llm_mode,
        }

    @app.get("/api/matches/{match_id}/cues")
    async def get_cues(match_id: str, profile_id: str | None = None) -> dict[str, list[OverlayCue]]:
        session = _get_session(manager, match_id)
        if profile_id is not None and profile_id not in {
            profile.profile_id for profile in session.profiles
        }:
            raise HTTPException(status_code=422, detail="profile is not active in this match")
        return {
            "cues": [
                cue for cue in session.cues if profile_id is None or cue.profile_id == profile_id
            ]
        }

    @app.get("/api/matches/{match_id}/trace")
    async def get_trace(match_id: str) -> dict[str, list[AgentTrace]]:
        return {"traces": _get_session(manager, match_id).traces}

    @app.websocket("/ws/matches/{match_id}")
    async def stream_match(
        websocket: WebSocket, match_id: str, profiles: str | None = None
    ) -> None:
        try:
            session = manager.get(match_id)
        except LookupError:
            await websocket.close(code=4404, reason="Match not found")
            return
        selected = frozenset(profiles.split(",")) if profiles is not None else None
        if selected is not None and not selected <= {
            profile.profile_id for profile in session.profiles
        }:
            await websocket.close(code=4400, reason="Unknown match profile")
            return
        await websocket.accept()
        try:
            async for message in session_stream(session, selected):
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
