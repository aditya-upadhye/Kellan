import json
from typing import Any

from matchlens.i18n import fallback_text
from matchlens.llm.client import MockResponse
from matchlens.models.traces import AgentName


def detector_response(user: str) -> dict[str, Any]:
    return {
        "decisions": [
            {
                "moment_id": item["moment_id"],
                "keep": True,
                "significance": item["rule_score"],
            }
            for item in json.loads(user)["candidates"]
        ],
        "merge_groups": [],
    }


def explainer_response(user: str) -> dict[str, Any]:
    request = json.loads(user)
    headline, prose = fallback_text("en", request["moment_type"])
    evidence = request["evidence"]
    return {
        "headline": headline,
        "body": [
            {
                "text": prose + " Recorded value: " if evidence else prose,
                "evidence_key": evidence[0]["key"] if evidence else None,
            }
        ],
        "tags": [request["moment_type"]],
    }


def personalizer_response(user: str) -> dict[str, Any]:
    request = json.loads(user)
    profile = request["profile"]
    headline, prose = fallback_text(profile["language"], request["moment_type"])
    allowed = request["allowed_claims"]
    key = allowed[0]["key"] if allowed and profile["mode"] == "analyst" else None
    if key is not None:
        prose += " Recorded value: "
    elif profile["mode"] == "player_focus":
        headline = request["favorite_player_name"]
    return {"headline": headline, "body": [{"text": prose, "claim_key": key}]}


def recap_response(user: str) -> dict[str, Any]:
    request = json.loads(user)
    spanish = request["profile"]["language"] == "es"
    evidence = request["final_snapshots"]
    key = evidence[0]["key"] if evidence else None
    label = evidence[0]["label"].lower() if evidence else ""
    opening = f"El registro muestra {label}: " if spanish else f"The record shows {label}: "
    paragraphs = [
        {"parts": [{"text": opening, "evidence_key": key}]}
        if key
        else {
            "parts": [
                {
                    "text": (
                        "El partido deja momentos destacados."
                        if spanish
                        else "The match leaves notable moments."
                    ),
                    "evidence_key": None,
                }
            ]
        },
        {
            "parts": [
                {
                    "text": (
                        "El juego queda resumido en los momentos verificados."
                        if spanish
                        else "Verified moments shape the story of the match."
                    ),
                    "evidence_key": None,
                }
            ]
        },
        {
            "parts": [
                {
                    "text": (
                        "El relato sigue la acción registrada."
                        if spanish
                        else "The account follows the recorded play."
                    ),
                    "evidence_key": None,
                }
            ]
        },
    ]
    return {"paragraphs": paragraphs}


def live_responses() -> dict[tuple[AgentName, str], MockResponse]:
    return {
        ("detector", "batch"): detector_response,
        ("explainer", "default"): explainer_response,
        ("personalizer", "default"): personalizer_response,
        ("producer", "recap"): recap_response,
    }
