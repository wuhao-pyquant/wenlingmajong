from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .hand_luck_neighbor import HandLuckNeighborScorer, load_hand_luck_neighbor_scorer


@dataclass(frozen=True)
class HandLuckNeighborAverageResult:
    seat: int | None
    predicted_point_delta: float
    luck_impact: float
    luck_percentile: float
    categories: dict[str, str]
    features: dict[str, float]
    model_score: float
    normal_progress_rate: float
    leizi_progress_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandLuckNeighborAverageScorer:
    """Compatibility wrapper around the neighbor-average hand-luck runtime."""

    def __init__(self, inner: HandLuckNeighborScorer) -> None:
        self.inner = inner
        self.low_efficiency_category = "<=-1.5"

    @classmethod
    def from_json(cls, path: str | Path) -> "HandLuckNeighborAverageScorer":
        return cls(HandLuckNeighborScorer.from_json(path))

    def score(self, **kwargs: Any) -> HandLuckNeighborAverageResult:
        scorer_kwargs = _normalize_kwargs(kwargs)
        result = self.inner.score(**scorer_kwargs)
        model_score = float(result.model_score)
        return HandLuckNeighborAverageResult(
            seat=result.seat,
            predicted_point_delta=model_score,
            luck_impact=model_score,
            luck_percentile=result.luck_percentile,
            categories=_categories(scorer_kwargs, result.normal_progress_rate, result.leizi_progress_rate),
            features=dict(result.features),
            model_score=model_score,
            normal_progress_rate=result.normal_progress_rate,
            leizi_progress_rate=result.leizi_progress_rate,
        )

    def score_players(self, players: Iterable[Mapping[str, Any]]) -> list[HandLuckNeighborAverageResult]:
        return [self.score(**dict(player)) for player in players]


def _normalize_kwargs(kwargs: Mapping[str, Any]) -> dict[str, Any]:
    normalized = dict(kwargs)
    flags = _compat_jump_flags(str(normalized.get("win_type") or ""))
    for name, value in flags.items():
        if normalized.get(name) is None:
            normalized[name] = value
    return normalized


def _compat_jump_flags(win_type: str) -> dict[str, bool]:
    normalized = win_type.strip()
    return {
        "leizi_win": any(token in normalized for token in ("劣子", "鍔", "閸旓絽")),
        "zimo_de": any(token in normalized for token in ("自摸得", "鑷", "閼奉")),
        "gang_flower": any(token in normalized for token in ("杠上开花", "鏉", "閺夌姳")),
        "rob_gang": normalized == "rob_gang"
        or any(token in normalized for token in ("抢杠", "鎶", "閹躲垺")),
    }


def _categories(kwargs: Mapping[str, Any], normal_rate: float, leizi_rate: float) -> dict[str, str]:
    de_draws = int(kwargs.get("de_draws") or 0)
    fan_flower_draws = int(kwargs.get("fan_flower_draws") or 0)
    opening_shanten = int(kwargs.get("opening_shanten") or 0)
    opening_leizi_distance = int(kwargs.get("opening_leizi_distance") or 0)
    leizi_win = bool(kwargs.get("leizi_win")) or de_draws >= 3
    zimo_de = bool(kwargs.get("zimo_de"))
    gang_flower = bool(kwargs.get("gang_flower"))
    rob_gang = bool(kwargs.get("rob_gang"))
    return {
        "de": str(min(max(de_draws, 0), 3)),
        "flower": str(min(max(fan_flower_draws, 0), 5)),
        "shanten": str(min(max(opening_shanten, 0), 7)),
        "progress": _progress_category(normal_rate),
        "opening_leizi": str(min(max(opening_leizi_distance, 0), 4)),
        "leizi_progress": _progress_category(leizi_rate),
        "leizi_win": "1" if leizi_win else "0",
        "zimo_de": "1" if zimo_de else "0",
        "gang_flower": "1" if gang_flower else "0",
        "rob_gang": "1" if rob_gang else "0",
    }


def _progress_category(value: float) -> str:
    if value <= -1.5:
        return "<=-1.5"
    if value <= -1.0:
        return "-1.5~-1.0"
    if value <= -0.6:
        return "-1.0~-0.6"
    if value <= -0.3:
        return "-0.6~-0.3"
    if value < 0:
        return "-0.3~0"
    if value == 0:
        return "0"
    return ">0"


HandLuckResult = HandLuckNeighborAverageResult
HandLuckScorer = HandLuckNeighborAverageScorer


def load_hand_luck_scorer(model_path: str | Path | None = None) -> HandLuckScorer:
    return HandLuckNeighborAverageScorer(load_hand_luck_neighbor_scorer(model_path))


def load_hand_luck_efficiency6_scorer(model_path: str | Path | None = None) -> HandLuckScorer:
    """Backward-compatible alias for older callers."""
    return load_hand_luck_scorer(model_path)


def load_hand_luck_jump_bool_scorer(model_path: str | Path | None = None) -> HandLuckScorer:
    """Backward-compatible alias for the previous runtime package name."""
    return load_hand_luck_scorer(model_path)


def load_hand_luck_monotonic_scorer(model_path: str | Path | None = None) -> HandLuckScorer:
    """Backward-compatible alias for the previous anchored monotonic runtime."""
    return load_hand_luck_scorer(model_path)
