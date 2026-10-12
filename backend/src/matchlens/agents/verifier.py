from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from matchlens.agents.facts import NO_EVIDENCE_CITED, REFERENCE_PATTERN
from matchlens.models.insights import CheckError

if TYPE_CHECKING:
    from matchlens.models.base import Language
    from matchlens.models.insights import Claim, Insight, Moment
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.store.base import MetricStore


HEADLINE_LIMIT = 60
BODY_LIMIT = 280

_CARDINALS = {
    "nil": 0,
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "seventy": 70,
    "eighty": 80,
    "ninety": 90,
    "once": 1,
    "twice": 2,
    "thrice": 3,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
}
_SCALES = {"hundred": 100, "thousand": 1000}
_SPANISH_CARDINALS = {
    "cero": 0,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "once": 11,
    "doce": 12,
    "trece": 13,
    "catorce": 14,
    "quince": 15,
    "dieciseis": 16,
    "dieciséis": 16,
    "diecisiete": 17,
    "dieciocho": 18,
    "diecinueve": 19,
    "veinte": 20,
    "veintiun": 21,
    "veintiuno": 21,
    "veintiuna": 21,
    "veintidos": 22,
    "veintidós": 22,
    "veintitres": 23,
    "veintitrés": 23,
    "veinticuatro": 24,
    "veinticinco": 25,
    "veintiseis": 26,
    "veintiséis": 26,
    "veintisiete": 27,
    "veintiocho": 28,
    "veintinueve": 29,
    "treinta": 30,
    "cuarenta": 40,
    "cincuenta": 50,
    "sesenta": 60,
    "setenta": 70,
    "ochenta": 80,
    "noventa": 90,
    "cien": 100,
    "ciento": 100,
    "doscientos": 200,
    "trescientos": 300,
    "cuatrocientos": 400,
    "quinientos": 500,
    "seiscientos": 600,
    "setecientos": 700,
    "ochocientos": 800,
    "novecientos": 900,
    "primero": 1,
    "primera": 1,
    "primer": 1,
    "segundo": 2,
    "segunda": 2,
    "tercero": 3,
    "tercera": 3,
    "cuarto": 4,
    "cuarta": 4,
    "quinto": 5,
    "quinta": 5,
    "sexto": 6,
    "sexta": 6,
    "septimo": 7,
    "séptimo": 7,
    "septima": 7,
    "séptima": 7,
    "octavo": 8,
    "octava": 8,
    "noveno": 9,
    "novena": 9,
    "decimo": 10,
    "décimo": 10,
    "decima": 10,
    "décima": 10,
}
_SPANISH_SCALES = {"cientos": 100, "mil": 1000}
_SPANISH_UNIT_PATTERN = r"por\s+ciento|índice|indice|km/h|%|xG|ratio|m|puntos?"
_DIGIT_PATTERN = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:st|nd|rd|th|\s?(?:km/h|%|xG|index|ratio|m|points?|por\s+ciento|índice|indice))?(?!\w)",
    re.IGNORECASE,
)
_DIGIT_VALUE = re.compile(r"^([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")
_PREFIX_UNIT_PATTERN = re.compile(
    r"\b(?P<unit>km/h|xG|index|ratio|m)\s*(?:(?:of|is|at|=|:)\s*)?$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class _Number:
    start: int
    end: int
    value: Decimal
    places: int
    unit: str | None


async def verify_draft(
    insight: Insight,
    moment: Moment,
    evidence: list[MetricSnapshot],
    store: MetricStore,
    language: Language = "en",
) -> list[CheckError]:
    errors = await verify_claims(insight, moment, store, language)
    if evidence and not insight.claims:
        errors.append(CheckError(code="unsupported_claim", detail=NO_EVIDENCE_CITED))
    return errors


async def verify_claims(
    insight: Insight, moment: Moment, store: MetricStore, language: Language = "en"
) -> list[CheckError]:
    text = f"{insight.headline}\n{insight.body}"
    numbers = _numbers(text, language)
    covered: set[int] = set()
    errors: list[CheckError] = []

    if len(insight.headline) > HEADLINE_LIMIT:
        errors.append(CheckError(code="too_long", detail="headline exceeds 60 characters"))
    if len(insight.body) > BODY_LIMIT:
        errors.append(CheckError(code="too_long", detail="body exceeds 280 characters"))
    if insight.moment_id != moment.moment_id:
        errors.append(CheckError(code="unsupported_claim", detail="insight moment does not match"))

    for reference in REFERENCE_PATTERN.finditer(text):
        errors.append(
            CheckError(
                code="unsupported_claim",
                detail=f"unresolved evidence reference {reference.group()}",
            )
        )

    citations = Counter(claim.text_span for claim in insight.claims)
    for claim in insight.claims:
        claim_errors, spans = await _check_claim(claim, moment, store, text, language)
        errors.extend(claim_errors)
        cited = spans[: citations[claim.text_span]]
        covered.update(
            index
            for index, number in enumerate(numbers)
            if any(start <= number.start and number.end <= end for start, end in cited)
        )

    for index, number in enumerate(numbers):
        if index not in covered:
            errors.append(
                CheckError(
                    code="uncited_number",
                    detail=f"{text[number.start : number.end]} at position {number.start}",
                )
            )
    return errors


async def _check_claim(
    claim: Claim,
    moment: Moment,
    store: MetricStore,
    text: str,
    language: Language,
) -> tuple[list[CheckError], list[tuple[int, int]]]:
    errors: list[CheckError] = []
    spans = [match.span() for match in re.finditer(re.escape(claim.text_span), text)]
    if not spans:
        errors.append(
            CheckError(code="span_not_found", detail=f"{claim.claim_id}: text span is absent")
        )

    displayed = _numbers(claim.text_span, language)
    if len(displayed) != 1:
        errors.append(
            CheckError(
                code="unsupported_claim",
                detail=f"{claim.claim_id}: text span must contain one number",
            )
        )
        return errors, spans
    number = displayed[0]
    if claim.as_of_seq > moment.seq_end or claim.metric_id not in moment.evidence_metric_ids:
        errors.append(
            CheckError(code="unsupported_claim", detail=f"{claim.claim_id}: unsupported evidence")
        )
        return errors, spans

    snapshot = await store.get(moment.match_id, claim.metric_id, claim.as_of_seq)
    if snapshot is None:
        errors.append(
            CheckError(code="unknown_metric", detail=f"{claim.claim_id}: {claim.metric_id}")
        )
    else:
        if number.unit != snapshot.unit.lower() and (
            number.unit is not None or snapshot.unit not in {"", "count"}
        ):
            errors.append(
                CheckError(code="unsupported_claim", detail=f"{claim.claim_id}: unit mismatch")
            )
        if not _matches(number, claim.value, snapshot):
            errors.append(
                CheckError(code="value_mismatch", detail=f"{claim.claim_id}: {claim.metric_id}")
            )
    return errors, spans


def _matches(number: _Number, claimed: float, snapshot: MetricSnapshot) -> bool:
    precision = Decimal(1).scaleb(-number.places)
    actual = Decimal(str(snapshot.value)).quantize(precision, rounding=ROUND_HALF_UP)
    return (
        Decimal(str(claimed)).quantize(precision, rounding=ROUND_HALF_UP) == actual
        and number.value == actual
    )


def _numbers(text: str, language: Language = "en") -> list[_Number]:
    numbers: list[_Number] = []
    for match in _DIGIT_PATTERN.finditer(text):
        value_match = _DIGIT_VALUE.match(match.group())
        if value_match is None:
            continue
        literal = value_match.group(1).replace(",", "")
        suffix = match.group()[value_match.end() :].strip().lower()
        unit = suffix if suffix not in {"st", "nd", "rd", "th", ""} else None
        if unit is not None:
            unit = _normalize_unit(unit, language)
        if unit is None:
            prefix = text[max(0, match.start() - 32) : match.start()]
            prefix_match = _PREFIX_UNIT_PATTERN.search(prefix)
            unit = prefix_match.group("unit").lower() if prefix_match else None
        places = len(literal.partition(".")[2])
        numbers.append(_Number(match.start(), match.end(), Decimal(literal), places, unit))
    words, scales, conjunction, unit_pattern = _word_grammar(language)
    number_word_pattern = "|".join(sorted((*words, *scales), key=len, reverse=True))
    conjunction_pattern = r"and" if conjunction == "and" else r"y"
    word_pattern = re.compile(
        rf"\b(?P<sign>menos\s+)?(?P<words>(?:{number_word_pattern})(?:[\s-]+(?:(?:{conjunction_pattern})[\s-]+)?(?:{number_word_pattern}))*)"
        rf"(?:\s+coma\s+(?P<fraction>(?:{number_word_pattern})(?:[\s-]+(?:{number_word_pattern}))*)\b)?"
        rf"\b(?:\s?(?P<unit>{unit_pattern}))?",
        re.IGNORECASE,
    )
    for match in word_pattern.finditer(text):
        if match.group("words").lower() == "nil-nil":
            numbers.extend(
                (
                    _Number(match.start(), match.start() + 3, Decimal(0), 0, None),
                    _Number(match.start() + 4, match.start() + 7, Decimal(0), 0, None),
                )
            )
            continue
        value = Decimal(_word_value(match.group("words"), words, scales, conjunction))
        if match.group("sign"):
            value = -value
        fraction = match.group("fraction")
        places = 0
        if fraction:
            fraction_tokens = fraction.lower().replace("-", " ").split()
            if any(token not in words or words[token] > 9 for token in fraction_tokens):
                continue
            fraction_text = "".join(str(words[token]) for token in fraction_tokens)
            places = len(fraction_text)
            value += Decimal(f"0.{fraction_text}")
        unit = match.group("unit")
        normalized_unit = _normalize_unit(unit, language) if unit else None
        numbers.append(_Number(match.start(), match.end(), value, places, normalized_unit))
    return sorted(numbers, key=lambda number: number.start)


def _word_grammar(language: Language) -> tuple[dict[str, int], dict[str, int], str, str]:
    if language == "es":
        return _SPANISH_CARDINALS, _SPANISH_SCALES, "y", _SPANISH_UNIT_PATTERN
    return _CARDINALS, _SCALES, "and", r"km/h|%|xG|index|ratio|m|points?"


def _normalize_unit(unit: str, language: Language) -> str:
    normalized = unit.lower()
    if language == "es":
        return {"por ciento": "%", "índice": "index", "indice": "index"}.get(normalized, normalized)
    return normalized


def _word_value(
    text: str,
    numbers: dict[str, int],
    scales: dict[str, int],
    conjunction: str,
) -> int:
    total = 0
    current = 0
    for word in text.lower().replace("-", " ").split():
        if word == conjunction:
            continue
        if word in scales and scales[word] < 1000:
            current = max(current, 1) * 100
        elif word in scales:
            total += max(current, 1) * scales[word]
            current = 0
        else:
            current += numbers[word]
    return total + current
