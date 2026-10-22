import asyncio

from matchlens.api.matches import MatchManager, StartMatchRequest
from matchlens.config import LLMMode, Settings


def test_live_match_produces_frames_and_can_stop_before_generation_finishes() -> None:
    async def exercise() -> None:
        manager = MatchManager(Settings(judge_mode=False, llm_mode=LLMMode.OFF))
        session = await manager.start(StartMatchRequest(speed=1))
        try:
            async with asyncio.timeout(5):
                while not session.frames:
                    assert session.state != "error", session.error
                    await asyncio.sleep(0.01)
            assert session.frames[0].clock.ms == 0
            assert session.state == "running"
            assert session.task is not None
            assert not session.task.done()
        finally:
            await asyncio.wait_for(manager.close(), timeout=5)
        assert session.task is not None
        assert session.task.done()

    asyncio.run(exercise())
