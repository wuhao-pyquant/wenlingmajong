from __future__ import annotations

import json
from bisect import bisect_left, bisect_right
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class HandLuckMonotonicResult:
    seat: int
    predicted_point_delta: float
    luck_impact: float
    luck_percentile: float
    feature_levels: dict[str, str]
    normal_progress_rate: float
    leizi_progress_rate: float

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HandLuckMonotonicScorer:
    def __init__(self, payload: Mapping[str, Any]) -> None:
        self.intercept = float(payload["intercept"])
        self.seat_effect = [float(value) for value in payload["seat_effect"]]
        self.feature_order = [str(value) for value in payload["feature_order"]]
        self.levels = {
            str(feature): [str(value) for value in values]
            for feature, values in payload["levels"].items()
        }
        self.effects = {
            str(feature): [float(value) for value in values]
            for feature, values in payload["effects"].items()
        }
        self.seat_means = {str(key): float(value) for key, value in payload["seat_means"].items()}
        self.sorted_luck = [float(value) for value in payload["per_hand"]["sorted_luck_impact"]]
        if self.sorted_luck != sorted(self.sorted_luck):
            raise ValueError("per_hand.sorted_luck_impact must be sorted in ascending order")

    @classmethod
    def from_json(cls, path: str | Path) -> "HandLuckMonotonicScorer":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls(json.load(handle))

    def score(
        self,
        *,
        seat: int,
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
    ) -> HandLuckMonotonicResult:
        feature_indices, feature_levels, normal_rate, leizi_rate = self._feature_indices(
            seat=seat,
            de_draws=de_draws,
            fan_flower_draws=fan_flower_draws,
            opening_shanten=opening_shanten,
            final_shanten=final_shanten,
            normal_draw_count=normal_draw_count,
            open_claim_count=open_claim_count,
            opening_leizi_distance=opening_leizi_distance,
            final_leizi_distance=final_leizi_distance,
            supplement_draw_count=supplement_draw_count,
            flags=_jump_flags(
                win_type=win_type,
                leizi_win=leizi_win,
                zimo_de=zimo_de,
                gang_flower=gang_flower,
                rob_gang=rob_gang,
            ),
        )
        predicted = self.intercept + self.seat_effect[seat]
        for feature in self.feature_order:
            predicted += self.effects[feature][feature_indices[feature]]
        luck_impact = predicted - self.seat_means[str(seat)]
        return HandLuckMonotonicResult(
            seat=seat,
            predicted_point_delta=round(predicted, 2),
            luck_impact=round(luck_impact, 2),
            luck_percentile=round(self._midrank_percentile(luck_impact), 1),
            feature_levels=feature_levels,
            normal_progress_rate=round(normal_rate, 6),
            leizi_progress_rate=round(leizi_rate, 6),
        )

    def score_players(self, players: Iterable[Mapping[str, Any]]) -> list[HandLuckMonotonicResult]:
        results = [self.score(**dict(player)) for player in players]
        seats = [result.seat for result in results]
        if len(seats) != len(set(seats)):
            raise ValueError("player seats must be unique")
        return results

    def _feature_indices(
        self,
        *,
        seat: int,
        de_draws: int,
        fan_flower_draws: int,
        opening_shanten: int,
        final_shanten: int,
        normal_draw_count: int,
        open_claim_count: int,
        opening_leizi_distance: int,
        final_leizi_distance: int,
        supplement_draw_count: int,
        flags: Mapping[str, bool],
    ) -> tuple[dict[str, int], dict[str, str], float, float]:
        if seat not in range(4):
            raise ValueError("seat must be 0, 1, 2, or 3")
        if de_draws < 0 or fan_flower_draws < 0:
            raise ValueError("de_draws and fan_flower_draws cannot be negative")
        if opening_shanten < 0 or final_shanten < 0:
            raise ValueError("shanten values cannot be negative")
        if normal_draw_count < 0 or open_claim_count < 0 or supplement_draw_count < 0:
            raise ValueError("draw and claim counts cannot be negative")
        if opening_leizi_distance < 0 or final_leizi_distance < 0:
            raise ValueError("leizi distances cannot be negative")

        normal_denominator = max(1, int(normal_draw_count) + int(open_claim_count))
        leizi_denominator = max(1, int(normal_draw_count) + int(supplement_draw_count))
        normal_rate = (int(final_shanten) - int(opening_shanten)) / normal_denominator
        leizi_rate = (int(final_leizi_distance) - int(opening_leizi_distance)) / leizi_denominator
        leizi_win_flag = bool(flags["leizi_win"]) or int(de_draws) >= 3
        indices = {
            "de": min(int(de_draws), 3),
            "flower": min(int(fan_flower_draws), 5),
            "shanten": 7 - min(int(opening_shanten), 7),
            "progress": _efficiency_good_index(normal_rate),
            "opening_leizi": 4 - min(int(opening_leizi_distance), 4),
            "leizi_progress": _efficiency_good_index(leizi_rate),
            "leizi_win": 1 if leizi_win_flag else 0,
            "zimo_de": 1 if flags["zimo_de"] else 0,
            "gang_flower": 1 if flags["gang_flower"] else 0,
            "rob_gang": 1 if flags["rob_gang"] else 0,
        }
        return (
            indices,
            {feature: self.levels[feature][index] for feature, index in indices.items()},
            normal_rate,
            leizi_rate,
        )

    def _midrank_percentile(self, value: float) -> float:
        if not self.sorted_luck:
            return 50.0
        left = bisect_left(self.sorted_luck, value)
        right = bisect_right(self.sorted_luck, value)
        return 100.0 * (left + 0.5 * (right - left)) / len(self.sorted_luck)


def _jump_flags(
    *,
    win_type: str | None,
    leizi_win: bool | int | None,
    zimo_de: bool | int | None,
    gang_flower: bool | int | None,
    rob_gang: bool | int | None,
) -> dict[str, bool]:
    normalized = str(win_type or "").strip()
    return {
        "leizi_win": bool(leizi_win) if leizi_win is not None else normalized == "\u52a3\u5b50\u548c",
        "zimo_de": bool(zimo_de) if zimo_de is not None else normalized == "\u81ea\u6478\u5f97",
        "gang_flower": bool(gang_flower) if gang_flower is not None else normalized == "\u6760\u4e0a\u5f00\u82b1",
        "rob_gang": bool(rob_gang)
        if rob_gang is not None
        else normalized in {"rob_gang", "\u62a2\u6760\u80e1", "\u62a2\u6760\u548c"},
    }


def _efficiency_good_index(value: float) -> int:
    if value > 0:
        return 0
    if value == 0:
        return 1
    if value > -0.3:
        return 2
    if value > -0.6:
        return 3
    if value > -1.0:
        return 4
    if value > -1.5:
        return 5
    return 6


def load_hand_luck_monotonic_scorer(
    model_path: str | Path | None = None,
) -> HandLuckMonotonicScorer:
    path = Path(model_path) if model_path is not None else Path(__file__).with_name(
        "hand_luck_monotonic_model.json"
    )
    return HandLuckMonotonicScorer.from_json(path)
