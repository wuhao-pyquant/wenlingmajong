from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path
from typing import Any

from .tiles import DRAGONS, SUITS, TILE_BY_CODE, WIND_BY_SEAT, is_dragon, is_honor, is_suited, is_terminal, tile_name


Action = dict[str, Any]


def observation_wind_code(observation: dict[str, Any], seat: int | None = None) -> str:
    public = observation.get("public", {})
    players = public.get("players", [])
    try:
        own_seat = int(observation.get("seat", 0) if seat is None else seat)
    except (TypeError, ValueError):
        own_seat = 0
    wind_index = own_seat
    if 0 <= own_seat < len(players):
        try:
            wind_index = int(players[own_seat].get("wind_index", own_seat))
        except (TypeError, ValueError):
            wind_index = own_seat
    else:
        try:
            wind_index = (own_seat - int(public.get("dealer", 0))) % 4
        except (TypeError, ValueError):
            wind_index = own_seat
    return WIND_BY_SEAT.get(wind_index % 4, "east")


def action_label(action: Action) -> str:
    kind = action.get("type")
    tile = action.get("tile")
    if kind == "discard":
        return f"打出 {tile_name(tile)}"
    if kind == "hu":
        return "和牌"
    if kind == "pass":
        return "过"
    if kind == "an_gang":
        return f"暗杠 {tile_name(tile)}"
    if kind == "bu_gang":
        return f"补杠 {tile_name(tile)}"
    if kind == "ming_gang":
        return f"明杠 {tile_name(tile)}"
    if kind == "peng":
        return f"碰 {tile_name(tile)}"
    if kind == "chi":
        names = "、".join(tile_name(code) for code in action.get("tiles", []))
        return f"吃 {names}"
    return str(action)


class LinearPolicyModel:
    """Small local policy/value model.

    It intentionally stays dependency-free. The architecture mirrors the training
    document at a practical scale: every decision is made from a filtered
    observation, while self-play centrally updates one shared parameter set.
    """

    def __init__(self, model_path: str | Path):
        self.path = Path(model_path)
        self.weights: dict[str, float] = {}
        self.trained_games = 0
        self.experience_count = 0
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.learning_rate = 0.012
        self.version = 1

    @classmethod
    def load(cls, model_path: str | Path) -> "LinearPolicyModel":
        model = cls(model_path)
        if model.path.exists():
            data = json.loads(model.path.read_text(encoding="utf-8"))
            model.weights = {str(k): float(v) for k, v in data.get("weights", {}).items()}
            model.trained_games = int(data.get("trained_games", 0))
            model.experience_count = int(data.get("experience_count", 0))
            model.created_at = float(data.get("created_at", time.time()))
            model.updated_at = float(data.get("updated_at", model.created_at))
            model.learning_rate = float(data.get("learning_rate", model.learning_rate))
            model.version = int(data.get("version", 1))
        else:
            model.save()
        return model

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": time.time(),
            "trained_games": self.trained_games,
            "experience_count": self.experience_count,
            "learning_rate": self.learning_rate,
            "weights": dict(sorted(self.weights.items())),
        }
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self.updated_at = data["updated_at"]

    def reset(self) -> None:
        self.weights.clear()
        self.trained_games = 0
        self.experience_count = 0
        self.created_at = time.time()
        self.updated_at = self.created_at
        self.save()

    def feature_vector(self, observation: dict[str, Any], action: Action) -> dict[str, float]:
        kind = action.get("type", "unknown")
        features: dict[str, float] = {f"bias:{kind}": 1.0}
        hand = {code: int(count) for code, count in observation.get("hand", {}).items()}
        public = observation.get("public", {})
        wall_remaining = int(public.get("wall_remaining", 0))
        seat = int(observation.get("seat", 0))
        own_wind = observation_wind_code(observation, seat)

        if kind == "discard":
            tile = action["tile"]
            tile_def = TILE_BY_CODE[tile]
            count = hand.get(tile, 0)
            features["discard"] = 1.0
            features[f"discard:suit:{tile_def.suit}"] = 1.0
            features[f"discard:count:{min(count, 4)}"] = 1.0
            if is_terminal(tile):
                features["discard:terminal"] = 1.0
            if is_honor(tile):
                features["discard:honor"] = 1.0
            if tile in DRAGONS:
                features["discard:dragon"] = 1.0
            if tile == own_wind:
                features["discard:own_wind"] = 1.0
            if is_suited(tile):
                rank = tile_def.rank or 0
                left = hand.get(f"{tile_def.suit}{rank - 1}", 0) if rank > 1 else 0
                right = hand.get(f"{tile_def.suit}{rank + 1}", 0) if rank < 9 else 0
                gap_left = hand.get(f"{tile_def.suit}{rank - 2}", 0) if rank > 2 else 0
                gap_right = hand.get(f"{tile_def.suit}{rank + 2}", 0) if rank < 8 else 0
                if left + right + gap_left + gap_right == 0 and count == 1:
                    features["discard:isolated"] = 1.0
                if left and right:
                    features["discard:center_link"] = 1.0
                if rank in (4, 5, 6):
                    features["discard:middle"] = 1.0
            if wall_remaining <= 31:
                features["discard:late"] = 1.0

        elif kind in {"an_gang", "bu_gang", "ming_gang"}:
            tile = action["tile"]
            features["kong"] = 1.0
            if is_terminal(tile) or is_honor(tile):
                features["kong:valuable"] = 1.0
            if wall_remaining <= 24:
                features["kong:late"] = 1.0

        elif kind in {"peng", "chi"}:
            features[f"claim:{kind}"] = 1.0
            if wall_remaining <= 31:
                features["claim:late"] = 1.0

        elif kind == "hu":
            features["hu"] = 1.0

        elif kind == "pass":
            features["pass"] = 1.0

        return features

    def heuristic(self, observation: dict[str, Any], action: Action) -> float:
        kind = action.get("type")
        if kind == "hu":
            return 100.0
        if kind == "pass":
            return 0.0
        public = observation.get("public", {})
        hand = observation.get("hand", {})
        seat = int(observation.get("seat", 0))
        own_wind = observation_wind_code(observation, seat)
        wall_remaining = int(public.get("wall_remaining", 0))

        if kind == "discard":
            tile = action["tile"]
            count = int(hand.get(tile, 0))
            score = 18.0
            if count >= 2:
                score -= 7.0 * (count - 1)
            if is_honor(tile):
                score += 4.0
                if tile in DRAGONS or tile == own_wind:
                    score -= 8.0
            if is_terminal(tile):
                score += 2.5
            if is_suited(tile):
                tile_def = TILE_BY_CODE[tile]
                rank = tile_def.rank or 0
                neighbors = 0
                for delta in (-2, -1, 1, 2):
                    nr = rank + delta
                    if 1 <= nr <= 9:
                        neighbors += int(hand.get(f"{tile_def.suit}{nr}", 0))
                if neighbors == 0:
                    score += 10.0
                if rank in (4, 5, 6):
                    score -= 3.5
            return score

        if kind in {"an_gang", "bu_gang", "ming_gang"}:
            score = 17.0
            tile = action.get("tile")
            if tile and (is_terminal(tile) or is_honor(tile)):
                score += 5.0
            if wall_remaining <= 24:
                score -= 8.0
            return score

        if kind == "peng":
            tile = action.get("tile")
            score = 9.0
            if tile and (is_dragon(tile) or tile == own_wind):
                score += 8.0
            return score

        if kind == "chi":
            return 7.0

        return 0.0

    def score_action(self, observation: dict[str, Any], action: Action) -> float:
        score = self.heuristic(observation, action)
        for feature, value in self.feature_vector(observation, action).items():
            score += self.weights.get(feature, 0.0) * value
        return score

    def score_actions(self, observation: dict[str, Any], legal_actions: list[Action]) -> list[dict[str, Any]]:
        scored = []
        for action in legal_actions:
            scored.append({"action": action, "label": action_label(action), "score": self.score_action(observation, action)})
        scored.sort(key=lambda item: item["score"], reverse=True)
        return scored

    def choose_action(self, observation: dict[str, Any], legal_actions: list[Action], explore: float = 0.02) -> Action:
        if not legal_actions:
            return {"type": "pass"}
        if random.random() < explore:
            return random.choice(legal_actions)
        scored = self.score_actions(observation, legal_actions)
        if explore > 0.0 and len(scored) > 1:
            # Softmax sampling keeps self-play from becoming deterministic too early.
            temp = max(2.5, 10.0 * explore)
            values = [math.exp((item["score"] - scored[0]["score"]) / temp) for item in scored]
            total = sum(values)
            pick = random.random() * total
            acc = 0.0
            for item, value in zip(scored, values):
                acc += value
                if acc >= pick:
                    return item["action"]
        return scored[0]["action"]

    def update_from_episode(self, decisions: list[dict[str, Any]], final_rewards: dict[int, float]) -> None:
        if not decisions:
            self.trained_games += 1
            return
        for decision in decisions:
            player = int(decision["player"])
            reward = max(-2.0, min(1.5, final_rewards.get(player, 0.0) / 80.0))
            if reward == 0:
                continue
            legal = decision.get("legal_actions", [])
            if not legal:
                continue
            observation = decision["observation"]
            chosen = decision["action"]
            chosen_features = self.feature_vector(observation, chosen)
            for feature, value in chosen_features.items():
                self.weights[feature] = self.weights.get(feature, 0.0) + self.learning_rate * reward * value
            # Small counter-update for the current top alternative if it differs.
            alternatives = self.score_actions(observation, legal)
            for item in alternatives:
                if item["action"] != chosen:
                    for feature, value in self.feature_vector(observation, item["action"]).items():
                        self.weights[feature] = self.weights.get(feature, 0.0) - self.learning_rate * reward * value * 0.18
                    break
            self.experience_count += 1
        self.trained_games += 1

    def explain_decision(self, observation: dict[str, Any], chosen: Action, legal_actions: list[Action]) -> dict[str, Any]:
        scored = self.score_actions(observation, legal_actions)
        if not scored:
            return {"score": 100, "best": None, "chosen": action_label(chosen), "reason": "没有可比较的备选动作。"}
        best = scored[0]
        chosen_score = self.score_action(observation, chosen)
        gap = max(0.0, best["score"] - chosen_score)
        grade = max(0, min(100, round(100 - gap * 4.2)))
        reasons = []
        if chosen.get("type") == "discard":
            tile = chosen.get("tile")
            if is_suited(tile):
                tile_def = TILE_BY_CODE[tile]
                hand = observation.get("hand", {})
                rank = tile_def.rank or 0
                links = 0
                for delta in (-1, 1):
                    nr = rank + delta
                    if 1 <= nr <= 9:
                        links += int(hand.get(f"{tile_def.suit}{nr}", 0))
                if links:
                    reasons.append("这张牌附近仍有搭子，过早切掉会损失进张。")
            if is_dragon(tile) or tile == observation_wind_code(observation):
                reasons.append("字牌或门风牌可能带来番数/刻子价值，模型倾向更谨慎处理。")
        if chosen.get("type") == "pass" and best["action"].get("type") in {"hu", "an_gang", "ming_gang", "bu_gang"}:
            reasons.append("模型认为当前机会价值较高，放弃会损失即时收益。")
        if not reasons:
            reasons.append("模型给出的最佳动作期望值更高，主要来自牌型速度、番数潜力和安全性综合权衡。")
        return {
            "score": grade,
            "chosen": action_label(chosen),
            "chosen_score": round(chosen_score, 2),
            "best": action_label(best["action"]),
            "best_score": round(best["score"], 2),
            "bad": grade < 75,
            "reason": " ".join(reasons),
            "suggestion": self._suggestion(chosen, best["action"]),
            "ranked": [{"label": item["label"], "score": round(item["score"], 2)} for item in scored[:5]],
        }

    def _suggestion(self, chosen: Action, best: Action) -> str:
        if best.get("type") == "discard":
            return f"下一次类似牌姿优先考虑{action_label(best)}，同时保留有效搭子和高番字牌。"
        if best.get("type") == "hu":
            return "已经达到可和形时优先和牌，温岭麻将后段风险上升很快。"
        if best.get("type") in {"an_gang", "ming_gang", "bu_gang"}:
            return "真实四张成杠且不含得时，可优先把杠的基础牌点和补牌机会兑现。"
        if best.get("type") in {"peng", "chi"}:
            return "模型认为副露能显著加速成型，可在不破坏主牌型时积极执行。"
        return "保持当前思路，但复盘时关注安全牌和有效进张的平衡。"

    def summary(self) -> dict[str, Any]:
        return {
            "backend": "linear",
            "path": str(self.path),
            "trained_games": self.trained_games,
            "experience_count": self.experience_count,
            "weights": len(self.weights),
            "updated_at": self.updated_at,
            "learning_rate": self.learning_rate,
        }


class RandomPolicyModel:
    def choose_action(self, observation: dict[str, Any], legal_actions: list[Action], explore: float = 0.0) -> Action:
        if not legal_actions:
            return {"type": "pass"}
        hu = [action for action in legal_actions if action.get("type") == "hu"]
        if hu:
            return hu[0]
        return random.choice(legal_actions)

    def score_action(self, observation: dict[str, Any], action: Action) -> float:
        return 0.0

    def score_actions(self, observation: dict[str, Any], legal_actions: list[Action]) -> list[dict[str, Any]]:
        return [{"action": action, "label": action_label(action), "score": 0.0} for action in legal_actions]

    def explain_decision(self, observation: dict[str, Any], chosen: Action, legal_actions: list[Action]) -> dict[str, Any]:
        return {
            "score": 50,
            "chosen": action_label(chosen),
            "best": "随机基准不评估最佳动作",
            "bad": False,
            "reason": "随机基准仅用于评测，不用于指导。",
            "suggestion": "使用训练模型进行复盘。",
            "ranked": [],
        }

    def summary(self) -> dict[str, Any]:
        return {"backend": "random", "trained_games": 0, "experience_count": 0, "weights": 0}


class HeuristicPolicyModel(LinearPolicyModel):
    def __init__(self):
        super().__init__(":memory:heuristic")

    def save(self) -> None:
        return

    def summary(self) -> dict[str, Any]:
        return {"backend": "heuristic", "trained_games": 0, "experience_count": 0, "weights": 0}
