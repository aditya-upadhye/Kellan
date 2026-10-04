from pathlib import Path

from matchlens.sim.match import SimulatedMatch

METADATA_FILE = "metadata.json"
EVENTS_FILE = "events.jsonl"
FRAMES_FILE = "frames.jsonl"


def write_match(match: SimulatedMatch, output_root: Path) -> Path:
    match_dir = output_root / match.metadata.match_id
    match_dir.mkdir(parents=True, exist_ok=True)
    (match_dir / METADATA_FILE).write_text(
        match.metadata.model_dump_json(indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with (match_dir / EVENTS_FILE).open("w", encoding="utf-8", newline="\n") as events_file:
        events_file.writelines(event.model_dump_json() + "\n" for event in match.events)
    if match.frames:
        with (match_dir / FRAMES_FILE).open("w", encoding="utf-8", newline="\n") as frames_file:
            frames_file.writelines(frame.model_dump_json() + "\n" for frame in match.frames)
    return match_dir
