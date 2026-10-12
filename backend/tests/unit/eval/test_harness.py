from __future__ import annotations

import asyncio
import json
from hashlib import sha256
from typing import TYPE_CHECKING

import pytest

from matchlens.config import LLMMode, Settings
from matchlens.eval.harness import evaluate, mock_explainer, write_report

if TYPE_CHECKING:
    from pathlib import Path


def test_mock_fixture_corrects_deliberately_wrong_draft() -> None:
    moment_id = next(
        f"fixture-moment-{index}"
        for index in range(1000)
        if sha256(f"fixture-moment-{index}".encode()).digest()[0] % 10 == 0
    )
    payload = {
        "moment": {"moment_id": moment_id},
        "moment_type": "goal",
        "evidence": [{"metric_id": "team.home.xg", "value": 0.7, "unit": "xG", "as_of_seq": 10}],
        "check_errors": [],
    }

    first = mock_explainer(json.dumps(payload))
    payload["check_errors"] = [{"code": "value_mismatch", "detail": "wrong value"}]
    revised = mock_explainer(json.dumps(payload))

    assert first["claims"][0]["value"] == 1.7
    assert revised["claims"][0]["value"] == 0.7


def test_report_writes_machine_and_readable_results(tmp_path: Path) -> None:
    report = {
        "mode": "mock",
        "fault_rate": 1.0,
        "summary": {
            "matches": 1,
            "unverified_claims": 0,
            "faults_caught": 2,
            "faults_injected": 2,
            "fault_catch_rate": 1.0,
            "first_pass_rate": 0.5,
            "fallback_rate": 0.0,
            "moments_per_match": 20,
            "insight_latency_p50_ms": 3,
            "insight_latency_p95_ms": 5,
            "llm_calls": 40,
            "tokens_in": 100,
            "tokens_out": 50,
        },
        "matches": [
            {
                "scenario": "balanced",
                "seed": 1,
                "moments": 20,
                "first_pass": 10,
                "fallbacks": 0,
                "claims": 2,
                "faults_caught": 2,
                "faults_injected": 2,
            }
        ],
    }
    json_path = tmp_path / "eval/report.json"
    markdown_path = tmp_path / "docs/eval-results.md"

    write_report(report, json_path, markdown_path)

    assert json.loads(json_path.read_text(encoding="utf-8")) == report
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Unverified numeric claims shipped | 0" in markdown
    assert "Fault catch rate | 100.0%" in markdown
    assert "balanced | 1 | 20" in markdown


@pytest.mark.slow
def test_full_mock_match_catches_faults_before_output() -> None:
    settings = Settings(llm_mode=LLMMode.MOCK)
    report = asyncio.run(evaluate(["balanced"], [1], LLMMode.MOCK, 1.0, settings))
    summary = report["summary"]

    assert 15 <= summary["moments"] <= 30
    assert summary["claims"] > 0
    assert summary["faults_injected"] > 0
    assert summary["faults_caught"] == summary["faults_injected"]
    assert summary["unverified_claims"] == 0
    assert summary["fallbacks"] == 0
