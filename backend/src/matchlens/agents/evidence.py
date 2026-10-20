from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from matchlens.models.insights import Insight, Moment
    from matchlens.models.metrics import MetricSnapshot
    from matchlens.store.base import MetricStore


@dataclass(frozen=True, slots=True)
class EvidenceAnchor:
    """Retain the generation-time read-only metric view for published stories."""

    moment: Moment
    insight: Insight
    store: MetricStore


async def moment_evidence(moment: Moment, store: MetricStore) -> list[MetricSnapshot]:
    snapshots: list[MetricSnapshot] = []
    for metric_id in moment.evidence_metric_ids:
        if moment.type == "momentum_swing" and moment.seq_start < moment.seq_end:
            start = await store.get(moment.match_id, metric_id, moment.seq_start)
            if start is not None:
                snapshots.append(start)
        end = await store.get(moment.match_id, metric_id, moment.seq_end)
        if end is not None:
            snapshots.append(end)
    return snapshots
