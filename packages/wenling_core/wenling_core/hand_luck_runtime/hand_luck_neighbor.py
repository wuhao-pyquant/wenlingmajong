from __future__ import annotations

import json
import math
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class HandLuckNeighborResult:
    seat: int | None
    model_score: float
    luck_percentile: float
    features: dict[str, float]
    normal_progress_rate: float
    leizi_progress_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandLuckNeighborScorer:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.payload = payload
        self.feature_names = [str(value) for value in payload["feature_names"]]
        self.w1 = [[float(v) for v in row] for row in payload["w1"]]
        self.b1 = [float(v) for v in payload["b1"]]
        self.w2 = [float(v) for v in payload["w2"]]
        self.bias = float(payload["bias"])
        self.sorted_scores = [float(value) for value in payload["per_hand"]["sorted_model_score"]]
        if self.sorted_scores != sorted(self.sorted_scores):
            raise ValueError("per_hand.sorted_model_score must be sorted in ascending order")

    @classmethod
    def from_json(cls, path: str | Path) -> "HandLuckNeighborScorer":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def score(
        self,
        *,
        seat: int | None = None,
        de_draws: int,
        fan_flower_draws: int,
        opening_shanten: int,
        final_shanten: int,
        normal_draw_count: int,
        open_claim_count: int,
        opening_leizi_distance: int,
        final_leizi_distance: int,
        supplement_draw_count: int = 0,
        win_type: str | None = None,
        leizi_win: bool | int | None = None,
        zimo_de: bool | int | None = None,
        gang_flower: bool | int | None = None,
        rob_gang: bool | int | None = None,
    ) -> HandLuckNeighborResult:
        if seat is not None and int(seat) not in range(4):
            raise ValueError("seat must be 0, 1, 2, or 3 when provided")
        if min(de_draws, fan_flower_draws, opening_shanten, final_shanten, normal_draw_count, open_claim_count,
               opening_leizi_distance, final_leizi_distance, supplement_draw_count) < 0:
            raise ValueError("counts and distances cannot be negative")
        flags = _jump_flags(
            win_type=win_type,
            leizi_win=leizi_win,
            zimo_de=zimo_de,
            gang_flower=gang_flower,
            rob_gang=rob_gang,
        )
        normal_denominator = max(1, int(normal_draw_count) + int(open_claim_count))
        leizi_denominator = max(1, int(normal_draw_count) + int(supplement_draw_count))
        normal_rate = (int(final_shanten) - int(opening_shanten)) / normal_denominator
        leizi_rate = (int(final_leizi_distance) - int(opening_leizi_distance)) / leizi_denominator
        values = {
            "de_draws": int(de_draws),
            "fan_flower_draws": int(fan_flower_draws),
            "opening_shanten": int(opening_shanten),
            "normal_progress_rate": normal_rate,
            "opening_leizi_distance": int(opening_leizi_distance),
            "leizi_progress_rate": leizi_rate,
            "leizi_win": bool(flags["leizi_win"]) or int(de_draws) >= 3,
            "zimo_de": bool(flags["zimo_de"]),
            "gang_flower": bool(flags["gang_flower"]),
            "rob_gang": bool(flags["rob_gang"]),
        }
        features = _feature_vector(values)
        score = self._predict_raw(features)
        return HandLuckNeighborResult(
            seat=None if seat is None else int(seat),
            model_score=round(score, 2),
            luck_percentile=round(self._midrank_percentile(score), 1),
            features={name: round(float(value), 6) for name, value in zip(self.feature_names, features, strict=True)},
            normal_progress_rate=round(normal_rate, 6),
            leizi_progress_rate=round(leizi_rate, 6),
        )

    def score_players(self, players: Iterable[Mapping[str, Any]]) -> list[HandLuckNeighborResult]:
        return [self.score(**dict(player)) for player in players]

    def _predict_raw(self, features: list[float]) -> float:
        hidden = []
        for j, bias in enumerate(self.b1):
            total = float(bias)
            for i, value in enumerate(features):
                total += float(value) * self.w1[i][j]
            hidden.append(_softplus(total))
        return self.bias + sum(h * w for h, w in zip(hidden, self.w2, strict=True))

    def _midrank_percentile(self, value: float) -> float:
        if not self.sorted_scores:
            return 50.0
        left = bisect_left(self.sorted_scores, value)
        right = bisect_right(self.sorted_scores, value)
        return 100.0 * (left + 0.5 * (right - left)) / len(self.sorted_scores)


def _softplus(value: float) -> float:
    if value > 50:
        return value
    if value < -50:
        return math.exp(value)
    return math.log1p(math.exp(value))


def _u(*codes: int) -> str:
    return "".join(chr(code) for code in codes)


def _jump_flags(
    *,
    win_type: str | None,
    leizi_win: bool | int | None,
    zimo_de: bool | int | None,
    gang_flower: bool | int | None,
    rob_gang: bool | int | None,
) -> dict[str, bool]:
    normalized = str(win_type or "").strip()
    leizi_names = {_u(0x52A3, 0x5B50, 0x548C), _u(0x52A3, 0x5B50, 0x80E1), "鍔ｅ瓙鍜?", "鍔ｅ瓙鑳?"}
    zimo_de_names = {_u(0x81EA, 0x6478, 0x5F97), "鑷懜寰?"}
    gang_flower_names = {_u(0x6760, 0x4E0A, 0x5F00, 0x82B1), "鏉犱笂寮€鑺?"}
    rob_gang_names = {
        "rob_gang",
        _u(0x62A2, 0x6760, 0x80E1),
        _u(0x62A2, 0x6760, 0x548C),
        "鎶㈡潬鑳?",
        "鎶㈡潬鍜?",
    }
    return {
        "leizi_win": bool(leizi_win) if leizi_win is not None else normalized in leizi_names,
        "zimo_de": bool(zimo_de) if zimo_de is not None else normalized in zimo_de_names,
        "gang_flower": bool(gang_flower) if gang_flower is not None else normalized in gang_flower_names,
        "rob_gang": bool(rob_gang)
        if rob_gang is not None
        else normalized in rob_gang_names,
    }


def _feature_vector(values: Mapping[str, Any]) -> list[float]:
    de = min(max(float(values.get("de_draws", 0.0)), 0.0), 3.0) / 3.0
    flower = min(max(float(values.get("fan_flower_draws", 0.0)), 0.0), 5.0) / 5.0
    opening_shanten = min(max(float(values.get("opening_shanten", 7.0)), 0.0), 7.0)
    opening_shanten_good = (7.0 - opening_shanten) / 7.0
    opening_shanten_zero = 1.0 if opening_shanten <= 0.0 else 0.0
    normal_rate = float(values.get("normal_progress_rate", 0.0))
    normal_progress_good = min(max(-normal_rate / 1.5, 0.0), 1.0)
    opening_leizi = min(max(float(values.get("opening_leizi_distance", 4.0)), 0.0), 4.0)
    opening_leizi_good = (4.0 - opening_leizi) / 4.0
    opening_leizi_zero = 1.0 if opening_leizi <= 0.0 else 0.0
    leizi_rate = float(values.get("leizi_progress_rate", 0.0))
    leizi_progress_good = min(max(-leizi_rate / 1.5, 0.0), 1.0)
    leizi_win = 1.0 if bool(values.get("leizi_win", False)) or float(values.get("de_draws", 0.0)) >= 3.0 else 0.0
    zimo_de = 1.0 if bool(values.get("zimo_de", False)) else 0.0
    gang_flower = 1.0 if bool(values.get("gang_flower", False)) else 0.0
    rob_gang = 1.0 if bool(values.get("rob_gang", False)) else 0.0
    return [
        de,
        flower,
        opening_shanten_good,
        opening_shanten_zero,
        normal_progress_good,
        opening_leizi_good,
        opening_leizi_zero,
        leizi_progress_good,
        leizi_win,
        zimo_de,
        gang_flower,
        rob_gang,
        de * flower,
        de * leizi_win,
        flower * gang_flower,
        max(opening_shanten_zero, opening_leizi_zero),
        opening_shanten_good * normal_progress_good,
        opening_leizi_good * leizi_progress_good,
        opening_leizi_good * leizi_win,
        de * zimo_de,
        min(leizi_win + zimo_de + gang_flower + rob_gang, 2.0) / 2.0,
        max(de, flower),
    ]


def load_hand_luck_neighbor_scorer(model_path: str | Path | None = None) -> HandLuckNeighborScorer:
    path = Path(model_path) if model_path is not None else Path(__file__).with_name("hand_luck_neighbor_model.json")
    return HandLuckNeighborScorer.from_json(path)
