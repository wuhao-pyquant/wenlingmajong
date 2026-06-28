from __future__ import annotations

import random
import threading
from collections import Counter, OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from .model import action_label
from .rules import can_win, legal_discards, score_player
from .tiles import FLOWERS, TILE_ORDER, build_wall, is_suited


Action = dict[str, Any]
Metric = dict[str, Any]


PHYSICAL_TILE_COUNTS: dict[str, int] = Counter(build_wall())
_KEY_ORDER: tuple[str, ...] = tuple(TILE_ORDER)
_KEY_INDEX: dict[str, int] = {code: index for index, code in enumerate(_KEY_ORDER)}
_NON_SUITED_ORDER: tuple[str, ...] = tuple(code for code in _KEY_ORDER if not is_suited(code))
BAO_RISK_POINT_PENALTY = 1_000_000_000
_GLOBAL_METRIC_CACHE_MAX = 120_000
_GLOBAL_METRIC_CACHE: OrderedDict[tuple[Any, ...], Metric] = OrderedDict()
_GLOBAL_METRIC_HITS = 0
_GLOBAL_METRIC_MISSES = 0
_BEST_AFTER_DISCARD_CACHE_MAX = 120_000
_BEST_AFTER_DISCARD_CACHE: OrderedDict[tuple[Any, ...], Metric] = OrderedDict()
_BEST_AFTER_DISCARD_HITS = 0
_BEST_AFTER_DISCARD_MISSES = 0
_GLOBAL_CACHE_LOCK = threading.RLock()


def shanten(hand: Counter[str] | dict[str, int], de_set: set[str]) -> int:
    """Return normal-hu shanten for any legal concealed hand size.

    The result follows common Mahjong convention: -1 is a complete normal win,
    0 is tenpai, and larger values need that many improvements before tenpai.
    The target concealed group count is derived from the current concealed tile
    count instead of assuming a fixed 14/16/17-tile shape.
    """
    counts = Counter({code: int(count) for code, count in Counter(hand).items() if count > 0})
    return _shanten_cached(_counter_key(counts), tuple(sorted(de_set)))


@lru_cache(maxsize=200_000)
def _shanten_cached(hand_key: tuple[int, ...], de_tuple: tuple[str, ...]) -> int:
    de_set = set(de_tuple)
    counts = Counter({code: count for code, count in zip(_KEY_ORDER, hand_key) if count > 0})

    real_counts = Counter(counts)
    wilds = 0
    for code in list(real_counts):
        if code in de_set:
            wilds += real_counts.pop(code)

    concealed_total = sum(real_counts.values()) + wilds
    target_groups = _target_concealed_groups(concealed_total)
    if target_groups <= 0:
        if concealed_total % 3 == 2:
            return -1 if _has_normal_pair(real_counts, wilds) else 0
        return 0 if concealed_total else 1

    block_keys = _compact_block_keys(real_counts)
    states_by_used_wilds: dict[int, set[tuple[int, int, int]]] = {0: {(0, 0, 0)}}
    for block_key, suited in block_keys:
        next_states: dict[int, set[tuple[int, int, int]]] = {}
        for used_wilds, partial_states in states_by_used_wilds.items():
            for block_wilds in range(wilds - used_wilds + 1):
                total_wilds = used_wilds + block_wilds
                block_states = _compact_block_states(block_key, suited, block_wilds, target_groups)
                target_set = next_states.setdefault(total_wilds, set())
                for left in partial_states:
                    for right in block_states:
                        target_set.add(_merge_state(left, right, target_groups))
        states_by_used_wilds = next_states

    best = 2 * target_groups
    for used_wilds, partial_states in states_by_used_wilds.items():
        for wild_state in _wild_only_states(wilds - used_wilds, target_groups):
            for partial_state in partial_states:
                melds, taatsu, pair = _merge_state(partial_state, wild_state, target_groups)
                best = min(best, 2 * target_groups - 2 * melds - taatsu - pair)
    return max(-1, best)


@lru_cache(maxsize=200_000)
def _effective_tile_codes_cached(
    hand_key: tuple[int, ...],
    de_tuple: tuple[str, ...],
    flower_tuple: tuple[str, ...],
    base_shanten: int,
) -> tuple[str, ...]:
    de_set = set(de_tuple)
    flower_set = set(flower_tuple)
    effective: list[str] = []
    for index, code in enumerate(_KEY_ORDER):
        if code in FLOWERS and code not in de_set:
            continue
        if code in flower_set and code not in de_set:
            continue
        candidate = list(hand_key)
        candidate[index] += 1
        if _shanten_cached(tuple(candidate), de_tuple) < base_shanten:
            effective.append(code)
    return tuple(effective)


def _shanten_reference(hand: Counter[str] | dict[str, int], de_set: set[str]) -> int:
    """Legacy 42-slot block implementation retained for equivalence tests."""
    counts = Counter({code: int(count) for code, count in Counter(hand).items() if count > 0})
    real_counts = Counter(counts)
    wilds = 0
    for code in list(real_counts):
        if code in de_set:
            wilds += real_counts.pop(code)

    concealed_total = sum(real_counts.values()) + wilds
    target_groups = _target_concealed_groups(concealed_total)
    if target_groups <= 0:
        if concealed_total % 3 == 2:
            return -1 if _has_normal_pair(real_counts, wilds) else 0
        return 0 if concealed_total else 1

    block_keys = _split_block_keys(_counter_key(real_counts))
    states_by_used_wilds: dict[int, set[tuple[int, int, int]]] = {0: {(0, 0, 0)}}
    for block_key in block_keys:
        next_states: dict[int, set[tuple[int, int, int]]] = {}
        for used_wilds, partial_states in states_by_used_wilds.items():
            for block_wilds in range(wilds - used_wilds + 1):
                total_wilds = used_wilds + block_wilds
                block_states = _block_states(block_key, block_wilds, target_groups)
                target_set = next_states.setdefault(total_wilds, set())
                for left in partial_states:
                    for right in block_states:
                        target_set.add(_merge_state(left, right, target_groups))
        states_by_used_wilds = next_states

    best = 2 * target_groups
    for used_wilds, partial_states in states_by_used_wilds.items():
        for wild_state in _wild_only_states(wilds - used_wilds, target_groups):
            for partial_state in partial_states:
                melds, taatsu, pair = _merge_state(partial_state, wild_state, target_groups)
                best = min(best, 2 * target_groups - 2 * melds - taatsu - pair)
    return max(-1, best)


def hand_metric(
    observation: dict[str, Any],
    hand: Counter[str] | dict[str, int],
    melds: list[dict[str, Any]] | None = None,
    extra_visible: Counter[str] | None = None,
    include_points: bool = True,
    include_improvement: bool = True,
) -> Metric:
    public = observation.get("public", {})
    de_set = set(public.get("de_set", []))
    base_hand = Counter({code: int(count) for code, count in Counter(hand).items() if count > 0})
    own_melds = list(melds if melds is not None else _own_melds(observation))
    current_shanten = shanten(base_hand, de_set)
    waits = effective_tiles(observation, base_hand, current_shanten, extra_visible)
    improvements = improvement_tiles(observation, base_hand, current_shanten, sum(waits.values()), extra_visible) if include_improvement else {}
    point_score = current_points(observation, base_hand, own_melds) if include_points else 0
    return {
        "shanten": current_shanten,
        "ukeire": sum(waits.values()),
        "waits": waits,
        "improvement": sum(improvements.values()),
        "improvements": improvements,
        "points": point_score,
        "hand": dict(base_hand),
        "melds": own_melds,
    }


def effective_tiles(
    observation: dict[str, Any],
    hand: Counter[str],
    base_shanten: int | None = None,
    extra_visible: Counter[str] | None = None,
) -> dict[str, int]:
    public = observation.get("public", {})
    de_set = set(public.get("de_set", []))
    flower_set = set(public.get("flower_set", []))
    base = shanten(hand, de_set) if base_shanten is None else base_shanten
    visible = visible_counts(observation, hand, extra_visible)
    waits: dict[str, int] = {}
    for code in _effective_tile_codes_cached(
        _counter_key(hand),
        tuple(sorted(de_set)),
        tuple(sorted(flower_set)),
        base,
    ):
        remaining = max(0, PHYSICAL_TILE_COUNTS.get(code, 0) - visible.get(code, 0))
        if remaining > 0:
            waits[code] = remaining
    return waits


def improvement_tiles(
    observation: dict[str, Any],
    hand: Counter[str],
    base_shanten: int | None = None,
    base_ukeire: int | None = None,
    extra_visible: Counter[str] | None = None,
) -> dict[str, int]:
    public = observation.get("public", {})
    de_set = set(public.get("de_set", []))
    flower_set = set(public.get("flower_set", []))
    base = shanten(hand, de_set) if base_shanten is None else base_shanten
    if base_ukeire is None:
        base_ukeire = sum(effective_tiles(observation, hand, base, extra_visible).values())
    effective_codes = set(
        _effective_tile_codes_cached(
            _counter_key(hand),
            tuple(sorted(de_set)),
            tuple(sorted(flower_set)),
            base,
        )
    )
    visible = visible_counts(observation, hand, extra_visible)
    improvements: dict[str, int] = {}
    for code in TILE_ORDER:
        if code in FLOWERS and code not in de_set:
            continue
        if code in flower_set and code not in de_set:
            continue
        remaining = max(0, PHYSICAL_TILE_COUNTS.get(code, 0) - visible.get(code, 0))
        if remaining <= 0:
            continue
        if code in effective_codes:
            continue
        candidate = Counter(hand)
        candidate[code] += 1
        best = _best_after_draw_discard_metric(
            observation,
            candidate,
            Counter(extra_visible or {}),
            de_set,
            target_shanten=base,
        )
        if int(best.get("shanten", 99)) == base and int(best.get("ukeire", 0)) > int(base_ukeire):
            improvements[code] = remaining
    return improvements


def visible_counts(
    observation: dict[str, Any],
    hand: Counter[str] | dict[str, int],
    extra_visible: Counter[str] | None = None,
) -> Counter[str]:
    public = observation.get("public", {})
    visible = Counter({code: int(count) for code, count in Counter(hand).items() if count > 0})
    indicator = public.get("de_indicator")
    if indicator:
        visible[str(indicator)] += 1
    for player in public.get("players", []):
        visible.update(player.get("discards", []))
        visible.update(player.get("flowers", []))
        for meld in player.get("melds", []):
            visible.update(meld.get("tiles", []))
    if extra_visible:
        visible.update(extra_visible)
    for code in list(visible):
        visible[code] = min(visible[code], PHYSICAL_TILE_COUNTS.get(code, visible[code]))
    return visible


def current_points(
    observation: dict[str, Any],
    hand: Counter[str],
    melds: list[dict[str, Any]],
) -> int:
    public = observation.get("public", {})
    seat = int(observation.get("seat", 0))
    players = public.get("players", [])
    wind_index = seat
    if 0 <= seat < len(players):
        try:
            wind_index = int(players[seat].get("wind_index", seat))
        except (TypeError, ValueError):
            wind_index = seat
    return _current_points_cached(
        _counter_key(hand),
        tuple(sorted(str(code) for code in observation.get("flowers", []))),
        _melds_key(melds),
        wind_index,
        tuple(sorted(str(code) for code in public.get("de_set", []))),
        str(public.get("de_indicator", "")),
    )


@lru_cache(maxsize=200_000)
def _current_points_cached(
    hand_key: tuple[int, ...],
    flowers_key: tuple[str, ...],
    melds_key: tuple[tuple[str, tuple[str, ...]], ...],
    wind_index: int,
    de_tuple: tuple[str, ...],
    de_indicator: str,
) -> int:
    try:
        score = score_player(
            _counter_from_key(hand_key),
            list(flowers_key),
            _melds_from_key(melds_key),
            int(wind_index),
            set(de_tuple),
            de_indicator,
            winner=False,
        )
        return int(score.get("total", 0))
    except Exception:
        return 0


def tile_efficiency_cache_info() -> dict[str, Any]:
    return {
        "shanten": _shanten_cached.cache_info()._asdict(),
        "effective_tile_codes": _effective_tile_codes_cached.cache_info()._asdict(),
        "current_points": _current_points_cached.cache_info()._asdict(),
        "metric": {
            "hits": _GLOBAL_METRIC_HITS,
            "misses": _GLOBAL_METRIC_MISSES,
            "maxsize": _GLOBAL_METRIC_CACHE_MAX,
            "currsize": len(_GLOBAL_METRIC_CACHE),
        },
        "best_after_discard": {
            "hits": _BEST_AFTER_DISCARD_HITS,
            "misses": _BEST_AFTER_DISCARD_MISSES,
            "maxsize": _BEST_AFTER_DISCARD_CACHE_MAX,
            "currsize": len(_BEST_AFTER_DISCARD_CACHE),
        },
    }


class TileEfficiencyPolicyModel:
    """Independent policy that prioritizes normal-hu tile efficiency."""

    def __init__(self) -> None:
        self.backend = "tile_efficiency"

    def summary(self) -> dict[str, Any]:
        return {"backend": "tile_efficiency", "trained_games": 0, "experience_count": 0, "weights": 0}

    def save(self) -> None:
        return

    def choose_action(
        self,
        observation: dict[str, Any],
        legal_actions: list[Action],
        explore: float = 0.0,
    ) -> Action:
        if not legal_actions:
            return {"type": "pass"}
        hu = [action for action in legal_actions if action.get("type") == "hu"]
        if hu:
            return hu[0]
        if explore > 0 and random.random() < explore:
            return random.choice(legal_actions)
        scored = self.score_actions(observation, legal_actions)
        if not scored:
            return random.choice(legal_actions)
        best_key = scored[0]["rank_key"]
        tied = [item["action"] for item in scored if item["rank_key"] == best_key]
        pass_action = next((action for action in tied if action.get("type") == "pass"), None)
        if pass_action is not None:
            return pass_action
        return random.choice(tied)

    def score_action(self, observation: dict[str, Any], action: Action) -> float:
        key = self.action_rank_key(observation, action)
        return float(key[0] * 1_000_000_000 + key[1] * 1_000_000 + key[2] * 1_000 + key[3])

    def score_actions(self, observation: dict[str, Any], legal_actions: list[Action]) -> list[dict[str, Any]]:
        context = EfficiencyContext.from_observation(observation)
        metrics = [(action, self._action_shanten_metric(observation, action, context=context)) for action in legal_actions]
        best_shanten_key = max((-int(metric["shanten"]) for _, metric in metrics), default=-99)
        ukeire_metrics: list[tuple[Action, Metric]] = []
        for action, metric in metrics:
            if -int(metric["shanten"]) == best_shanten_key:
                metric = self._action_metric(observation, action, include_points=False, include_improvement=False, context=context)
            ukeire_metrics.append((action, metric))
        best_ukeire_key = max(
            (
                int(metric.get("ukeire", 0))
                for _, metric in ukeire_metrics
                if -int(metric["shanten"]) == best_shanten_key
            ),
            default=0,
        )
        improved_metrics: list[tuple[Action, Metric]] = []
        for action, metric in ukeire_metrics:
            if -int(metric["shanten"]) == best_shanten_key and int(metric.get("ukeire", 0)) == best_ukeire_key:
                metric = self._action_metric(observation, action, include_points=False, include_improvement=True, context=context)
            improved_metrics.append((action, metric))
        best_pre_point_key = max(
            (
                (-int(metric["shanten"]), int(metric.get("ukeire", 0)), int(metric.get("improvement", 0)))
                for _, metric in improved_metrics
            ),
            default=(-99, 0, 0),
        )
        best_pre_point_count = sum(
            1
            for _, metric in improved_metrics
            if (-int(metric["shanten"]), int(metric.get("ukeire", 0)), int(metric.get("improvement", 0))) == best_pre_point_key
        )
        scored: list[dict[str, Any]] = []
        for action, metric in improved_metrics:
            pre_point_key = (-int(metric["shanten"]), int(metric.get("ukeire", 0)), int(metric.get("improvement", 0)))
            if best_pre_point_count > 1 and pre_point_key == best_pre_point_key:
                metric = self._action_metric(observation, action, include_points=True, include_improvement=True, context=context)
            rank_key = _rank_key(metric)
            scored.append(
                {
                    "action": action,
                    "label": action_label(action),
                    "score": float(rank_key[0] * 1_000_000_000 + rank_key[1] * 1_000_000 + rank_key[2] * 1_000 + rank_key[3]),
                    "rank_key": rank_key,
                    "metric": metric,
                }
            )
        scored.sort(key=lambda item: item["rank_key"], reverse=True)
        return scored

    def explain_decision(
        self,
        observation: dict[str, Any],
        chosen: Action,
        legal_actions: list[Action],
    ) -> dict[str, Any]:
        scored = self.score_actions(observation, legal_actions)
        if not scored:
            return {"score": 100, "best": None, "chosen": action_label(chosen), "reason": "没有可比较的候选动作。"}
        best = scored[0]
        chosen_item = next((item for item in scored if item["action"] == chosen), best)
        chosen_key = chosen_item["rank_key"]
        best_key = best["rank_key"]
        grade = 100 if chosen_key == best_key else 70
        metric = chosen_item["metric"]
        return {
            "score": grade,
            "chosen": action_label(chosen),
            "chosen_score": round(chosen_item["score"], 2),
            "best": action_label(best["action"]),
            "best_score": round(best["score"], 2),
            "bad": grade < 75,
            "reason": (
                f"牌效优先：向听 {metric.get('shanten')}，"
                f"有效进张 {metric.get('ukeire')}，当前牌面点数 {metric.get('points')}。"
            ),
            "suggestion": "优先选择向听更小、有效进张存量更多的动作；完全相同再看当前牌面点数。",
            "ranked": [
                {
                    "label": item["label"],
                    "score": round(item["score"], 2),
                    "shanten": item["metric"].get("shanten"),
                    "ukeire": item["metric"].get("ukeire"),
                    "improvement": item["metric"].get("improvement"),
                    "points": item["metric"].get("points"),
                }
                for item in scored[:5]
            ],
        }

    def action_rank_key(self, observation: dict[str, Any], action: Action) -> tuple[int, int, int, int]:
        return _rank_key(self.action_metric(observation, action))

    def action_metric(self, observation: dict[str, Any], action: Action) -> Metric:
        return self._action_metric(
            observation,
            action,
            include_points=True,
            include_improvement=True,
            context=EfficiencyContext.from_observation(observation),
        )

    def _action_metric(
        self,
        observation: dict[str, Any],
        action: Action,
        include_points: bool,
        include_improvement: bool,
        context: "EfficiencyContext",
    ) -> Metric:
        if action.get("type") == "hu":
            return {"shanten": -99, "ukeire": 0, "improvement": 0, "points": 1_000_000, "waits": {}, "improvements": {}}
        hand = Counter(context.hand)
        melds = list(context.melds)
        extra_visible: Counter[str] = Counter()
        metric = _simulate_action_metric(observation, action, hand, melds, extra_visible, include_points, include_improvement, context)
        return _apply_bao_risk_penalty(metric, observation, action, hand, context.de_set, include_points)

    def _action_shanten_metric(
        self,
        observation: dict[str, Any],
        action: Action,
        context: "EfficiencyContext",
    ) -> Metric:
        if action.get("type") == "hu":
            return {"shanten": -99, "ukeire": 0, "improvement": 0, "points": 1_000_000, "waits": {}, "improvements": {}}
        return _simulate_action_shanten_metric(observation, action, Counter(context.hand), list(context.melds), Counter(), context)


@dataclass
class EfficiencyContext:
    observation: dict[str, Any]
    de_set: set[str]
    flower_set: set[str]
    public_visible: Counter[str]
    hand: Counter[str]
    melds: list[dict[str, Any]]
    _metric_cache: dict[tuple[tuple[int, ...], tuple[tuple[str, tuple[str, ...]], ...], tuple[tuple[str, int], ...], bool, bool], Metric] = field(default_factory=dict)

    @classmethod
    def from_observation(cls, observation: dict[str, Any]) -> "EfficiencyContext":
        public = observation.get("public", {})
        public_visible: Counter[str] = Counter()
        indicator = public.get("de_indicator")
        if indicator:
            public_visible[str(indicator)] += 1
        for player in public.get("players", []):
            public_visible.update(player.get("discards", []))
            public_visible.update(player.get("flowers", []))
            for meld in player.get("melds", []):
                public_visible.update(meld.get("tiles", []))
        for code in list(public_visible):
            public_visible[code] = min(public_visible[code], PHYSICAL_TILE_COUNTS.get(code, public_visible[code]))
        return cls(
            observation=observation,
            de_set=set(public.get("de_set", [])),
            flower_set=set(public.get("flower_set", [])),
            public_visible=public_visible,
            hand=Counter({code: int(count) for code, count in observation.get("hand", {}).items() if count > 0}),
            melds=_own_melds(observation),
        )

    def metric(
        self,
        hand: Counter[str],
        melds: list[dict[str, Any]],
        extra_visible: Counter[str],
        include_points: bool,
        include_improvement: bool = True,
    ) -> Metric:
        hand_key = _counter_key(hand)
        melds_key = _melds_key(melds)
        extra_key = tuple(sorted((code, int(count)) for code, count in extra_visible.items() if count))
        cache_key = (hand_key, melds_key, extra_key, include_points, include_improvement)
        cached = self._metric_cache.get(cache_key)
        if cached is not None:
            return _copy_metric(cached)
        global_key = self._global_metric_key(hand_key, melds_key, extra_key, include_points, include_improvement)
        global_cached = _global_metric_cache_get(global_key)
        if global_cached is not None:
            metric = _copy_metric(global_cached)
            self._metric_cache[cache_key] = _copy_metric(metric)
            return metric
        current_shanten = shanten(hand, self.de_set)
        waits = self.effective_tiles(hand, current_shanten, extra_visible)
        improvements = self.improvement_tiles(hand, current_shanten, sum(waits.values()), extra_visible) if include_improvement else {}
        point_score = current_points(self.observation, hand, melds) if include_points else 0
        metric = {
            "shanten": current_shanten,
            "ukeire": sum(waits.values()),
            "waits": waits,
            "improvement": sum(improvements.values()),
            "improvements": improvements,
            "points": point_score,
            "hand": dict(hand),
            "melds": list(melds),
        }
        self._metric_cache[cache_key] = _copy_metric(metric)
        _global_metric_cache_set(global_key, metric)
        return metric

    def _global_metric_key(
        self,
        hand_key: tuple[int, ...],
        melds_key: tuple[tuple[str, tuple[str, ...]], ...],
        extra_key: tuple[tuple[str, int], ...],
        include_points: bool,
        include_improvement: bool,
    ) -> tuple[Any, ...]:
        public = self.observation.get("public", {})
        seat = int(self.observation.get("seat", 0))
        players = public.get("players", [])
        wind_index = seat
        if 0 <= seat < len(players):
            try:
                wind_index = int(players[seat].get("wind_index", seat))
            except (TypeError, ValueError):
                wind_index = seat
        return (
            hand_key,
            melds_key,
            tuple(sorted((code, int(count)) for code, count in self.public_visible.items() if count)),
            extra_key,
            tuple(sorted(self.de_set)),
            tuple(sorted(self.flower_set)),
            tuple(sorted(str(code) for code in self.observation.get("flowers", []))),
            int(wind_index),
            str(public.get("de_indicator", "")),
            bool(public.get("bao_phase")),
            tuple(sorted(str(code) for code in public.get("discarded_tile_kinds", []))),
            bool(include_points),
            bool(include_improvement),
        )

    def effective_tiles(self, hand: Counter[str], base_shanten: int, extra_visible: Counter[str]) -> dict[str, int]:
        visible = Counter(self.public_visible)
        visible.update(hand)
        visible.update(extra_visible)
        waits: dict[str, int] = {}
        for code in _effective_tile_codes_cached(
            _counter_key(hand),
            tuple(sorted(self.de_set)),
            tuple(sorted(self.flower_set)),
            base_shanten,
        ):
            remaining = max(0, PHYSICAL_TILE_COUNTS.get(code, 0) - min(visible.get(code, 0), PHYSICAL_TILE_COUNTS.get(code, 0)))
            if remaining > 0:
                waits[code] = remaining
        return waits

    def improvement_tiles(
        self,
        hand: Counter[str],
        base_shanten: int,
        base_ukeire: int,
        extra_visible: Counter[str],
    ) -> dict[str, int]:
        visible = Counter(self.public_visible)
        visible.update(hand)
        visible.update(extra_visible)
        effective_codes = set(
            _effective_tile_codes_cached(
                _counter_key(hand),
                tuple(sorted(self.de_set)),
                tuple(sorted(self.flower_set)),
                base_shanten,
            )
        )
        improvements: dict[str, int] = {}
        for code in TILE_ORDER:
            if code in FLOWERS and code not in self.de_set:
                continue
            if code in self.flower_set and code not in self.de_set:
                continue
            remaining = max(0, PHYSICAL_TILE_COUNTS.get(code, 0) - min(visible.get(code, 0), PHYSICAL_TILE_COUNTS.get(code, 0)))
            if remaining <= 0:
                continue
            if code in effective_codes:
                continue
            candidate = Counter(hand)
            candidate[code] += 1
            best = _best_after_draw_discard_metric(
                self.observation,
                candidate,
                Counter(extra_visible),
                self.de_set,
                context=self,
                target_shanten=base_shanten,
            )
            if int(best.get("shanten", 99)) == base_shanten and int(best.get("ukeire", 0)) > int(base_ukeire):
                improvements[code] = remaining
        return improvements


def _simulate_action_metric(
    observation: dict[str, Any],
    action: Action,
    hand: Counter[str],
    melds: list[dict[str, Any]],
    extra_visible: Counter[str],
    include_points: bool = True,
    include_improvement: bool = True,
    context: EfficiencyContext | None = None,
) -> Metric:
    kind = action.get("type")
    tile = action.get("tile")
    public = observation.get("public", {})
    de_set = set(public.get("de_set", []))

    if kind == "pass":
        return context.metric(hand, melds, extra_visible, include_points, include_improvement) if context else hand_metric(observation, hand, melds, extra_visible, include_points, include_improvement)

    if kind == "discard" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile])
        next_extra = Counter(extra_visible)
        next_extra[tile] += 1
        return context.metric(next_hand, melds, next_extra, include_points, include_improvement) if context else hand_metric(observation, next_hand, melds, next_extra, include_points, include_improvement)

    if kind == "an_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 4)
        next_melds = list(melds) + [{"type": "an_gang", "tile": tile, "tiles": [tile] * 4, "from": observation.get("seat", 0)}]
        next_extra = Counter(extra_visible)
        next_extra[tile] += 4
        return context.metric(next_hand, next_melds, next_extra, include_points, include_improvement) if context else hand_metric(observation, next_hand, next_melds, next_extra, include_points, include_improvement)

    if kind == "bu_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile])
        next_melds = _upgrade_peng_to_bu_gang(melds, tile)
        next_extra = Counter(extra_visible)
        next_extra[tile] += 1
        return context.metric(next_hand, next_melds, next_extra, include_points, include_improvement) if context else hand_metric(observation, next_hand, next_melds, next_extra, include_points, include_improvement)

    if kind == "ming_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 3)
        next_melds = list(melds) + [{"type": "ming_gang", "tile": tile, "tiles": [tile] * 4, "from": None}]
        next_extra = Counter(extra_visible)
        next_extra[tile] += 3
        return context.metric(next_hand, next_melds, next_extra, include_points, include_improvement) if context else hand_metric(observation, next_hand, next_melds, next_extra, include_points, include_improvement)

    if kind == "peng" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 2)
        next_melds = list(melds) + [{"type": "peng", "tile": tile, "tiles": [tile] * 3, "from": None}]
        next_extra = Counter(extra_visible)
        next_extra[tile] += 2
        return _best_forced_discard_metric(
            observation,
            next_hand,
            next_melds,
            next_extra,
            de_set,
            include_points,
            include_improvement,
            context,
        )

    if kind == "chi" and tile:
        chi_tiles = list(action.get("tiles", []))
        next_hand = Counter(hand)
        _remove_tiles(next_hand, chi_tiles)
        tiles = sorted([tile] + chi_tiles, key=lambda code: _KEY_INDEX.get(code, 999))
        next_melds = list(melds) + [{"type": "chi", "tile": tile, "tiles": tiles, "from": None}]
        next_extra = Counter(extra_visible)
        next_extra.update(chi_tiles)
        return _best_forced_discard_metric(
            observation,
            next_hand,
            next_melds,
            next_extra,
            de_set,
            include_points,
            include_improvement,
            context,
        )

    return context.metric(hand, melds, extra_visible, include_points, include_improvement) if context else hand_metric(observation, hand, melds, extra_visible, include_points, include_improvement)


def _simulate_action_shanten_metric(
    observation: dict[str, Any],
    action: Action,
    hand: Counter[str],
    melds: list[dict[str, Any]],
    extra_visible: Counter[str],
    context: EfficiencyContext,
) -> Metric:
    kind = action.get("type")
    tile = action.get("tile")

    if kind == "pass":
        return _shanten_metric(hand, melds, context)

    if kind == "discard" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile])
        return _shanten_metric(next_hand, melds, context)

    if kind == "an_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 4)
        next_melds = list(melds) + [{"type": "an_gang", "tile": tile, "tiles": [tile] * 4, "from": observation.get("seat", 0)}]
        return _shanten_metric(next_hand, next_melds, context)

    if kind == "bu_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile])
        return _shanten_metric(next_hand, _upgrade_peng_to_bu_gang(melds, tile), context)

    if kind == "ming_gang" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 3)
        next_melds = list(melds) + [{"type": "ming_gang", "tile": tile, "tiles": [tile] * 4, "from": None}]
        return _shanten_metric(next_hand, next_melds, context)

    if kind == "peng" and tile:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [tile] * 2)
        next_melds = list(melds) + [{"type": "peng", "tile": tile, "tiles": [tile] * 3, "from": None}]
        return _best_forced_discard_shanten_metric(next_hand, next_melds, context)

    if kind == "chi" and tile:
        chi_tiles = list(action.get("tiles", []))
        next_hand = Counter(hand)
        _remove_tiles(next_hand, chi_tiles)
        tiles = sorted([tile] + chi_tiles, key=lambda code: _KEY_INDEX.get(code, 999))
        next_melds = list(melds) + [{"type": "chi", "tile": tile, "tiles": tiles, "from": None}]
        return _best_forced_discard_shanten_metric(next_hand, next_melds, context)

    return _shanten_metric(hand, melds, context)


def _best_forced_discard_metric(
    observation: dict[str, Any],
    hand: Counter[str],
    melds: list[dict[str, Any]],
    extra_visible: Counter[str],
    de_set: set[str],
    include_points: bool = True,
    include_improvement: bool = True,
    context: EfficiencyContext | None = None,
) -> Metric:
    discards = legal_discards(hand, de_set)
    if not discards:
        return context.metric(hand, melds, extra_visible, include_points, include_improvement) if context else hand_metric(observation, hand, melds, extra_visible, include_points, include_improvement)
    best: Metric | None = None
    for discard in discards:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [discard])
        next_extra = Counter(extra_visible)
        next_extra[discard] += 1
        metric = context.metric(next_hand, melds, next_extra, include_points, include_improvement) if context else hand_metric(observation, next_hand, melds, next_extra, include_points, include_improvement)
        if best is None or _rank_key(metric) > _rank_key(best):
            best = metric
            best["forced_discard"] = discard
    assert best is not None
    return best


def _best_forced_discard_shanten_metric(
    hand: Counter[str],
    melds: list[dict[str, Any]],
    context: EfficiencyContext,
) -> Metric:
    discards = legal_discards(hand, context.de_set)
    if not discards:
        return _shanten_metric(hand, melds, context)
    best: Metric | None = None
    for discard in discards:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [discard])
        metric = _shanten_metric(next_hand, melds, context)
        if best is None or _rank_key(metric) > _rank_key(best):
            best = metric
            best["forced_discard"] = discard
    assert best is not None
    return best


def _best_after_draw_discard_metric(
    observation: dict[str, Any],
    hand: Counter[str],
    extra_visible: Counter[str],
    de_set: set[str],
    context: EfficiencyContext | None = None,
    target_shanten: int | None = None,
) -> Metric:
    cache_key = _best_after_discard_cache_key(observation, hand, extra_visible, de_set, context, target_shanten)
    cached = _best_after_discard_cache_get(cache_key)
    if cached is not None:
        return cached
    discards = legal_discards(hand, de_set)
    if not discards:
        metric = context.metric(hand, [], extra_visible, include_points=False, include_improvement=False) if context else hand_metric(
            observation,
            hand,
            [],
            extra_visible,
            include_points=False,
            include_improvement=False,
        )
        _best_after_discard_cache_set(cache_key, metric)
        return metric
    if target_shanten is not None:
        candidates: list[tuple[str, Counter[str], Counter[str]]] = []
        best_shanten = 99
        best_shanten_hand: Counter[str] | None = None
        best_shanten_extra: Counter[str] | None = None
        for discard in discards:
            next_hand = Counter(hand)
            _remove_tiles(next_hand, [discard])
            next_shanten = shanten(next_hand, de_set)
            if next_shanten < best_shanten:
                best_shanten = next_shanten
                best_shanten_hand = next_hand
                best_shanten_extra = Counter(extra_visible)
                best_shanten_extra[discard] += 1
            if next_shanten != target_shanten:
                continue
            next_extra = Counter(extra_visible)
            next_extra[discard] += 1
            candidates.append((discard, next_hand, next_extra))
        if not candidates:
            fallback_hand = best_shanten_hand if best_shanten_hand is not None else hand
            fallback_extra = best_shanten_extra if best_shanten_extra is not None else extra_visible
            metric = {
                "shanten": best_shanten,
                "ukeire": 0,
                "waits": {},
                "improvement": 0,
                "improvements": {},
                "points": 0,
                "hand": dict(fallback_hand),
                "melds": [],
                "extra_visible": dict(fallback_extra),
            }
            _best_after_discard_cache_set(cache_key, metric)
            return metric
        best: Metric | None = None
        for discard, next_hand, next_extra in candidates:
            metric = context.metric(next_hand, [], next_extra, include_points=False, include_improvement=False) if context else hand_metric(
                observation,
                next_hand,
                [],
                next_extra,
                include_points=False,
                include_improvement=False,
            )
            if best is None or _rank_key(metric) > _rank_key(best):
                best = metric
                best["forced_discard"] = discard
        assert best is not None
        _best_after_discard_cache_set(cache_key, best)
        return best
    best: Metric | None = None
    for discard in discards:
        next_hand = Counter(hand)
        _remove_tiles(next_hand, [discard])
        next_extra = Counter(extra_visible)
        next_extra[discard] += 1
        metric = context.metric(next_hand, [], next_extra, include_points=False, include_improvement=False) if context else hand_metric(
            observation,
            next_hand,
            [],
            next_extra,
            include_points=False,
            include_improvement=False,
        )
        if best is None or _rank_key(metric) > _rank_key(best):
            best = metric
    assert best is not None
    _best_after_discard_cache_set(cache_key, best)
    return best


def _shanten_metric(hand: Counter[str], melds: list[dict[str, Any]], context: EfficiencyContext) -> Metric:
    base_hand = Counter({code: int(count) for code, count in hand.items() if count > 0})
    return {
        "shanten": shanten(base_hand, context.de_set),
        "ukeire": 0,
        "waits": {},
        "improvement": 0,
        "improvements": {},
        "points": 0,
        "hand": dict(base_hand),
        "melds": list(melds),
    }


def _apply_bao_risk_penalty(
    metric: Metric,
    observation: dict[str, Any],
    action: Action,
    hand_before_action: Counter[str],
    de_set: set[str],
    include_points: bool,
) -> Metric:
    risk = _bao_risk_penalty(observation, action, hand_before_action, de_set)
    if risk <= 0:
        return metric
    updated = dict(metric)
    updated["bao_risk_penalty"] = risk
    if include_points:
        updated["points"] = int(updated.get("points", 0)) - risk
    return updated


def _bao_risk_penalty(
    observation: dict[str, Any],
    action: Action,
    hand_before_action: Counter[str],
    de_set: set[str],
) -> int:
    public = observation.get("public", {})
    kind = action.get("type")
    tile = str(action.get("tile", ""))
    risk_units = 0
    if kind == "discard" and tile:
        if public.get("bao_phase") and tile not in set(public.get("discarded_tile_kinds", [])):
            risk_units += 1
        if tile in {"zhong", "fa"} and shanten(hand_before_action, de_set) > 1:
            risk_units += 1
    if kind in {"chi", "peng", "ming_gang"} and public.get("bao_phase"):
        risk_units += 1
    return risk_units * BAO_RISK_POINT_PENALTY


def _rank_key(metric: Metric) -> tuple[int, int, int, int]:
    return (
        -int(metric.get("shanten", 99)),
        int(metric.get("ukeire", 0)),
        int(metric.get("improvement", 0)),
        int(metric.get("points", 0)),
    )


def _target_concealed_groups(concealed_total: int) -> int:
    if concealed_total <= 0:
        return 0
    if concealed_total % 3 == 2:
        return max(0, (concealed_total - 2) // 3)
    if concealed_total % 3 == 1:
        return max(0, (concealed_total - 1) // 3)
    return max(0, concealed_total // 3)


def _has_normal_pair(counts: Counter[str], wilds: int) -> bool:
    if any(count >= 2 for count in counts.values()):
        return True
    return wilds >= 1 and any(count >= 1 for count in counts.values())


def _compact_block_keys(counts: Counter[str]) -> tuple[tuple[tuple[int, ...], bool], ...]:
    blocks: list[tuple[tuple[int, ...], bool]] = []
    for suit in ("m", "t", "b"):
        block = tuple(int(counts.get(f"{suit}{rank}", 0)) for rank in range(1, 10))
        if any(block):
            blocks.append((block, True))
    honors = tuple(int(counts.get(code, 0)) for code in _NON_SUITED_ORDER)
    if any(honors):
        blocks.append((honors, False))
    return tuple(blocks)


@lru_cache(maxsize=None)
def _compact_block_states(
    counts: tuple[int, ...],
    suited: bool,
    wilds: int,
    target_groups: int,
) -> tuple[tuple[int, int, int], ...]:
    if not any(counts):
        return _wild_only_states(wilds, target_groups)

    first = next(index for index, count in enumerate(counts) if count > 0)
    first_count = counts[first]
    states: set[tuple[int, int, int]] = set()

    def after_removing(indices: tuple[int, ...]) -> tuple[int, ...]:
        updated = list(counts)
        for index in indices:
            updated[index] -= 1
        return tuple(updated)

    def add_child(
        child_counts: tuple[int, ...],
        child_wilds: int,
        dm: int = 0,
        dt: int = 0,
        dp: int = 0,
    ) -> None:
        for melds, taatsu, pair in _compact_block_states(
            child_counts,
            suited,
            child_wilds,
            target_groups,
        ):
            states.add(_normalize_state(melds + dm, taatsu + dt, pair + dp, target_groups))

    add_child(after_removing((first,)), wilds)

    if first_count >= 2:
        after = after_removing((first, first))
        add_child(after, wilds, dp=1)
        add_child(after, wilds, dt=1)
    if wilds >= 1:
        after = after_removing((first,))
        add_child(after, wilds - 1, dp=1)
        add_child(after, wilds - 1, dt=1)

    use_real = min(3, first_count)
    need = 3 - use_real
    if need <= wilds:
        add_child(after_removing((first,) * use_real), wilds - need, dm=1)

    if suited:
        for start in (first - 2, first - 1, first):
            if start < 0 or start > 6:
                continue
            sequence = (start, start + 1, start + 2)
            updated = list(counts)
            missing = 0
            for index in sequence:
                if updated[index] > 0:
                    updated[index] -= 1
                else:
                    missing += 1
            if missing <= wilds:
                add_child(tuple(updated), wilds - missing, dm=1)

        for other in (first + 1, first + 2):
            if other < len(counts) and counts[other] > 0:
                add_child(after_removing((first, other)), wilds, dt=1)
        if wilds >= 1:
            add_child(after_removing((first,)), wilds - 1, dt=1)

    return tuple(states)


@lru_cache(maxsize=200_000)
def _split_block_keys(key: tuple[int, ...]) -> tuple[tuple[int, ...], ...]:
    blocks: list[tuple[int, ...]] = []
    for suit in ("m", "t", "b"):
        block = [0] * len(_KEY_ORDER)
        has_tile = False
        for index, code in enumerate(_KEY_ORDER):
            if is_suited(code) and code.startswith(suit) and key[index] > 0:
                block[index] = key[index]
                has_tile = True
        if has_tile:
            blocks.append(tuple(block))

    honor_block = [0] * len(_KEY_ORDER)
    has_honor = False
    for index, code in enumerate(_KEY_ORDER):
        if key[index] > 0 and not is_suited(code):
            honor_block[index] = key[index]
            has_honor = True
    if has_honor:
        blocks.append(tuple(honor_block))
    return tuple(blocks)


def _merge_state(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    target_groups: int,
) -> tuple[int, int, int]:
    melds = left[0] + right[0]
    taatsu = left[1] + right[1]
    pair = max(left[2], right[2])
    return _normalize_state(melds, taatsu, pair, target_groups)


def _counter_key(counts: Counter[str]) -> tuple[int, ...]:
    return tuple(int(counts.get(code, 0)) for code in _KEY_ORDER)


def _counter_from_key(key: tuple[int, ...]) -> Counter[str]:
    return Counter({code: count for code, count in zip(_KEY_ORDER, key) if count > 0})


def _melds_key(melds: list[dict[str, Any]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    rows = []
    for meld in melds:
        rows.append(
            (
                str(meld.get("type", "")),
                tuple(sorted((str(code) for code in meld.get("tiles", [])), key=lambda code: _KEY_INDEX.get(code, 999))),
            )
        )
    return tuple(sorted(rows))


def _melds_from_key(melds_key: tuple[tuple[str, tuple[str, ...]], ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for kind, tiles in melds_key:
        tile = tiles[0] if tiles else ""
        rows.append({"type": kind, "tile": tile, "tiles": list(tiles), "from": None})
    return rows


def _copy_metric(metric: Metric) -> Metric:
    copied = dict(metric)
    for key in ("waits", "improvements", "hand", "extra_visible"):
        if isinstance(copied.get(key), dict):
            copied[key] = dict(copied[key])
    if isinstance(copied.get("melds"), list):
        copied["melds"] = [dict(meld) for meld in copied["melds"]]
    return copied


def _global_metric_cache_get(key: tuple[Any, ...]) -> Metric | None:
    global _GLOBAL_METRIC_HITS, _GLOBAL_METRIC_MISSES
    with _GLOBAL_CACHE_LOCK:
        cached = _GLOBAL_METRIC_CACHE.get(key)
        if cached is None:
            _GLOBAL_METRIC_MISSES += 1
            return None
        _GLOBAL_METRIC_HITS += 1
        _GLOBAL_METRIC_CACHE.move_to_end(key)
        return _copy_metric(cached)


def _global_metric_cache_set(key: tuple[Any, ...], metric: Metric) -> None:
    with _GLOBAL_CACHE_LOCK:
        _GLOBAL_METRIC_CACHE[key] = _copy_metric(metric)
        _GLOBAL_METRIC_CACHE.move_to_end(key)
        while len(_GLOBAL_METRIC_CACHE) > _GLOBAL_METRIC_CACHE_MAX:
            _GLOBAL_METRIC_CACHE.popitem(last=False)


def _best_after_discard_cache_key(
    observation: dict[str, Any],
    hand: Counter[str],
    extra_visible: Counter[str],
    de_set: set[str],
    context: EfficiencyContext | None,
    target_shanten: int | None,
) -> tuple[Any, ...]:
    if context is not None:
        public_visible = context.public_visible
        flower_set = context.flower_set
    else:
        public_visible = visible_counts(observation, Counter())
        flower_set = set(observation.get("public", {}).get("flower_set", []))
    return (
        _counter_key(hand),
        tuple(sorted((code, int(count)) for code, count in extra_visible.items() if count)),
        tuple(sorted(str(code) for code in de_set)),
        tuple(sorted((code, int(count)) for code, count in public_visible.items() if count)),
        tuple(sorted(str(code) for code in flower_set)),
        target_shanten,
    )


def _best_after_discard_cache_get(key: tuple[Any, ...]) -> Metric | None:
    global _BEST_AFTER_DISCARD_HITS, _BEST_AFTER_DISCARD_MISSES
    with _GLOBAL_CACHE_LOCK:
        cached = _BEST_AFTER_DISCARD_CACHE.get(key)
        if cached is None:
            _BEST_AFTER_DISCARD_MISSES += 1
            return None
        _BEST_AFTER_DISCARD_HITS += 1
        _BEST_AFTER_DISCARD_CACHE.move_to_end(key)
        return _copy_metric(cached)


def _best_after_discard_cache_set(key: tuple[Any, ...], metric: Metric) -> None:
    with _GLOBAL_CACHE_LOCK:
        _BEST_AFTER_DISCARD_CACHE[key] = _copy_metric(metric)
        _BEST_AFTER_DISCARD_CACHE.move_to_end(key)
        while len(_BEST_AFTER_DISCARD_CACHE) > _BEST_AFTER_DISCARD_CACHE_MAX:
            _BEST_AFTER_DISCARD_CACHE.popitem(last=False)


def _remove_tiles(hand: Counter[str], tiles: list[str]) -> None:
    for code in tiles:
        hand[code] -= 1
        if hand[code] <= 0:
            hand.pop(code, None)


def _own_melds(observation: dict[str, Any]) -> list[dict[str, Any]]:
    seat = int(observation.get("seat", 0))
    players = observation.get("public", {}).get("players", [])
    if 0 <= seat < len(players):
        return [dict(meld) for meld in players[seat].get("melds", [])]
    return []


def _upgrade_peng_to_bu_gang(melds: list[dict[str, Any]], tile: str) -> list[dict[str, Any]]:
    updated = [dict(meld) for meld in melds]
    for meld in updated:
        if meld.get("type") == "peng" and meld.get("tile") == tile:
            meld["type"] = "bu_gang"
            meld["tiles"] = list(meld.get("tiles", [])) + [tile]
            return updated
    return updated + [{"type": "bu_gang", "tile": tile, "tiles": [tile] * 4, "from": None}]


@lru_cache(maxsize=None)
def _wild_only_states(wilds: int, target_groups: int) -> tuple[tuple[int, int, int], ...]:
    states: set[tuple[int, int, int]] = {(0, 0, 0)}
    if wilds <= 0:
        return tuple(states)
    for melds, taatsu, pair in _wild_only_states(wilds - 1, target_groups):
        states.add(_normalize_state(melds, taatsu, pair, target_groups))
    if wilds >= 2:
        for melds, taatsu, pair in _wild_only_states(wilds - 2, target_groups):
            states.add(_normalize_state(melds, taatsu + 1, pair, target_groups))
    return tuple(states)


@lru_cache(maxsize=None)
def _block_states(
    key: tuple[int, ...],
    wilds: int,
    target_groups: int,
) -> tuple[tuple[int, int, int], ...]:
    counts = Counter({code: count for code, count in zip(_KEY_ORDER, key) if count})
    if not counts:
        return _wild_only_states(wilds, target_groups)

    first = next(code for code in _KEY_ORDER if counts.get(code, 0) > 0)
    first_count = counts[first]
    states: set[tuple[int, int, int]] = set()

    def add_child(child_counts: Counter[str], child_wilds: int, dm: int = 0, dt: int = 0, dp: int = 0) -> None:
        for melds, taatsu, pair in _block_states(_counter_key(child_counts), child_wilds, target_groups):
            states.add(_normalize_state(melds + dm, taatsu + dt, pair + dp, target_groups))

    skipped = Counter(counts)
    _remove_tiles(skipped, [first])
    add_child(skipped, wilds)

    if first_count >= 2:
        after = Counter(counts)
        _remove_tiles(after, [first, first])
        add_child(after, wilds, dp=1)
        add_child(after, wilds, dt=1)
    if first_count >= 1 and wilds >= 1:
        after = Counter(counts)
        _remove_tiles(after, [first])
        add_child(after, wilds - 1, dp=1)
        add_child(after, wilds - 1, dt=1)

    use_real = min(3, first_count)
    need = 3 - use_real
    if need <= wilds:
        after = Counter(counts)
        _remove_tiles(after, [first] * use_real)
        add_child(after, wilds - need, dm=1)

    if is_suited(first):
        rank = int(first[1:])
        suit = first[0]
        for start in (rank - 2, rank - 1, rank):
            if start < 1 or start > 7:
                continue
            seq = [f"{suit}{start + offset}" for offset in range(3)]
            if first not in seq:
                continue
            after = Counter(counts)
            missing = 0
            for code in seq:
                if after.get(code, 0) > 0:
                    _remove_tiles(after, [code])
                else:
                    missing += 1
            if missing <= wilds:
                add_child(after, wilds - missing, dm=1)

        for other_rank in (rank + 1, rank + 2):
            if other_rank <= 9:
                other = f"{suit}{other_rank}"
                if counts.get(other, 0) > 0:
                    after = Counter(counts)
                    _remove_tiles(after, [first, other])
                    add_child(after, wilds, dt=1)
        if wilds >= 1:
            after = Counter(counts)
            _remove_tiles(after, [first])
            add_child(after, wilds - 1, dt=1)

    return tuple(states)


def _normalize_state(melds: int, taatsu: int, pair: int, target_groups: int) -> tuple[int, int, int]:
    melds = min(max(0, melds), target_groups)
    taatsu = min(max(0, taatsu), max(0, target_groups - melds))
    pair = 1 if pair else 0
    return melds, taatsu, pair
