from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matchlens.models.insights import MomentType
    from matchlens.models.profiles import Language

_FALLBACKS: dict[Language, dict[MomentType, tuple[str, str]]] = {
    "en": {
        "goal": (
            "A goal changes the match",
            "The score changes, giving the match a new direction.",
        ),
        "big_chance": (
            "A clear chance emerges",
            "The attack creates a moment that could change the match.",
        ),
        "card": (
            "A card raises the tension",
            "A disciplinary decision adds pressure to the match.",
        ),
        "momentum_swing": ("The match momentum shifts", "The balance of play is changing."),
        "press_shift": (
            "The pressure changes",
            "A change in pressure gives the match a different rhythm.",
        ),
        "control_shift": ("Control of the match shifts", "The balance of control has changed."),
        "milestone": ("A milestone in the match", "The match reaches an important moment."),
        "speed_alert": ("A quick burst stands out", "A burst of pace catches the eye."),
        "player_spotlight": ("A player steps forward", "A player makes their presence felt."),
    },
    "es": {
        "goal": ("El marcador cambia", "El marcador cambia y el partido toma otro rumbo."),
        "big_chance": (
            "La ocasión es clara",
            "El ataque genera peligro y puede cambiar el partido.",
        ),
        "card": (
            "La tarjeta eleva la tensión",
            "La decisión disciplinaria añade presión al partido.",
        ),
        "momentum_swing": (
            "Cambia el impulso del partido",
            "El equilibrio del juego está cambiando.",
        ),
        "press_shift": ("Cambia la presión", "La presión cambia el ritmo del partido."),
        "control_shift": (
            "Cambia el control del partido",
            "El equilibrio del control ha cambiado.",
        ),
        "milestone": ("Momento importante", "Momento clave en el partido."),
        "speed_alert": ("Aceleración destacada", "La arrancada rápida llama la atención."),
        "player_spotlight": (
            "El jugador toma protagonismo",
            "El jugador se hace notar en esta jugada.",
        ),
    },
}


def fallback_text(language: Language, moment_type: MomentType) -> tuple[str, str]:
    return _FALLBACKS[language][moment_type]
