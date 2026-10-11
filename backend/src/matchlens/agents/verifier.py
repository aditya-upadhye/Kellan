from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

from matchlens.models.insights import CheckError

if TYPE_CHECKING:
    from matchlens.models.insights import Claim, Insight, Moment
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.store.base import MetricStore


HEADLINE_LIMIT = 60
BODY_LIMIT = 280

_CARDINALS = {
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
_NUMBER_WORD = "|".join(sorted((*_CARDINALS, *_SCALES), key=len, reverse=True))
_WORD_PATTERN = re.compile(
    rf"\b(?P<words>(?:{_NUMBER_WORD})(?:[\s-]+(?:and[\s-]+)?(?:{_NUMBER_WORD}))*)"
    r"\b(?:\s?(?P<unit>km/h|%|xG))?",
    re.IGNORECASE,
)
_DIGIT_PATTERN = re.compile(
    r"(?<![\w.])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
    r"(?:st|nd|rd|th|\s?(?:km/h|%|xG))?(?!\w)",
    re.IGNORECASE,
)
_DIGIT_VALUE = re.compile(r"^([-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)")


@dataclass(frozen=True, slots=True)
class _Number:
    start: int
    end: int
    value: Decimal
    places: int
    unit: str | None


async def verify_claims(insight: Insight, moment: Moment, store: MetricStore) -> list[CheckError]:
    text = f"{insight.headline}\n{insight.body}"
    numbers = _numbers(text)
    covered: set[int] = set()
    errors: list[CheckError] = []

    if len(insight.headline) > HEADLINE_LIMIT:
        errors.append(CheckError(code="too_long", detail="headline exceeds 60 characters"))
    if len(insight.body) > BODY_LIMIT:
        errors.append(CheckError(code="too_long", detail="body exceeds 280 characters"))
    if insight.moment_id != moment.moment_id:
        errors.append(CheckError(code="unsupported_claim", detail="insight moment does not match"))

    for claim in insight.claims:
        claim_errors, claim_coverage = await _check_claim(claim, moment, store, text, numbers)
        errors.extend(claim_errors)
        covered.update(claim_coverage)

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
    numbers: list[_Number],
) -> tuple[list[CheckError], set[int]]:
    errors: list[CheckError] = []
    spans = list(re.finditer(re.escape(claim.text_span), text))
    covered = {
        index
        for index, number in enumerate(numbers)
        if any(span.start() <= number.start and number.end <= span.end() for span in spans)
    }
    if not spans:
        errors.append(
            CheckError(code="span_not_found", detail=f"{claim.claim_id}: text span is absent")
        )

    displayed = _numbers(claim.text_span)
    if len(displayed) != 1:
        errors.append(
            CheckError(
                code="unsupported_claim",
                detail=f"{claim.claim_id}: text span must contain one number",
            )
        )
        return errors, covered
    number = displayed[0]
    if claim.as_of_seq > moment.seq_end or claim.metric_id not in moment.evidence_metric_ids:
        errors.append(
            CheckError(code="unsupported_claim", detail=f"{claim.claim_id}: unsupported evidence")
        )
        return errors, covered

    snapshot = await store.get(moment.match_id, claim.metric_id, claim.as_of_seq)
    if snapshot is None:
        errors.append(
            CheckError(code="unknown_metric", detail=f"{claim.claim_id}: {claim.metric_id}")
        )
    elif number.unit is not None and number.unit != snapshot.unit.lower():
        errors.append(
            CheckError(code="unsupported_claim", detail=f"{claim.claim_id}: unit mismatch")
        )
    elif not _matches(number, claim.value, snapshot):
        errors.append(
            CheckError(code="value_mismatch", detail=f"{claim.claim_id}: {claim.metric_id}")
        )
    return errors, covered


def _matches(number: _Number, claimed: float, snapshot: MetricSnapshot) -> bool:
    precision = Decimal(1).scaleb(-number.places)
    actual = Decimal(str(snapshot.value)).quantize(precision, rounding=ROUND_HALF_UP)
    return (
        Decimal(str(claimed)).quantize(precision, rounding=ROUND_HALF_UP) == actual
        and number.value == actual
    )


def _numbers(text: str) -> list[_Number]:
    numbers: list[_Number] = []
    for match in _DIGIT_PATTERN.finditer(text):
        value_match = _DIGIT_VALUE.match(match.group())
        if value_match is None:
            continue
        literal = value_match.group(1).replace(",", "")
        suffix = match.group()[value_match.end() :].strip().lower()
        unit = suffix if suffix not in {"st", "nd", "rd", "th", ""} else None
        places = len(literal.partition(".")[2])
        numbers.append(_Number(match.start(), match.end(), Decimal(literal), places, unit))
    for match in _WORD_PATTERN.finditer(text):
        value = _word_value(match.group("words"))
        unit = match.group("unit")
        numbers.append(
            _Number(match.start(), match.end(), Decimal(value), 0, unit.lower() if unit else None)
        )
    return sorted(numbers, key=lambda number: number.start)


def _word_value(text: str) -> int:
    total = 0
    current = 0
    for word in text.lower().replace("-", " ").split():
        if word == "and":
            continue
        if word == "hundred":
            current = max(current, 1) * 100
        elif word == "thousand":
            total += max(current, 1) * 1000
            current = 0
        else:
            current += _CARDINALS[word]
    return total + current
