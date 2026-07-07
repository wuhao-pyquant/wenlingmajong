from __future__ import annotations

import json
import random
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .hand_luck_runtime import HandLuckScorer, default_hand_luck_scorer
from .model import LinearPolicyModel, action_label
from .rules import (
    add_kongs,
    can_ming_gang,
    can_peng,
    can_win,
    concealed_kongs,
    chi_options,
    legal_discards,
    leizi_win_reason,
    score_player,
)
from .tiles import (
    FLOWERS,
    TILE_BY_CODE,
    build_wall,
    flower_set_for_de,
    same_family_de_set,
    sorted_tiles,
    tile_name,
)
from .tile_efficiency import shanten

CLAIM_ACTION_TYPES = {"ming_gang", "peng"}
RESPONSE_ACTION_PRIORITY = {"hu": 3, "ming_gang": 2, "peng": 2, "chi": 1}
DEFAULT_AI_DECISION_TIMEOUT_SEC = 8.0


def same_action(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("type") == right.get("type")
        and left.get("tile") == right.get("tile")
        and sorted(left.get("tiles", [])) == sorted(right.get("tiles", []))
    )


@dataclass
class PlayerState:
    name: str = ""
    hand: Counter[str] = field(default_factory=Counter)
    flowers: list[str] = field(default_factory=list)
    melds: list[dict[str, Any]] = field(default_factory=list)
    discards: list[str] = field(default_factory=list)
    chips: int = 0

    def reset_round(self) -> None:
        self.hand.clear()
        self.flowers.clear()
        self.melds.clear()
        self.discards.clear()


@dataclass
class BaoLiability:
    seq: int
    liable_seat: int
    target_winner: int | None
    reason: str
    source_event_id: str
    active: bool = True


@dataclass
class PendingAiJob:
    seat: int
    token: int
    started_at: float
    status: str = "thinking"

    def to_dict(self) -> dict[str, Any]:
        return {
            "seat": int(self.seat),
            "token": int(self.token),
            "started_at": float(self.started_at),
            "status": self.status,
        }


@dataclass
class PendingResponse:
    source_seat: int
    tile: str
    response_kind: str
    candidates: dict[int, list[dict[str, Any]]]
    order_index_by_seat: dict[int, int]
    human_responders: list[int]
    ai_candidates: list[int]
    source_event_id: str = ""
    pending_id: str | None = None
    room_generation: int | None = None
    created_at: float = field(default_factory=time.time)
    decisions_by_seat: dict[int, dict[str, Any]] = field(default_factory=dict)
    ai_jobs_by_seat: dict[int, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        legal_by_seat = {
            int(seat): [dict(action) for action in actions]
            for seat, actions in self.candidates.items()
        }
        responders = [int(seat) for seat in self.candidates.keys()]
        human_actions: list[dict[str, Any]] = []
        if self.human_responders:
            first_human = int(self.human_responders[0])
            human_actions = [dict(action) for action in legal_by_seat.get(first_human, [])]
        return {
            "kind": "response_poll",
            "pending_id": self.pending_id,
            "room_generation": self.room_generation,
            "source_event_id": self.source_event_id,
            "source_seat": int(self.source_seat),
            "response_kind": self.response_kind,
            "from": int(self.source_seat),
            "tile": self.tile,
            "created_at": float(self.created_at),
            "responders": responders,
            "candidates": legal_by_seat,
            "order_index_by_seat": {int(seat): int(index) for seat, index in self.order_index_by_seat.items()},
            "legal_by_seat": legal_by_seat,
            "responses": [],
            "decisions_by_seat": {int(seat): dict(action) for seat, action in self.decisions_by_seat.items()},
            "human_responders": [int(seat) for seat in self.human_responders],
            "human_actions": human_actions,
            "ai_candidates": [int(seat) for seat in self.ai_candidates],
            "ai_jobs_by_seat": {int(seat): dict(job) for seat, job in self.ai_jobs_by_seat.items()},
            "ai_thinking_by_seat": {},
            "ai_started_at_by_seat": {},
            "ai_precomputed_actions": {},
            "ai_precomputed_observations": {},
            "ai_precomputed_legal_actions": {},
            "deferred": bool(self.human_responders or self.ai_candidates),
            "deadline": None,
            "poll_index": 0,
            "current_responder": None,
        }


class WenlingMahjongGame:
    def __init__(
        self,
        model: LinearPolicyModel,
        log_dir: str | Path,
        human_seat: int | None = 0,
        human_seats: set[int] | list[int] | tuple[int, ...] | None = None,
        seed: int | None = None,
        training: bool = False,
        seat_models: list[Any] | None = None,
        persist_logs: bool = True,
        defer_ai_responses: bool = False,
        response_delay_sec: float = 2.0,
        ai_decision_timeout_sec: float = DEFAULT_AI_DECISION_TIMEOUT_SEC,
        stats_recorder: Any | None = None,
        hand_luck_scorer: HandLuckScorer | None = None,
        ai_result_callback: Any | None = None,
        ai_context_provider: Any | None = None,
    ):
        self.model = model
        self.seat_models = seat_models or [model, model, model, model]
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.human_seat = human_seat
        self.human_seats = self._normalize_human_seats(human_seat, human_seats)
        self.training = training
        self.persist_logs = persist_logs
        self.defer_ai_responses = defer_ai_responses
        self.response_delay_sec = max(0.0, float(response_delay_sec))
        self.ai_decision_timeout_sec = max(0.1, float(ai_decision_timeout_sec))
        self.stats_recorder = stats_recorder
        self.hand_luck_scorer = hand_luck_scorer or default_hand_luck_scorer()
        self.ai_result_callback = ai_result_callback
        self.ai_context_provider = ai_context_provider
        self.random = random.Random(seed)
        self.players = [PlayerState(name=name) for name in ["你", "AI1", "AI2", "AI3"]]
        self.dealer = 0
        self.next_dealer: int | None = None
        self.current_player = 0
        self.round_no = 0
        self.wall: list[str] = []
        self.initial_wall: list[str] = []
        self.initial_dealt_hands: list[dict[str, int]] = []
        self.opening_hands: list[dict[str, int]] = []
        self.de_indicator = ""
        self.de_set: set[str] = set()
        self.flower_set: set[str] = set()
        self.phase = "idle"
        self.pending: dict[str, Any] | None = None
        self.winner: int | None = None
        self.win_type = ""
        self.settlement: dict[str, Any] | None = None
        self.history: list[dict[str, Any]] = []
        self.decisions: list[dict[str, Any]] = []
        self.human_analysis: list[dict[str, Any]] = []
        self.last_draw: dict[int, str] = {}
        self.pending_self_win_type: dict[int, str] = {}
        self.player_stats: dict[str, dict[str, float]] = {}
        self.round_stats: list[dict[str, int | None]] = []
        self.round_started_at = time.time()
        self._ai_response_token = 0
        self._ai_result_lock = threading.Lock()
        self._ai_result_queue: deque[dict[str, Any]] = deque()
        self.supplement_count = 0
        self.bao_phase = False
        self.bao_phase_wall_threshold = 32
        self.draw_wall_threshold = 16
        self.discarded_tile_kinds: set[str] = set()
        self.discard_events: list[dict[str, Any]] = []
        self._discard_event_seq = 0
        self.bao_liabilities: list[BaoLiability] = []
        self._bao_liability_seq = 0
        self.temporary_bao_seat: int | None = None
        self.temporary_bao_reason = ""
        self.temporary_bao_started_event_id = ""
        self.claimed_discard_streaks: dict[int, list[dict[str, Any]]] = {seat: [] for seat in range(4)}
        self.claim_warnings: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _normalize_human_seats(
        human_seat: int | None,
        human_seats: set[int] | list[int] | tuple[int, ...] | None = None,
    ) -> set[int]:
        seats: set[int] = set()
        if human_seats is not None:
            seats.update(int(seat) for seat in human_seats)
        elif human_seat is not None:
            seats.add(int(human_seat))
        return {seat for seat in seats if 0 <= seat < 4}

    def set_human_seats(self, human_seats: set[int] | list[int] | tuple[int, ...]) -> None:
        self.human_seats = self._normalize_human_seats(self.human_seat, human_seats)
        if self.human_seat not in self.human_seats:
            self.human_seat = next(iter(sorted(self.human_seats)), None)

    def _is_human_actor(self, seat: int | None) -> bool:
        return seat is not None and int(seat) in getattr(self, "human_seats", set())

    @staticmethod
    def _empty_player_stats() -> dict[str, float]:
        return {
            "rounds": 0.0,
            "opening_shanten_total": 0.0,
            "de_draw_total": 0.0,
            "fan_flower_draw_total": 0.0,
            "wins": 0.0,
            "win_turn_total": 0.0,
            "win_point_total": 0.0,
            "luck_score_total": 0.0,
            "luck_score_count": 0.0,
        }

    @staticmethod
    def _empty_round_stats() -> dict[str, int | None]:
        return {
            "opening_shanten": None,
            "opening_normal_shanten": None,
            "opening_leizi_distance": None,
            "de_draws": 0,
            "fan_flower_draws": 0,
            "draw_turns": 0,
            "normal_draw_count": 0,
            "open_claim_count": 0,
            "supplement_draw_count": 0,
        }

    @staticmethod
    def _luck_model_distance(value: int | None) -> int:
        return max(0, int(value or 0))

    def _stats_key(self, seat: int) -> str:
        name = str(self.players[seat].name or "").strip()
        return name or f"seat-{seat}"

    def _stats_for(self, seat: int) -> dict[str, float]:
        key = self._stats_key(seat)
        if key not in self.player_stats:
            self.player_stats[key] = self._empty_player_stats()
        return self.player_stats[key]

    def _record_received_tile(self, seat: int, tile: str) -> None:
        if not tile or seat < 0 or seat >= len(self.players):
            return
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        current = self.round_stats[seat]
        if tile in self.de_set:
            current["de_draws"] = int(current.get("de_draws") or 0) + 1
        if tile in FLOWERS and tile in self.flower_set:
            current["fan_flower_draws"] = int(current.get("fan_flower_draws") or 0) + 1

    def _record_turn_draw(self, seat: int) -> None:
        if seat < 0 or seat >= len(self.players):
            return
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        current = self.round_stats[seat]
        current["draw_turns"] = int(current.get("draw_turns") or 0) + 1
        current["normal_draw_count"] = int(current.get("normal_draw_count") or 0) + 1

    def _record_open_claim(self, seat: int) -> None:
        if seat < 0 or seat >= len(self.players):
            return
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        current = self.round_stats[seat]
        current["open_claim_count"] = int(current.get("open_claim_count") or 0) + 1

    def _initialize_opening_turn_counts(self) -> None:
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        for seat in range(len(self.players)):
            self.round_stats[seat]["draw_turns"] = 1 if seat == self.dealer else 0

    def _record_win_stats(self, seat: int, win_points: int) -> int:
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        win_turn = int(self.round_stats[seat].get("draw_turns") or 0)
        stats = self._stats_for(seat)
        stats["wins"] += 1
        stats["win_turn_total"] += win_turn
        stats["win_point_total"] += int(win_points)
        return win_turn

    def _record_hand_luck(
        self,
        winner: int | None,
        final_hands: list[Counter[str]] | None = None,
        win_type: str = "",
    ) -> list[dict[str, Any]]:
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        results: list[dict[str, Any]] = []
        recorder = getattr(self, "stats_recorder", None)
        for seat in range(len(self.players)):
            current = self.round_stats[seat]
            final_hand = (
                Counter(final_hands[seat])
                if final_hands is not None and 0 <= seat < len(final_hands)
                else Counter(self.players[seat].hand)
            )
            final_normal_shanten = self._luck_model_distance(shanten(final_hand, set()))
            final_leizi_distance = self._luck_model_distance(shanten(final_hand, self.de_set))
            result = self.hand_luck_scorer.score(
                seat=seat,
                de_draws=min(3, int(current.get("de_draws") or 0)),
                fan_flower_draws=int(current.get("fan_flower_draws") or 0),
                opening_shanten=self._luck_model_distance(
                    current.get("opening_normal_shanten")
                    if current.get("opening_normal_shanten") is not None
                    else current.get("opening_shanten")
                ),
                final_shanten=final_normal_shanten,
                normal_draw_count=int(current.get("normal_draw_count") or 0),
                opening_leizi_distance=self._luck_model_distance(current.get("opening_leizi_distance")),
                final_leizi_distance=final_leizi_distance,
                open_claim_count=int(current.get("open_claim_count") or 0),
                supplement_draw_count=int(current.get("supplement_draw_count") or 0),
                win_type=self._hand_luck_feature_win_type(win_type, winner, seat),
            )
            account = self._stats_key(seat)
            results.append({**result.as_dict(), "account": account})
            stats = self._stats_for(seat)
            stats["luck_score_total"] += float(result.luck_percentile)
            stats["luck_score_count"] += 1
            if recorder is not None and hasattr(recorder, "record_hand_luck"):
                recorder.record_hand_luck(account, result.luck_percentile)
        return results

    @staticmethod
    def _hand_luck_feature_win_type(win_type: str, winner: int | None, seat: int) -> str:
        if winner is None or seat != winner:
            return ""
        normalized = str(win_type or "").strip()
        return normalized if normalized in {"劣子和", "自摸得", "杠上开花", "抢杠胡", "抢杠和", "rob_gang"} else ""

    def _give_drawn_tile(self, seat: int, tile: str) -> None:
        if not tile:
            return
        self.players[seat].hand[tile] += 1
        self._record_received_tile(seat, tile)

    def _record_opening_stats(self) -> None:
        while len(self.round_stats) < len(self.players):
            self.round_stats.append(self._empty_round_stats())
        for seat, player in enumerate(self.players):
            value = shanten(player.hand, self.de_set)
            normal_value = shanten(player.hand, set())
            self.round_stats[seat]["opening_shanten"] = value
            self.round_stats[seat]["opening_normal_shanten"] = self._luck_model_distance(normal_value)
            self.round_stats[seat]["opening_leizi_distance"] = self._luck_model_distance(value)
            stats = self._stats_for(seat)
            stats["rounds"] += 1
            stats["opening_shanten_total"] += value
            stats["de_draw_total"] += int(self.round_stats[seat].get("de_draws") or 0)
            stats["fan_flower_draw_total"] += int(self.round_stats[seat].get("fan_flower_draws") or 0)
            recorder = getattr(self, "stats_recorder", None)
            if recorder is not None:
                recorder.record_opening(
                    self._stats_key(seat),
                    value,
                    int(self.round_stats[seat].get("de_draws") or 0),
                    int(self.round_stats[seat].get("fan_flower_draws") or 0),
                )

    def player_stat_summary(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for seat, player in enumerate(self.players):
            name = str(player.name or "").strip()
            stats = self.player_stats.get(name) if name else None
            rounds = int(stats.get("rounds", 0)) if stats else 0
            rows.append(
                {
                    "name": name,
                    "seat": seat,
                    "wind": self._seat_wind(seat),
                    "rounds": rounds,
                    "avg_opening_shanten": round(stats["opening_shanten_total"] / rounds, 3) if stats and rounds else None,
                    "avg_de_draws": round(stats["de_draw_total"] / rounds, 3) if stats and rounds else None,
                    "avg_fan_flower_draws": round(stats["fan_flower_draw_total"] / rounds, 3) if stats and rounds else None,
                    "avg_win_turn": round(stats["win_turn_total"] / stats["wins"], 3) if stats and stats.get("wins") else None,
                    "avg_win_points": round(stats["win_point_total"] / stats["wins"], 3) if stats and stats.get("wins") else None,
                    "wins": int(stats.get("wins", 0)) if stats else 0,
                    "win_rate": round(stats["wins"] / rounds, 4) if stats and rounds else None,
                    "luck_score": round(stats["luck_score_total"] / stats["luck_score_count"], 1)
                    if stats and stats.get("luck_score_count")
                    else None,
                    "total_de_draws": int(stats.get("de_draw_total", 0)) if stats else 0,
                    "total_fan_flower_draws": int(stats.get("fan_flower_draw_total", 0)) if stats else 0,
                }
            )
        return rows

    def _model_for(self, seat: int) -> Any:
        if 0 <= seat < len(self.seat_models):
            return self.seat_models[seat]
        return self.model

    def new_round(self) -> dict[str, Any]:
        if self.round_no > 0 and self.next_dealer is not None:
            self.dealer = self.next_dealer
        self.next_dealer = None
        self.round_no += 1
        self.wall = build_wall()
        self.random.shuffle(self.wall)
        self.initial_wall = list(self.wall)
        # The revealed "得" indicator is outside the live wall and never participates in play.
        self.de_indicator = self.wall.pop(0)
        self.de_set = same_family_de_set(self.de_indicator)
        self.flower_set = flower_set_for_de(self.de_indicator)
        self.phase = "deal"
        self.pending = None
        self.winner = None
        self.win_type = ""
        self.settlement = None
        self.history.clear()
        self.decisions.clear()
        self.human_analysis.clear()
        self.last_draw.clear()
        self.pending_self_win_type.clear()
        self.round_stats = [self._empty_round_stats() for _ in range(4)]
        self.round_started_at = time.time()
        self.supplement_count = 0
        self.bao_phase = False
        self.bao_phase_wall_threshold, self.draw_wall_threshold = self._wall_thresholds()
        self.discarded_tile_kinds.clear()
        self.discard_events.clear()
        self._discard_event_seq = 0
        self.bao_liabilities.clear()
        self._bao_liability_seq = 0
        self.temporary_bao_seat = None
        self.temporary_bao_reason = ""
        self.temporary_bao_started_event_id = ""
        self.claimed_discard_streaks = {seat: [] for seat in range(4)}
        self.claim_warnings.clear()
        for player in self.players:
            player.reset_round()

        for seat in range(4):
            target = 17 if seat == self.dealer else 16
            for _ in range(target):
                self._give_drawn_tile(seat, self._draw_front())
        self.initial_dealt_hands = [dict(player.hand) for player in self.players]

        self._log(
            "round_start",
            f"第 {self.round_no} 局开始，庄家 {self._seat_label(self.dealer)}，得为 {tile_name(self.de_indicator)}",
            de=sorted(self.de_set),
            flowers=sorted(self.flower_set),
        )
        self._initial_replenish_flowers()
        self.opening_hands = [dict(player.hand) for player in self.players]
        self._record_opening_stats()
        self._initialize_opening_turn_counts()

        for offset in range(4):
            seat = (self.dealer + offset) % 4
            if self._finish_leizi_if_present(seat):
                return self.serialize()
        if self._finish_tianhu_if_present():
            return self.serialize()

        self._start_turn(self.dealer)
        if not (self.defer_ai_responses and self.human_seats):
            self.advance_until_human()
        return self.serialize()

    def shuffle_seats(self, include_human: bool = False) -> None:
        if include_human:
            self.random.shuffle(self.players)
            for index, player in enumerate(self.players):
                if player.name == "你":
                    self.human_seat = index
                    self.human_seats = {index}
                    break
        else:
            ai_players = self.players[1:]
            self.random.shuffle(ai_players)
            self.players[1:] = ai_players
            self.human_seat = 0
            self.human_seats = {0}
        self.dealer = self.random.randrange(4)
        self.current_player = self.dealer
        self.pending = None
        self.next_dealer = None

    def _draw_front(self) -> str:
        if not self.wall:
            self._draw_game("牌墙为空")
            return ""
        return self.wall.pop(0)

    def _draw_tail(self) -> str:
        if not self.wall:
            self._draw_game("牌墙为空")
            return ""
        return self.wall.pop()

    def _wall_thresholds(self) -> tuple[int, int]:
        return (33, 17) if self.supplement_count % 2 else (32, 16)

    def _wall_to_draw_game(self) -> int:
        return max(0, len(self.wall) - self.draw_wall_threshold)

    def _update_wall_phase(self) -> None:
        self.bao_phase_wall_threshold, self.draw_wall_threshold = self._wall_thresholds()
        if self.phase == "round_over":
            return
        if len(self.wall) <= self.draw_wall_threshold:
            self._draw_game(f"牌墙剩余不超过 {self.draw_wall_threshold} 张")
            return
        if len(self.wall) <= self.bao_phase_wall_threshold:
            if not self.bao_phase:
                self._log(
                    "bao_phase",
                    f"进入包张阶段，离黄牌还剩 {self._wall_to_draw_game()} 张",
                    supplement_count=self.supplement_count,
                    wall_remaining=len(self.wall),
                )
            self.bao_phase = True

    def _draw_supplement_tile(self, seat: int, reason: str) -> str:
        tile = self._draw_tail()
        if tile:
            self.supplement_count += 1
            while len(self.round_stats) < len(self.players):
                self.round_stats.append(self._empty_round_stats())
            if 0 <= seat < len(self.round_stats):
                current = self.round_stats[seat]
                current["supplement_draw_count"] = int(current.get("supplement_draw_count") or 0) + 1
            self._log(
                "supplement",
                f"{self._seat_label(seat)}补牌：{reason}",
                seat=seat,
                tile=tile,
                reason=reason,
                supplement_count=self.supplement_count,
            )
            self._update_wall_phase()
        return tile

    def _initial_replenish_flowers(self) -> None:
        changed = True
        while changed and self.wall:
            changed = False
            for offset in range(4):
                seat = (self.dealer + offset) % 4
                extracted = self._extract_current_flowers(seat)
                if extracted:
                    changed = True
                    for _ in extracted:
                        tile = self._draw_supplement_tile(seat, "开局补花")
                        if tile:
                            self._give_drawn_tile(seat, tile)
                    if self.phase == "round_over":
                        return

    def _extract_current_flowers(self, seat: int) -> list[str]:
        player = self.players[seat]
        extracted: list[str] = []
        for code in list(player.hand):
            if code in self.flower_set and player.hand[code] > 0:
                count = player.hand.pop(code)
                player.flowers.extend([code] * count)
                extracted.extend([code] * count)
        if extracted:
            self._log("flower", f"{self._seat_label(seat)}补花：{self._tile_list(extracted)}", seat=seat, tiles=extracted)
        return extracted

    def _replenish_flowers_after_draw(self, seat: int) -> None:
        while self.wall:
            extracted = self._extract_current_flowers(seat)
            if not extracted:
                return
            for _ in extracted:
                tile = self._draw_supplement_tile(seat, "补花")
                if tile:
                    self._give_drawn_tile(seat, tile)
                    self.last_draw[seat] = tile
            if self.phase == "round_over":
                return

    def _start_turn(self, seat: int) -> None:
        if self.phase == "round_over":
            return
        self.current_player = seat
        self.pending = None
        self.phase = "turn"
        hand_count = sum(self.players[seat].hand.values())
        self.pending_self_win_type.pop(seat, None)
        if hand_count % 3 == 1:
            self._clear_temporary_bao_for_draw(seat)
            self._update_wall_phase()
            if self.phase == "round_over":
                return
            tile = self._draw_front()
            if not tile:
                return
            self._record_turn_draw(seat)
            self._give_drawn_tile(seat, tile)
            self.last_draw[seat] = tile
            self._log("draw", f"{self._seat_label(seat)}摸牌")
            self._update_wall_phase()
            if self.phase == "round_over":
                return
            self._replenish_flowers_after_draw(seat)
            if self.phase == "round_over":
                return
            if self._finish_leizi_if_present(seat):
                return
            if tile in self.de_set and can_win(self.players[seat].hand, self.de_set, self.players[seat].melds):
                self.pending_self_win_type[seat] = "自摸得"
        else:
            self.last_draw.pop(seat, None)

    def legal_turn_actions(self, seat: int | None = None) -> list[dict[str, Any]]:
        seat = self.current_player if seat is None else seat
        if self.phase != "turn" or self.winner is not None:
            return []
        player = self.players[seat]
        actions: list[dict[str, Any]] = []
        if can_win(player.hand, self.de_set, player.melds):
            actions.append({"type": "hu"})
        for tile in concealed_kongs(player.hand, self.de_set):
            actions.append({"type": "an_gang", "tile": tile})
        for tile in add_kongs(player.hand, player.melds, self.de_set):
            actions.append({"type": "bu_gang", "tile": tile})
        for tile in legal_discards(player.hand, self.de_set):
            actions.append({"type": "discard", "tile": tile})
        return actions

    def pending_actions_for_human(self) -> list[dict[str, Any]]:
        return self._pending_actions_for_seat(self.human_seat)

    def _pending_actions_for_seat(self, seat: int | None) -> list[dict[str, Any]]:
        if not self.pending or seat is None:
            return []
        if self.pending.get("kind") == "response_poll":
            responders = set(self.pending.get("responders", []))
            decisions = self.pending.get("decisions_by_seat") or {}
            if seat not in responders or seat in decisions:
                return []
            legal_by_seat = self.pending.get("legal_by_seat") or {}
            return [dict(action) for action in legal_by_seat.get(seat, [])]
        return list(self.pending.get("human_actions", []))

    def apply_human_action(self, action: dict[str, Any]) -> dict[str, Any]:
        return self.apply_human_action_for_seat(self.human_seat, action)

    def apply_human_action_for_seat(self, seat: int | None, action: dict[str, Any]) -> dict[str, Any]:
        if seat is None:
            raise ValueError("当前对局没有人类玩家")
        self.human_seat = int(seat)
        if self.human_seat is None:
            raise ValueError("当前对局没有人类玩家")
        if self.pending:
            current_responder = self.pending.get("current_responder")
            if self.pending.get("kind") != "response_poll" and current_responder is not None and current_responder != self.human_seat:
                raise ValueError("还没轮到这个玩家响应")
            legal = self.pending_actions_for_human()
            if not any(same_action(action, candidate) for candidate in legal):
                raise ValueError("非法响应动作")
            self._record_human_decision(self.human_seat, action, legal)
            self._resolve_pending_with_human(action)
        else:
            if self.phase != "turn" or self.current_player != self.human_seat:
                raise ValueError("还没有轮到人类玩家操作")
            legal = self.legal_turn_actions(self.human_seat)
            if not any(same_action(action, candidate) for candidate in legal):
                raise ValueError("非法行动")
            self._record_human_decision(self.human_seat, action, legal)
            self._execute_turn_action(self.human_seat, action, record=False)
        if not (self.defer_ai_responses and self.human_seats):
            self.advance_until_human()
        return self.serialize()

    def advance_until_human(self, max_steps: int = 2000, draw_on_limit: bool = True) -> None:
        steps = 0
        while self.phase != "round_over" and steps < max_steps:
            steps += 1
            if self._is_waiting_for_human():
                return
            if self.pending:
                self._resolve_pending_without_human()
                if self.pending and self.pending.get("deferred"):
                    return
                continue
            if self.phase == "turn":
                if self._is_human_actor(self.current_player):
                    return
                legal = self.legal_turn_actions(self.current_player)
                if not legal:
                    self._draw_game("没有合法出牌")
                    return
                obs = self.observation(self.current_player)
                action = self._model_for(self.current_player).choose_action(obs, legal, explore=0.06 if self.training else 0.0)
                action = self._legal_turn_fallback(self.current_player, action, legal)
                self.decisions.append(
                    {
                        "player": self.current_player,
                        "observation": obs,
                        "legal_actions": legal,
                        "action": action,
                    }
                )
                self._execute_turn_action(self.current_player, action)
        if draw_on_limit and steps >= max_steps:
            self._draw_game("自动流程达到保护步数")

    def _is_waiting_for_human(self) -> bool:
        if not self.human_seats:
            return False
        if self.pending and self.pending.get("deferred"):
            return True
        if self.pending and self.pending.get("human_actions"):
            return True
        return self.phase == "turn" and self._is_human_actor(self.current_player)

    def recover_invalid_pending(self, reason: str) -> bool:
        if not self.pending:
            return False
        source = int(self.pending.get("from", self.current_player))
        tile = self.pending.get("tile", "")
        kind = str(self.pending.get("kind", "pending"))
        self._log("warn", f"取消过期响应 {kind} {tile_name(tile) if tile else ''}：{reason}")
        self.pending = None
        if self.phase != "round_over":
            self._start_turn((source + 1) % 4)
        return True

    def _set_deferred_pending(
        self,
        kind: str,
        source: int,
        tile: str,
        human_actions: list[dict[str, Any]] | None = None,
        ai_candidates: list[int] | None = None,
        ai_action: dict[str, Any] | None = None,
        ai_legal_actions: Any = None,
    ) -> None:
        human_actions = list(human_actions or [])
        ai_candidates = list(ai_candidates or [])
        responders = set(ai_candidates)
        if human_actions and self.human_seat is not None:
            responders.add(self.human_seat)
        self.pending = {
            "kind": kind,
            "from": source,
            "tile": tile,
            "human_actions": human_actions,
            "ai_candidates": ai_candidates,
            "ai_action": ai_action,
            "ai_legal_actions": ai_legal_actions,
            "human_action": None,
            "deferred": True,
            "deadline": time.time() + self.response_delay_sec,
            "responders": sorted(responders),
        }

    def _queue_ai_result_local(self, result: dict[str, Any]) -> None:
        with self._ai_result_lock:
            self._ai_result_queue.append(dict(result))

    def _queue_ai_result(self, result: dict[str, Any]) -> None:
        if callable(getattr(self, "ai_result_callback", None)):
            self.ai_result_callback(dict(result))
            return
        self._queue_ai_result_local(result)

    def _ai_result_context(self, metadata: dict[str, Any]) -> dict[str, Any]:
        provider = getattr(self, "ai_context_provider", None)
        if not callable(provider):
            return {}
        try:
            context = provider(dict(metadata))
        except Exception:
            return {}
        return dict(context or {})

    def cancel_async_ai_jobs(self) -> None:
        self._ai_response_token += 1
        with self._ai_result_lock:
            self._ai_result_queue.clear()
        if isinstance(self.pending, dict):
            self.pending["ai_thinking"] = False
            self.pending["ai_started_at"] = None
            self.pending["ai_precomputed_action"] = None
            self.pending["ai_thinking_by_seat"] = {}
            self.pending["ai_started_at_by_seat"] = {}
            self.pending["ai_precomputed_actions"] = {}

    def _pop_ai_results(self) -> list[dict[str, Any]]:
        with self._ai_result_lock:
            results = list(self._ai_result_queue)
            self._ai_result_queue.clear()
        return results

    def _drain_ai_results(self) -> None:
        if not self.pending:
            self._pop_ai_results()
            return
        pending = self.pending
        for result in self._pop_ai_results():
            kind = result.get("kind")
            seat = result.get("seat")
            token = result.get("token")
            if kind == "response_poll" and pending.get("kind") == "response_poll":
                if (pending.get("ai_think_tokens_by_seat") or {}).get(seat) != token:
                    continue
                pending.setdefault("ai_precomputed_actions", {})[seat] = result.get("action")
                pending.setdefault("ai_precomputed_observations", {})[seat] = result.get("observation")
                pending.setdefault("ai_precomputed_legal_actions", {})[seat] = list(result.get("legal_actions") or [])
                pending.setdefault("ai_thinking_by_seat", {})[seat] = False
                job = (pending.setdefault("ai_jobs_by_seat", {}) or {}).setdefault(seat, {})
                job["status"] = "done"
                job["completed_at"] = time.time()
                continue
            if kind == "ai_turn" and pending.get("kind") == "ai_turn":
                if pending.get("ai_think_token") != token or int(pending.get("from", -1)) != int(seat):
                    continue
                pending["ai_precomputed_action"] = result.get("action")
                pending["ai_precomputed_observation"] = result.get("observation")
                pending["ai_precomputed_legal_actions"] = list(result.get("legal_actions") or [])
                pending["ai_thinking"] = False

    def resolve_deferred_pending(self, force: bool = False) -> None:
        if not self.pending or not self.pending.get("deferred"):
            return
        self._drain_ai_results()
        if self.pending.get("kind") == "response_poll":
            self._resolve_response_poll_step(force=force)
            return
        if self.pending.get("kind") == "ai_turn":
            self._resolve_ai_turn_step(force=force)
            return
        if self.pending.get("kind") == "post_action_pause":
            if not force and time.time() < float(self.pending.get("deadline", 0.0)):
                return
            pending = self.pending
            self.pending = None
            source = int(pending.get("from", self.current_player))
            tile = str(pending.get("tile", ""))
            if pending.get("response_kind") == "rob_gang":
                self._finalize_bu_gang(source, tile)
            else:
                self._start_turn((source + 1) % 4)
            return
        if not force and time.time() < float(self.pending.get("deadline", 0.0)):
            return
        if (
            self.pending.get("human_actions")
            and self.pending.get("human_action") is None
            and not self.pending.get("ai_candidates")
        ):
            return

        pending = self.pending
        kind = pending["kind"]
        source = pending["from"]
        tile = pending["tile"]
        human_action = pending.get("human_action") or {"type": "pass"}
        ai_candidates = list(pending.get("ai_candidates", []))
        ai_action = pending.get("ai_action")
        self.pending = None

        if kind == "discard_hu":
            winners = [p for p in ai_candidates if ai_action and self._ai_yes_no(p, ai_action, kind)]
            if human_action.get("type") == "hu":
                winners.append(self.human_seat)  # type: ignore[arg-type]
            if winners:
                self._finish_win(
                    self._priority_winner(source, winners),
                    self._win_type_for_discard(source, tile),
                    discarder=source,
                    win_tile=tile,
                )
            else:
                self._open_discard_response_after_hu_pass(source, tile)
            return

        if kind == "rob_gang":
            winners = [p for p in ai_candidates if ai_action and self._ai_yes_no(p, ai_action, kind)]
            if human_action.get("type") == "hu":
                winners.append(self.human_seat)  # type: ignore[arg-type]
            if winners:
                self._finish_win(self._priority_winner(source, winners), "抢杠和", discarder=source, win_tile=tile)
            else:
                self._finalize_bu_gang(source, tile)
            return

        if kind in {"ming_gang", "peng"}:
            ai_claims = [
                p for p in ai_candidates
                if ai_action
                and self._can_execute_claim(p, tile, kind)
                and self._ai_yes_no(p, ai_action, kind)
            ]
            if human_action.get("type") == kind and self.human_seat is not None and self._can_execute_claim(self.human_seat, tile, kind):
                self._execute_claim(self.human_seat, source, tile, kind)  # type: ignore[arg-type]
            elif ai_claims:
                self._execute_claim(self._priority_winner(source, ai_claims), source, tile, kind)
            else:
                self._open_discard_response_after_claim_pass(source, tile, kind)
            return

        if kind == "claim":
            claim_actions: list[tuple[int, dict[str, Any]]] = []
            if (
                human_action.get("type") in CLAIM_ACTION_TYPES
                and self.human_seat is not None
                and self._can_execute_claim(self.human_seat, tile, human_action["type"])
            ):
                claim_actions.append((self.human_seat, human_action))
            legal_by_seat = pending.get("ai_legal_actions") or {}
            for seat in ai_candidates:
                legal = list(legal_by_seat.get(str(seat), legal_by_seat.get(seat, [{"type": "pass"}])))
                action = self._choose_ai_claim_action(seat, legal)
                if action.get("type") in CLAIM_ACTION_TYPES and self._can_execute_claim(seat, tile, action["type"]):
                    claim_actions.append((seat, action))
            if claim_actions:
                winner = self._priority_winner(source, [seat for seat, _ in claim_actions])
                action = next(action for seat, action in claim_actions if seat == winner)
                self._execute_claim(winner, source, tile, action["type"])
            else:
                self._open_discard_response_after_claim_pass(source, tile, "claim")
            return

        if kind == "chi":
            if human_action.get("type") == "chi":
                self._execute_claim(self.human_seat, source, tile, "chi", human_action.get("tiles", []))  # type: ignore[arg-type]
                return
            if ai_candidates:
                next_seat = ai_candidates[0]
                legal = list(pending.get("ai_legal_actions") or [{"type": "pass"}])
                obs = self.observation(next_seat)
                action = self._model_for(next_seat).choose_action(obs, legal, explore=0.04 if self.training else 0.0)
                self.decisions.append({"player": next_seat, "observation": obs, "legal_actions": legal, "action": action})
                if action["type"] == "chi":
                    self._execute_claim(next_seat, source, tile, "chi", action.get("tiles", []))
                    return
                self._mark_latest_discard_unclaimed(source, tile)
                return
            self._mark_latest_discard_unclaimed(source, tile)
            self._start_turn((source + 1) % 4)

    def _response_order(self, source: int) -> list[int]:
        return [(source + offset) % 4 for offset in range(1, 4)]

    def _discard_response_actions(self, seat: int, discarder: int, tile: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if self._can_player_win_with_tile(seat, tile):
            actions.append({"type": "hu", "tile": tile})
        actions.extend(self._claim_actions_for_seat(seat, tile))
        if seat == (discarder + 1) % 4:
            actions.extend({"type": "chi", "tile": tile, "tiles": option} for option in chi_options(self.players[seat].hand, tile, self.de_set))
        if actions:
            actions.append({"type": "pass"})
        return actions

    def _rob_gang_response_actions(self, seat: int, source: int, tile: str) -> list[dict[str, Any]]:
        if self._can_player_win_with_tile(seat, tile):
            return [{"type": "hu", "tile": tile}, {"type": "pass"}]
        return []

    def _response_actions_for(self, response_kind: str, seat: int, source: int, tile: str) -> list[dict[str, Any]]:
        if response_kind == "discard":
            return self._discard_response_actions(seat, source, tile)
        if response_kind == "rob_gang":
            return self._rob_gang_response_actions(seat, source, tile)
        return []

    def _start_response_poll(self, response_kind: str, source: int, tile: str) -> None:
        order = self._response_order(source)
        legal_by_seat = {
            seat: self._response_actions_for(response_kind, seat, source, tile)
            for seat in order
        }
        responders = [seat for seat in order if legal_by_seat[seat]]
        if not responders:
            if response_kind == "discard":
                self._mark_latest_discard_unclaimed(source, tile)
            if self.defer_ai_responses and self.response_delay_sec > 0:
                self.pending = {
                    "kind": "post_action_pause",
                    "response_kind": response_kind,
                    "from": source,
                    "tile": tile,
                    "human_actions": [],
                    "deferred": True,
                    "deadline": time.time() + self.response_delay_sec,
                }
            elif response_kind == "rob_gang":
                self._finalize_bu_gang(source, tile)
            else:
                self._start_turn((source + 1) % 4)
            return
        order_index_by_seat = {seat: idx for idx, seat in enumerate(order)}
        human_responders = [seat for seat in responders if self._is_human_actor(seat)]
        human_actions = list(legal_by_seat.get(self.human_seat, [])) if self.human_seat in human_responders else []
        ai_candidates = [seat for seat in responders if not self._is_human_actor(seat)]
        event = self._latest_discard_event(source, tile) if response_kind == "discard" else None
        source_event_id = str(event.get("id")) if event else f"{response_kind}:{source}:{tile}:{len(self.history)}"
        candidates = {seat: list(legal_by_seat[seat]) for seat in responders}
        self.pending = PendingResponse(
            source_seat=source,
            tile=tile,
            response_kind=response_kind,
            candidates=candidates,
            order_index_by_seat=order_index_by_seat,
            human_responders=human_responders,
            ai_candidates=ai_candidates,
            source_event_id=source_event_id,
        ).to_dict()
        self.pending["human_actions"] = human_actions
        self.pending["deferred"] = bool(human_responders or (self.defer_ai_responses and ai_candidates))
        if self.defer_ai_responses:
            self.pending["deferred"] = True
            for seat in ai_candidates:
                self._start_ai_response_thinking(seat, legal_by_seat[seat], response_kind)
            if not human_responders:
                self._resolve_response_poll_step(force=False)
            return
        for seat in ai_candidates:
            action = self._choose_ai_response_action(seat, legal_by_seat[seat], response_kind)
            self.pending["decisions_by_seat"][seat] = action
            self._record_response_poll_action(seat, action, order_index_by_seat[seat])
        if human_actions:
            return
        self._finish_response_poll()

    def _start_ai_response_thinking(self, seat: int, legal: list[dict[str, Any]], context: str) -> None:
        if not self.pending:
            return
        self._ai_response_token += 1
        token = self._ai_response_token
        obs = self.observation(seat)
        legal_copy = [dict(action) for action in legal]
        model = self._model_for(seat)
        explore = 0.04 if self.training else 0.0
        self.pending.setdefault("ai_thinking_by_seat", {})[seat] = True
        started_at = time.time()
        self.pending.setdefault("ai_started_at_by_seat", {})[seat] = started_at
        self.pending.setdefault("ai_think_tokens_by_seat", {})[seat] = token
        self.pending.setdefault("ai_precomputed_actions", {}).pop(seat, None)
        self.pending.setdefault("ai_jobs_by_seat", {})[seat] = PendingAiJob(seat=seat, token=token, started_at=started_at).to_dict()
        job_context = self._ai_result_context({"kind": "response_poll", "seat": seat, "token": token})

        def run() -> None:
            try:
                action = model.choose_action(obs, legal_copy, explore=explore)
            except Exception:
                action = {"type": "pass"}
            self._queue_ai_result({
                "kind": "response_poll",
                "seat": seat,
                "token": token,
                "action": action,
                "observation": obs,
                "legal_actions": legal_copy,
                **job_context,
            })

        threading.Thread(target=run, daemon=True, name=f"ai-response-{seat}").start()

    def prepare_deferred_ai_turn(self) -> bool:
        if (
            self.pending
            or not self.defer_ai_responses
            or self.phase != "turn"
            or self._is_human_actor(self.current_player)
        ):
            return False
        seat = self.current_player
        legal = self.legal_turn_actions(seat)
        if not legal:
            self._draw_game("没有合法出牌")
            return True
        self._ai_response_token += 1
        token = self._ai_response_token
        obs = self.observation(seat)
        legal_copy = [dict(action) for action in legal]
        model = self._model_for(seat)
        explore = 0.06 if self.training else 0.0
        self.pending = {
            "kind": "ai_turn",
            "from": seat,
            "tile": "",
            "human_actions": [],
            "ai_candidates": [seat],
            "deferred": True,
            "deadline": time.time() + self.response_delay_sec,
            "ai_thinking": True,
            "ai_started_at": time.time(),
            "ai_think_token": token,
            "ai_precomputed_action": None,
            "ai_precomputed_observation": obs,
            "ai_precomputed_legal_actions": legal_copy,
        }
        job_context = self._ai_result_context({"kind": "ai_turn", "seat": seat, "token": token})

        def run() -> None:
            try:
                action = model.choose_action(obs, legal_copy, explore=explore)
            except Exception:
                action = legal_copy[0] if legal_copy else {"type": "pass"}
            self._queue_ai_result({
                "kind": "ai_turn",
                "seat": seat,
                "token": token,
                "action": action,
                "observation": obs,
                "legal_actions": legal_copy,
                **job_context,
            })

        threading.Thread(target=run, daemon=True, name=f"ai-turn-{seat}").start()
        return True

    def _resolve_ai_turn_step(self, force: bool = False) -> None:
        if not self.pending or self.pending.get("kind") != "ai_turn":
            return
        self._drain_ai_results()
        if not force and time.time() < float(self.pending.get("deadline") or 0.0):
            return
        seat = int(self.pending.get("from", self.current_player))
        action = self.pending.get("ai_precomputed_action")
        obs = self.pending.get("ai_precomputed_observation") or self.observation(seat)
        legal = list(self.pending.get("ai_precomputed_legal_actions") or self.legal_turn_actions(seat))
        if self.pending.get("ai_thinking") and action is None and not force:
            if not self._ai_job_timed_out(self.pending.get("ai_started_at")):
                return
            action = self._timeout_turn_action(seat, legal)
            self.pending["ai_thinking"] = False
        if action is None:
            action = self._model_for(seat).choose_action(obs, legal, explore=0.06 if self.training else 0.0)
        action = self._legal_turn_fallback(seat, action, legal)
        self.pending = None
        self.decisions.append({"player": seat, "observation": obs, "legal_actions": legal, "action": action})
        self._execute_turn_action(seat, action)

    def _legal_turn_fallback(self, seat: int, action: dict[str, Any], legal: list[dict[str, Any]]) -> dict[str, Any]:
        current_legal = self.legal_turn_actions(seat)
        if any(same_action(action, candidate) for candidate in current_legal):
            return action
        fallback = next((candidate for candidate in current_legal if candidate.get("type") == "discard"), None)
        if fallback is None and current_legal:
            fallback = current_legal[0]
        if fallback is None:
            fallback = {"type": "pass"}
        self._log("warn", "AI action was stale or illegal; replaced with a legal fallback", seat=seat, action=action, fallback=fallback)
        return fallback

    def _choose_ai_response_action(self, seat: int, legal: list[dict[str, Any]], context: str) -> dict[str, Any]:
        obs = self.observation(seat)
        action = self._model_for(seat).choose_action(obs, legal, explore=0.04 if self.training else 0.0)
        self.decisions.append({"player": seat, "observation": obs, "legal_actions": legal, "action": action, "context": context})
        return action

    def _ai_job_timed_out(self, started_at: Any, now: float | None = None) -> bool:
        try:
            started = float(started_at)
        except (TypeError, ValueError):
            return False
        current = time.time() if now is None else now
        return current - started >= self.ai_decision_timeout_sec

    def _timeout_response_action(self, seat: int, legal: list[dict[str, Any]], context: str) -> dict[str, Any]:
        action = next((dict(item) for item in legal if item.get("type") == "pass"), {"type": "pass"})
        self._log(
            "ai_timeout",
            f"{self._seat_label(seat)} AI response timed out; fallback to pass",
            seat=seat,
            context=context,
            elapsed_sec=self.ai_decision_timeout_sec,
        )
        if self.pending and self.pending.get("kind") == "response_poll":
            job = self.pending.setdefault("ai_jobs_by_seat", {}).setdefault(seat, {})
            job["status"] = "timeout"
            job["completed_at"] = time.time()
        return action

    def _timeout_turn_action(self, seat: int, legal: list[dict[str, Any]]) -> dict[str, Any]:
        action = next((dict(item) for item in legal if item.get("type") == "discard"), None)
        if action is None and legal:
            action = dict(legal[0])
        if action is None:
            action = {"type": "pass"}
        self._log(
            "ai_timeout",
            f"{self._seat_label(seat)} AI turn timed out; fallback action used",
            seat=seat,
            action=action,
            elapsed_sec=self.ai_decision_timeout_sec,
        )
        return action

    def _record_response_poll_action(self, seat: int, action: dict[str, Any], order_index: int) -> None:
        if not self.pending or action.get("type") == "pass":
            return
        self.pending.setdefault("responses", []).append({"seat": seat, "action": action, "order_index": order_index})

    def _resolve_response_poll_step(self, force: bool = False) -> None:
        if not self.pending or self.pending.get("kind") != "response_poll":
            return
        self._drain_ai_results()
        decisions = self.pending.setdefault("decisions_by_seat", {})
        legal_by_seat = self.pending.get("legal_by_seat") or {}
        ai_candidates = list(self.pending.get("ai_candidates", []))
        ai_actions = self.pending.get("ai_precomputed_actions") or {}
        ai_thinking = self.pending.get("ai_thinking_by_seat") or {}
        ai_started = self.pending.get("ai_started_at_by_seat") or {}
        for seat in ai_candidates:
            seat = int(seat)
            if seat in decisions:
                continue
            legal = list(legal_by_seat.get(seat) or [])
            action = ai_actions.get(seat)
            if action is None and ai_thinking.get(seat) and not force:
                if not self._ai_job_timed_out(ai_started.get(seat)):
                    return
                action = self._timeout_response_action(seat, legal, self.pending["response_kind"])
                self.pending.setdefault("ai_thinking_by_seat", {})[seat] = False
            if action is None:
                action = self._choose_ai_response_action(seat, legal, self.pending["response_kind"])
            else:
                obs = (self.pending.get("ai_precomputed_observations") or {}).get(seat) or self.observation(seat)
                legal_for_record = (self.pending.get("ai_precomputed_legal_actions") or {}).get(seat) or legal
                self.decisions.append({
                    "player": seat,
                    "observation": obs,
                    "legal_actions": legal_for_record,
                    "action": action,
                    "context": self.pending["response_kind"],
                })
            decisions[seat] = action
            order_index = (self.pending.get("order_index_by_seat") or {}).get(seat, 99)
            self._record_response_poll_action(seat, action, int(order_index))
        human_responders = list(self.pending.get("human_responders", []))
        if not force and any(seat not in decisions for seat in human_responders):
            return
        if any(seat not in decisions for seat in self.pending.get("responders", [])):
            return
        self._finish_response_poll()

    def _finish_response_poll(self) -> None:
        if not self.pending:
            return
        pending = self.pending
        self.pending = None
        responses = list(pending.get("responses", []))
        source = pending["from"]
        tile = pending["tile"]
        response_kind = pending.get("response_kind")
        actionable = [item for item in responses if RESPONSE_ACTION_PRIORITY.get(item.get("action", {}).get("type"), 0) > 0]
        if not actionable:
            if response_kind == "rob_gang":
                self._finalize_bu_gang(source, tile)
            else:
                self._mark_latest_discard_unclaimed(source, tile)
                self._start_turn((source + 1) % 4)
            return
        actionable.sort(key=lambda item: (-RESPONSE_ACTION_PRIORITY.get(item["action"].get("type"), 0), item.get("order_index", 99)))
        winner = actionable[0]
        seat = int(winner["seat"])
        action = winner["action"]
        kind = action["type"]
        if kind == "hu":
            if response_kind == "rob_gang":
                self._finish_win(seat, "rob_gang", discarder=source, win_tile=tile)
            else:
                self._finish_win(seat, self._win_type_for_discard(source, tile), discarder=source, win_tile=tile)
            return
        if kind == "chi":
            self._execute_claim(seat, source, tile, "chi", action.get("tiles", []))
            return
        if kind in CLAIM_ACTION_TYPES:
            self._execute_claim(seat, source, tile, kind)
            return
        if response_kind == "rob_gang":
            self._finalize_bu_gang(source, tile)
        else:
            self._start_turn((source + 1) % 4)

    def _execute_turn_action(self, seat: int, action: dict[str, Any], record: bool = True) -> None:
        kind = action["type"]
        if kind == "hu":
            win_type = self.pending_self_win_type.get(seat, "自摸")
            self._finish_win(seat, win_type, win_tile=self.last_draw.get(seat))
            return
        if kind == "an_gang":
            self._execute_an_gang(seat, action["tile"])
            return
        if kind == "bu_gang":
            self._try_bu_gang(seat, action["tile"])
            return
        if kind == "discard":
            self._discard(seat, action["tile"])
            return
        if kind == "pass":
            return
        raise ValueError(f"未知行动：{action}")

    def _execute_an_gang(self, seat: int, tile: str) -> None:
        player = self.players[seat]
        if tile in self.de_set or player.hand.get(tile, 0) < 4:
            raise ValueError("暗杠必须是 4 张相同真实牌，且不能使用得")
        player.hand[tile] -= 4
        if player.hand[tile] <= 0:
            player.hand.pop(tile, None)
        meld = {"type": "an_gang", "tile": tile, "tiles": [tile] * 4, "from": seat}
        player.melds.append(meld)
        self._log("kong", f"{self._seat_label(seat)}暗杠 {tile_name(tile)}", seat=seat, tile=tile, kind="an_gang")
        self._kong_supplement(seat)

    def _try_bu_gang(self, seat: int, tile: str) -> None:
        player = self.players[seat]
        if tile not in self.de_set and player.hand.get(tile, 0) >= 1:
            self._start_response_poll("rob_gang", seat, tile)
            return
        if tile in self.de_set or player.hand.get(tile, 0) < 1:
            raise ValueError("补杠必须补真实牌，且不能使用得")
        robbers = [p for p in range(4) if p != seat and self._can_player_win_with_tile(p, tile)]
        if self.defer_ai_responses and robbers:
            human_actions = [{"type": "hu", "tile": tile}, {"type": "pass"}] if self._is_human_actor(self.human_seat) and self.human_seat in robbers else []
            self._set_deferred_pending(
                "rob_gang",
                seat,
                tile,
                human_actions=human_actions,
                ai_candidates=[p for p in robbers if not self._is_human_actor(p)],
                ai_action={"type": "hu", "tile": tile},
            )
            self._log("prompt", f"等待响应抢杠 {tile_name(tile)}")
            return
        ai_robbers = [p for p in robbers if not self._is_human_actor(p) and self._ai_yes_no(p, {"type": "hu", "tile": tile}, "rob_gang")]
        if self._is_human_actor(self.human_seat) and self.human_seat in robbers:
            legal = [{"type": "hu", "tile": tile}, {"type": "pass"}]
            self.pending = {
                "kind": "rob_gang",
                "from": seat,
                "tile": tile,
                "ai_robbers": ai_robbers,
                "human_actions": legal,
            }
            self._log("prompt", f"等待人类选择是否抢杠 {tile_name(tile)}")
            return
        if ai_robbers:
            winner = self._priority_winner(seat, ai_robbers)
            self._finish_win(winner, "抢杠和", discarder=seat, win_tile=tile)
            return
        self._finalize_bu_gang(seat, tile)

    def _finalize_bu_gang(self, seat: int, tile: str) -> None:
        player = self.players[seat]
        player.hand[tile] -= 1
        if player.hand[tile] <= 0:
            player.hand.pop(tile, None)
        for meld in player.melds:
            if meld["type"] == "peng" and meld["tile"] == tile:
                meld["type"] = "bu_gang"
                meld["tiles"].append(tile)
                break
        self._log("kong", f"{self._seat_label(seat)}补杠 {tile_name(tile)}", seat=seat, tile=tile, kind="bu_gang")
        self._kong_supplement(seat)

    def _kong_supplement(self, seat: int) -> None:
        self._update_wall_phase()
        if self.phase == "round_over":
            return
        tile = self._draw_supplement_tile(seat, "杠后补牌")
        if not tile:
            return
        self._give_drawn_tile(seat, tile)
        self.last_draw[seat] = tile
        self.pending_self_win_type[seat] = "杠上开花"
        self._replenish_flowers_after_draw(seat)
        if self.phase == "round_over":
            return
        if self._finish_leizi_if_present(seat):
            return
        self.current_player = seat
        self.phase = "turn"

    def _next_discard_event_id(self) -> str:
        self._discard_event_seq += 1
        return f"d{self.round_no}-{self._discard_event_seq}"

    def _latest_discard_event(self, discarder: int | None = None, tile: str | None = None) -> dict[str, Any] | None:
        for event in reversed(self.discard_events):
            if discarder is not None and event.get("seat") != discarder:
                continue
            if tile is not None and event.get("tile") != tile:
                continue
            return event
        return None

    def _create_discard_event(self, seat: int, tile: str) -> dict[str, Any]:
        cleared_warning = self.claim_warnings.pop(seat, None)
        event = {
            "id": self._next_discard_event_id(),
            "seat": seat,
            "tile": tile,
            "discard_index": len(self.players[seat].discards),
            "is_fresh_tile": tile not in self.discarded_tile_kinds,
            "bao_phase": self.bao_phase,
            "shanten_before_discard": shanten(self.players[seat].hand, self.de_set),
            "claimed_by": None,
            "claim_type": None,
            "cleared_claim_warning": bool(cleared_warning),
        }
        self.discard_events.append(event)
        self.discarded_tile_kinds.add(tile)
        return event

    def _mark_latest_discard_unclaimed(self, discarder: int, tile: str) -> None:
        event = self._latest_discard_event(discarder, tile)
        if event is not None:
            event["resolved"] = True
        self.claimed_discard_streaks[discarder] = []

    def _mark_discard_claimed(self, discarder: int, tile: str, claimer: int, claim_type: str) -> dict[str, Any] | None:
        event = self._latest_discard_event(discarder, tile)
        if event is not None:
            event["claimed_by"] = claimer
            event["claim_type"] = claim_type
            event["resolved"] = True
        self._record_claimed_discard_streak(discarder, claimer, claim_type, event)
        if claim_type in CLAIM_ACTION_TYPES or claim_type == "chi":
            self._set_temporary_bao_after_open_claim(claimer, event["id"] if event else "")
        return event

    def _record_claimed_discard_streak(
        self,
        discarder: int,
        claimer: int,
        claim_type: str,
        event: dict[str, Any] | None,
    ) -> None:
        if event is None:
            return
        streak = self.claimed_discard_streaks.setdefault(discarder, [])
        expected_index = streak[-1]["discard_index"] + 1 if streak else event["discard_index"]
        if event["discard_index"] != expected_index:
            streak.clear()
        streak.append(
            {
                "discard_event_id": event["id"],
                "discard_index": event["discard_index"],
                "claimer": claimer,
                "claim_type": claim_type,
            }
        )
        del streak[:-3]
        last_two = streak[-2:]
        if (
            len(last_two) == 2
            and not event.get("cleared_claim_warning")
            and len({item["claimer"] for item in last_two}) == 1
            and all(item["claim_type"] in CLAIM_ACTION_TYPES or item["claim_type"] == "chi" for item in last_two)
        ):
            self.claim_warnings[discarder] = {
                "seat": discarder,
                "claimed_by": claimer,
                "source_event_id": event["id"],
                "reason": f"连续2张舍牌被{self._seat_label(claimer)}吃碰杠",
            }
        if len(streak) == 3 and len({item["claimer"] for item in streak}) == 1:
            self._add_bao_liability(
                liable_seat=discarder,
                target_winner=claimer,
                reason=f"连续3张舍牌被{self._seat_label(claimer)}响应",
                source_event_id=event["id"],
            )

    def _add_bao_liability(
        self,
        liable_seat: int,
        target_winner: int | None,
        reason: str,
        source_event_id: str,
        active: bool = True,
    ) -> BaoLiability:
        self._bao_liability_seq += 1
        liability = BaoLiability(
            seq=self._bao_liability_seq,
            liable_seat=liable_seat,
            target_winner=target_winner,
            reason=reason,
            source_event_id=source_event_id,
            active=active,
        )
        self.bao_liabilities.append(liability)
        return liability

    def _serialize_bao_liability(self, liability: BaoLiability) -> dict[str, Any]:
        return {
            "seq": liability.seq,
            "liable_seat": liability.liable_seat,
            "target_winner": liability.target_winner,
            "reason": liability.reason,
            "source_event_id": liability.source_event_id,
            "active": liability.active,
        }

    def _set_temporary_bao_after_open_claim(self, claimer: int, source_event_id: str) -> None:
        if not self.bao_phase:
            return
        if self.temporary_bao_seat is not None and self.temporary_bao_seat != claimer:
            self._clear_temporary_bao("其他玩家吃碰明杠")
        self.temporary_bao_seat = claimer
        self.temporary_bao_reason = "包张阶段吃碰明杠后他家胡牌"
        self.temporary_bao_started_event_id = source_event_id

    def _clear_temporary_bao(self, reason: str = "") -> None:
        self.temporary_bao_seat = None
        self.temporary_bao_reason = ""
        self.temporary_bao_started_event_id = ""

    def _clear_temporary_bao_for_draw(self, seat: int) -> None:
        if self.temporary_bao_seat == seat:
            self._clear_temporary_bao("本人摸牌")

    def _add_final_bao_candidates(
        self,
        winner: int,
        discarder: int | None,
        win_tile: str | None,
    ) -> None:
        event = self._latest_discard_event(discarder, win_tile) if discarder is not None and win_tile else None
        source_event_id = str(event.get("id")) if event else ""
        if discarder is not None and win_tile in {"zhong", "fa"} and event is not None:
            if int(event.get("shanten_before_discard", 99)) > 1:
                self._add_bao_liability(
                    liable_seat=discarder,
                    target_winner=winner,
                    reason=f"向听数大于1时打出{tile_name(win_tile)}放炮",
                    source_event_id=source_event_id,
                )
        if discarder is not None and event is not None and event.get("bao_phase") and event.get("is_fresh_tile"):
            self._add_bao_liability(
                liable_seat=discarder,
                target_winner=winner,
                reason="包张阶段打出生牌放炮",
                source_event_id=source_event_id,
            )
        if self.temporary_bao_seat is not None and self.temporary_bao_seat != winner:
            self._add_bao_liability(
                liable_seat=self.temporary_bao_seat,
                target_winner=winner,
                reason=self.temporary_bao_reason or "包张阶段吃碰明杠后他家胡牌",
                source_event_id=self.temporary_bao_started_event_id,
            )

    def _select_bao_liability(self, winner: int) -> BaoLiability | None:
        applicable = [
            liability
            for liability in self.bao_liabilities
            if liability.active and (liability.target_winner is None or liability.target_winner == winner)
        ]
        if not applicable:
            return None
        return min(applicable, key=lambda liability: liability.seq)

    def _discard(self, seat: int, tile: str) -> None:
        player = self.players[seat]
        if tile in self.de_set:
            raise ValueError("得不能被打出")
        if player.hand.get(tile, 0) <= 0:
            raise ValueError("手牌中没有这张牌")
        discard_event = self._create_discard_event(seat, tile)
        player.hand[tile] -= 1
        if player.hand[tile] <= 0:
            player.hand.pop(tile, None)
        player.discards.append(tile)
        self.last_draw.pop(seat, None)
        self.pending_self_win_type.pop(seat, None)
        self._log(
            "discard",
            f"{self._seat_label(seat)}打出 {tile_name(tile)}",
            seat=seat,
            tile=tile,
            discard_event_id=discard_event["id"],
            is_fresh_tile=discard_event["is_fresh_tile"],
            shanten_before_discard=discard_event["shanten_before_discard"],
        )
        self._open_discard_response(seat, tile)

    def _claim_actions_for_seat(self, seat: int, tile: str) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = []
        if self.players[seat].hand.get(tile, 0) >= 4:
            return actions
        if can_ming_gang(self.players[seat].hand, tile, self.de_set):
            actions.append({"type": "ming_gang", "tile": tile})
        if can_peng(self.players[seat].hand, tile, self.de_set):
            actions.append({"type": "peng", "tile": tile})
        return actions

    def _can_execute_claim(
        self,
        claimer: int,
        tile: str,
        kind: str,
        chi_tiles: list[str] | None = None,
    ) -> bool:
        if claimer < 0 or claimer >= len(self.players):
            return False
        hand = self.players[claimer].hand
        if kind in {"ming_gang", "peng"} and hand.get(tile, 0) >= 4:
            return False
        if kind == "ming_gang":
            return can_ming_gang(hand, tile, self.de_set)
        if kind == "peng":
            return can_peng(hand, tile, self.de_set)
        if kind == "chi":
            needed = Counter(chi_tiles or [])
            return bool(needed) and all(hand.get(code, 0) >= count for code, count in needed.items())
        return False

    def _claim_actions_by_seat(self, discarder: int, tile: str) -> dict[int, list[dict[str, Any]]]:
        return {
            seat: actions
            for seat in range(4)
            if seat != discarder
            for actions in [self._claim_actions_for_seat(seat, tile)]
            if actions
        }

    def _choose_ai_claim_action(self, seat: int, legal: list[dict[str, Any]]) -> dict[str, Any]:
        obs = self.observation(seat)
        action = self._model_for(seat).choose_action(obs, legal, explore=0.04 if self.training else 0.0)
        self.decisions.append({"player": seat, "observation": obs, "legal_actions": legal, "action": action})
        return action

    def _open_claim_response(self, discarder: int, tile: str) -> None:
        claim_actions = self._claim_actions_by_seat(discarder, tile)
        if not claim_actions:
            self._open_discard_response_after_claim_pass(discarder, tile, "claim")
            return

        if self.defer_ai_responses:
            human_actions = []
            if self._is_human_actor(self.human_seat) and self.human_seat in claim_actions:
                human_actions = list(claim_actions[self.human_seat]) + [{"type": "pass"}]
            ai_candidates = [seat for seat in claim_actions if not self._is_human_actor(seat)]
            ai_legal_actions = {seat: list(claim_actions[seat]) + [{"type": "pass"}] for seat in ai_candidates}
            self._set_deferred_pending(
                "claim",
                discarder,
                tile,
                human_actions=human_actions,
                ai_candidates=ai_candidates,
                ai_legal_actions=ai_legal_actions,
            )
            return

        ai_claims: list[dict[str, Any]] = []
        for seat, actions in claim_actions.items():
            if self._is_human_actor(seat):
                continue
            action = self._choose_ai_claim_action(seat, list(actions) + [{"type": "pass"}])
            if action.get("type") in CLAIM_ACTION_TYPES:
                ai_claims.append({"seat": seat, "action": action})

        if self._is_human_actor(self.human_seat) and self.human_seat in claim_actions:
            self.pending = {
                "kind": "claim",
                "from": discarder,
                "tile": tile,
                "ai_claim_actions": ai_claims,
                "human_actions": list(claim_actions[self.human_seat]) + [{"type": "pass"}],
            }
            return

        if ai_claims:
            winner = self._priority_winner(discarder, [item["seat"] for item in ai_claims])
            action = next(item["action"] for item in ai_claims if item["seat"] == winner)
            self._execute_claim(winner, discarder, tile, action["type"])
            return

        self._open_discard_response_after_claim_pass(discarder, tile, "claim")

    def _open_discard_response(self, discarder: int, tile: str) -> None:
        self._start_response_poll("discard", discarder, tile)
        return
        hu_candidates = [p for p in range(4) if p != discarder and self._can_player_win_with_tile(p, tile)]
        if self.defer_ai_responses and hu_candidates:
            self._set_deferred_pending(
                "discard_hu",
                discarder,
                tile,
                human_actions=[{"type": "hu", "tile": tile}, {"type": "pass"}] if self._is_human_actor(self.human_seat) and self.human_seat in hu_candidates else [],
                ai_candidates=[p for p in hu_candidates if not self._is_human_actor(p)],
                ai_action={"type": "hu", "tile": tile},
            )
            return
        ai_hu = [p for p in hu_candidates if not self._is_human_actor(p) and self._ai_yes_no(p, {"type": "hu", "tile": tile}, "discard_hu")]
        if self._is_human_actor(self.human_seat) and self.human_seat in hu_candidates:
            self.pending = {
                "kind": "discard_hu",
                "from": discarder,
                "tile": tile,
                "ai_hu": ai_hu,
                "human_actions": [{"type": "hu", "tile": tile}, {"type": "pass"}],
            }
            return
        if ai_hu:
            self._finish_win(
                self._priority_winner(discarder, ai_hu),
                self._win_type_for_discard(discarder, tile),
                discarder=discarder,
                win_tile=tile,
            )
            return

        self._open_claim_response(discarder, tile)

    def _resolve_pending_with_human(self, action: dict[str, Any]) -> None:
        assert self.pending is not None
        if self.pending.get("kind") == "response_poll":
            order_index = (self.pending.get("order_index_by_seat") or {}).get(self.human_seat, 99)
            self.pending.setdefault("decisions_by_seat", {})[self.human_seat] = dict(action)  # type: ignore[index]
            self._record_response_poll_action(self.human_seat, action, int(order_index))  # type: ignore[arg-type]
            if self.human_seat == self.pending.get("current_responder"):
                self.pending["human_actions"] = []
            self.pending["current_responder"] = None
            self.pending["current_legal_actions"] = []
            self._resolve_response_poll_step(force=False)
            return
        if self.pending.get("deferred"):
            self.pending["human_action"] = action
            self.pending["human_actions"] = []
            self.resolve_deferred_pending(force=True)
            return
        kind = self.pending["kind"]
        discarder = self.pending["from"]
        tile = self.pending["tile"]
        self.pending["human_actions"] = []

        if kind == "discard_hu":
            winners = list(self.pending.get("ai_hu", []))
            if action["type"] == "hu":
                winners.append(self.human_seat)  # type: ignore[arg-type]
            if winners:
                self.pending = None
                self._finish_win(
                    self._priority_winner(discarder, winners),
                    self._win_type_for_discard(discarder, tile),
                    discarder=discarder,
                    win_tile=tile,
                )
            else:
                self.pending = None
                self._open_discard_response_after_hu_pass(discarder, tile)
            return

        if kind == "rob_gang":
            winners = list(self.pending.get("ai_robbers", []))
            if action["type"] == "hu":
                winners.append(self.human_seat)  # type: ignore[arg-type]
            self.pending = None
            if winners:
                self._finish_win(self._priority_winner(discarder, winners), "抢杠和", discarder=discarder, win_tile=tile)
            else:
                self._finalize_bu_gang(discarder, tile)
            return

        if kind == "claim":
            ai_claim_actions = list(self.pending.get("ai_claim_actions", []))
            self.pending = None
            claim_actions: list[tuple[int, dict[str, Any]]] = []
            if (
                action.get("type") in CLAIM_ACTION_TYPES
                and self.human_seat is not None
                and self._can_execute_claim(self.human_seat, tile, action["type"])
            ):
                claim_actions.append((self.human_seat, action))
            for item in ai_claim_actions:
                ai_action = item.get("action", {})
                if ai_action.get("type") in CLAIM_ACTION_TYPES and self._can_execute_claim(item["seat"], tile, ai_action["type"]):
                    claim_actions.append((item["seat"], ai_action))
            if claim_actions:
                winner = self._priority_winner(discarder, [seat for seat, _ in claim_actions])
                winning_action = next(ai_action for seat, ai_action in claim_actions if seat == winner)
                self._execute_claim(winner, discarder, tile, winning_action["type"])
            else:
                self._open_discard_response_after_claim_pass(discarder, tile, "claim")
            return

        if kind in {"ming_gang", "peng"}:
            ai_claims = list(self.pending.get("ai_claims", []))
            self.pending = None
            if action["type"] == kind and self.human_seat is not None and self._can_execute_claim(self.human_seat, tile, kind):
                self._execute_claim(self.human_seat, discarder, tile, kind)  # type: ignore[arg-type]
            else:
                ai_claims = [seat for seat in ai_claims if self._can_execute_claim(seat, tile, kind)]
                if ai_claims:
                    self._execute_claim(self._priority_winner(discarder, ai_claims), discarder, tile, kind)
                else:
                    self._open_discard_response_after_claim_pass(discarder, tile, kind)
            return

        if kind == "chi":
            self.pending = None
            if action["type"] == "chi":
                self._execute_claim(self.human_seat, discarder, tile, "chi", action.get("tiles", []))  # type: ignore[arg-type]
            else:
                self._mark_latest_discard_unclaimed(discarder, tile)
                self._start_turn((discarder + 1) % 4)
            return

    def _resolve_pending_without_human(self) -> None:
        if not self.pending:
            return
        if self.pending.get("deferred"):
            self.resolve_deferred_pending(force=False)
            return
        # This path is mainly used in all-AI training. Choose pass for absent human prompts.
        legal = self.pending.get("human_actions", [{"type": "pass"}])
        self._resolve_pending_with_human({"type": "pass"} if any(a["type"] == "pass" for a in legal) else legal[0])

    def _open_discard_response_after_hu_pass(self, discarder: int, tile: str) -> None:
        self._open_claim_response(discarder, tile)

    def _open_discard_response_after_claim_pass(self, discarder: int, tile: str, passed_kind: str) -> None:
        next_seat = (discarder + 1) % 4
        chi = chi_options(self.players[next_seat].hand, tile, self.de_set)
        if self.defer_ai_responses and chi:
            legal = [{"type": "chi", "tile": tile, "tiles": option} for option in chi] + [{"type": "pass"}]
            is_human = self._is_human_actor(next_seat)
            if is_human:
                self.human_seat = next_seat
            self._set_deferred_pending(
                "chi",
                discarder,
                tile,
                human_actions=legal if is_human else [],
                ai_candidates=[] if is_human else [next_seat],
                ai_legal_actions=legal,
            )
            return
        if chi and self._is_human_actor(next_seat):
            self.human_seat = next_seat
            self.pending = {
                "kind": "chi",
                "from": discarder,
                "tile": tile,
                "human_actions": [{"type": "chi", "tile": tile, "tiles": option} for option in chi] + [{"type": "pass"}],
            }
            return
        if chi and not self._is_human_actor(next_seat):
            legal = [{"type": "chi", "tile": tile, "tiles": option} for option in chi] + [{"type": "pass"}]
            obs = self.observation(next_seat)
            action = self._model_for(next_seat).choose_action(obs, legal, explore=0.04 if self.training else 0.0)
            self.decisions.append({"player": next_seat, "observation": obs, "legal_actions": legal, "action": action})
            if action["type"] == "chi":
                self._execute_claim(next_seat, discarder, tile, "chi", action.get("tiles", []))
                return
        self._mark_latest_discard_unclaimed(discarder, tile)
        self._start_turn(next_seat)

    def _claimed_discard_index(self, discarder: int, tile: str) -> int | None:
        if discarder < 0 or discarder >= len(self.players):
            return None
        discards = self.players[discarder].discards
        if not discards:
            return None
        if discards[-1] == tile:
            return len(discards) - 1
        for idx in range(len(discards) - 1, -1, -1):
            if discards[idx] == tile:
                return idx
        return None

    def _claim_meld(self, kind: str, tile: str, tiles: list[str], discarder: int) -> dict[str, Any]:
        meld: dict[str, Any] = {"type": kind, "tile": tile, "tiles": tiles, "from": discarder}
        discard_index = self._claimed_discard_index(discarder, tile)
        if discard_index is not None:
            meld["discard_index"] = discard_index
        return meld

    def _execute_claim(self, claimer: int, discarder: int, tile: str, kind: str, chi_tiles: list[str] | None = None) -> None:
        player = self.players[claimer]
        chi_tiles = chi_tiles or []
        if kind == "ming_gang":
            if not self._can_execute_claim(claimer, tile, kind):
                raise ValueError("当前不能明杠这张牌")
            for _ in range(3):
                player.hand[tile] -= 1
            if player.hand[tile] <= 0:
                player.hand.pop(tile, None)
            meld = self._claim_meld("ming_gang", tile, [tile] * 4, discarder)
            player.melds.append(meld)
            self._mark_discard_claimed(discarder, tile, claimer, "ming_gang")
            self._record_open_claim(claimer)
            self._log("claim", f"{self._seat_label(claimer)}明杠 {tile_name(tile)}", seat=claimer, tile=tile, kind="ming_gang")
            self._kong_supplement(claimer)
            return
        if kind == "peng":
            if not self._can_execute_claim(claimer, tile, kind):
                raise ValueError("当前不能碰这张牌")
            for _ in range(2):
                player.hand[tile] -= 1
            if player.hand[tile] <= 0:
                player.hand.pop(tile, None)
            player.melds.append(self._claim_meld("peng", tile, [tile] * 3, discarder))
            self._mark_discard_claimed(discarder, tile, claimer, "peng")
            self._record_open_claim(claimer)
            self._log("claim", f"{self._seat_label(claimer)}碰 {tile_name(tile)}", seat=claimer, tile=tile, kind="peng")
            self._start_turn(claimer)
            return
        if kind == "chi":
            if not self._can_execute_claim(claimer, tile, kind, chi_tiles):
                raise ValueError("当前不能吃这张牌")
            for code in chi_tiles:
                player.hand[code] -= 1
                if player.hand[code] <= 0:
                    player.hand.pop(code, None)
            tiles = sorted_tiles([tile] + chi_tiles)
            player.melds.append(self._claim_meld("chi", tile, tiles, discarder))
            self._mark_discard_claimed(discarder, tile, claimer, "chi")
            self._record_open_claim(claimer)
            self._log("claim", f"{self._seat_label(claimer)}吃 {'、'.join(tile_name(c) for c in tiles)}", seat=claimer, tile=tile, kind="chi", tiles=tiles)
            self._start_turn(claimer)

    def _can_player_win_with_tile(self, seat: int, tile: str) -> bool:
        if tile in self.de_set:
            return False
        if self.players[seat].hand.get(tile, 0) >= 4:
            return False
        hand = Counter(self.players[seat].hand)
        hand[tile] += 1
        return shanten(hand, self.de_set) == -1

    def _ai_yes_no(self, seat: int, yes_action: dict[str, Any], context: str) -> bool:
        legal = [yes_action, {"type": "pass"}]
        obs = self.observation(seat)
        action = self._model_for(seat).choose_action(obs, legal, explore=0.05 if self.training else 0.0)
        self.decisions.append({"player": seat, "observation": obs, "legal_actions": legal, "action": action})
        return action["type"] != "pass"

    def _priority_winner(self, discarder: int, candidates: list[int]) -> int:
        order = [(discarder + 1) % 4, (discarder + 2) % 4, (discarder + 3) % 4]
        for seat in order:
            if seat in candidates:
                return seat
        return candidates[0]

    def _win_type_for_discard(self, discarder: int, tile: str) -> str:
        return "普通和牌"

    def _finish_leizi_if_present(self, seat: int) -> bool:
        reason = leizi_win_reason(
            self.players[seat].hand,
            self.players[seat].flowers,
            self.de_indicator,
            self.de_set,
            self._seat_wind_index(seat),
        )
        if not reason:
            return False
        self._finish_win(seat, "劣子和", reason=reason)
        return True

    def _finish_tianhu_if_present(self) -> bool:
        seat = self.dealer
        if self.phase == "round_over":
            return False
        if not can_win(self.players[seat].hand, self.de_set, self.players[seat].melds):
            return False
        self._finish_win(seat, "天胡")
        return True

    @staticmethod
    def _settle_score_differences(deltas: list[int], scores: list[dict[str, Any]], seats: list[int]) -> None:
        for i, a in enumerate(seats):
            for b in seats[i + 1 :]:
                diff = abs(scores[a]["total"] - scores[b]["total"])
                if scores[a]["total"] > scores[b]["total"]:
                    deltas[a] += diff
                    deltas[b] -= diff
                elif scores[b]["total"] > scores[a]["total"]:
                    deltas[b] += diff
                    deltas[a] -= diff

    @staticmethod
    def _zero_bao_score() -> dict[str, Any]:
        return {
            "base": 0,
            "fan": 0,
            "total": 0,
            "raw_total": 0,
            "limit_reason": "包牌者按0点非胡牌者参与结算",
            "plan": [],
            "base_items": [{"label": "包牌按0点结算", "points": 0}],
            "fan_items": [],
            "winning_shape": False,
        }

    @staticmethod
    def _append_transaction(
        transactions: list[dict[str, Any]],
        payer: int,
        receiver: int,
        amount: int,
        reason: str,
    ) -> None:
        if amount <= 0 or payer == receiver:
            return
        transactions.append({"from": payer, "to": receiver, "amount": int(amount), "reason": reason})

    def _build_base_transactions(self, scores: list[dict[str, Any]], winner: int) -> list[dict[str, Any]]:
        transactions: list[dict[str, Any]] = []
        winner_pay = int(scores[winner]["total"])
        for seat in range(4):
            if seat != winner:
                self._append_transaction(transactions, seat, winner, winner_pay, "胡牌支付")
        non_winners = [p for p in range(4) if p != winner]
        for i, a in enumerate(non_winners):
            for b in non_winners[i + 1 :]:
                total_a = int(scores[a]["total"])
                total_b = int(scores[b]["total"])
                diff = abs(total_a - total_b)
                if total_a > total_b:
                    self._append_transaction(transactions, b, a, diff, "非胡牌者牌面点差")
                elif total_b > total_a:
                    self._append_transaction(transactions, a, b, diff, "非胡牌者牌面点差")
        return transactions

    def _build_settlement_transactions(
        self,
        scores: list[dict[str, Any]],
        winner: int,
        bao: BaoLiability | None = None,
    ) -> list[dict[str, Any]]:
        base_transactions = self._build_base_transactions(scores, winner)
        if bao is None:
            return base_transactions
        redirected: list[dict[str, Any]] = []
        bao_seat = bao.liable_seat
        for transaction in base_transactions:
            receiver = int(transaction["to"])
            if receiver == bao_seat:
                continue
            redirected.append(
                {
                    **transaction,
                    "from": bao_seat,
                    "original_from": transaction["from"],
                    "reason": f"包牌承担：{transaction['reason']}",
                }
            )
        return redirected

    @staticmethod
    def _deltas_from_transactions(transactions: list[dict[str, Any]]) -> list[int]:
        deltas = [0, 0, 0, 0]
        for transaction in transactions:
            payer = int(transaction["from"])
            receiver = int(transaction["to"])
            amount = int(transaction["amount"])
            deltas[payer] -= amount
            deltas[receiver] += amount
        return deltas

    def _finish_win(
        self,
        winner: int,
        win_type: str,
        discarder: int | None = None,
        reason: str = "",
        win_tile: str | None = None,
    ) -> None:
        self.winner = winner
        self.win_type = win_type
        self.phase = "round_over"
        if discarder is not None and win_tile:
            self._mark_discard_claimed(discarder, win_tile, winner, "hu")
        self._add_final_bao_candidates(winner, discarder, win_tile)
        bao = self._select_bao_liability(winner)
        scores = []
        final_hands: list[Counter[str]] = []
        for seat, player in enumerate(self.players):
            scoring_hand = Counter(player.hand)
            if seat == winner and win_tile and discarder is not None:
                scoring_hand[win_tile] += 1
            final_hands.append(Counter(scoring_hand))
            scores.append(
                score_player(
                    scoring_hand,
                    player.flowers,
                    player.melds,
                    self._seat_wind_index(seat),
                    self.de_set,
                    self.de_indicator,
                    winner=seat == winner,
                    win_type=win_type,
                    win_tile=win_tile if seat == winner else None,
                )
            )
        if bao is not None:
            scores[bao.liable_seat] = self._zero_bao_score()
        winner_points = int(scores[winner].get("total") or 0)
        win_turn = self._record_win_stats(winner, winner_points)
        transactions = self._build_settlement_transactions(scores, winner, bao)
        deltas = self._deltas_from_transactions(transactions)
        for seat, delta in enumerate(deltas):
            self.players[seat].chips += delta
        hand_luck = self._record_hand_luck(winner, final_hands, win_type=win_type)

        self.settlement = {
            "winner": winner,
            "discarder": discarder,
            "win_type": win_type,
            "reason": reason,
            "win_tile": win_tile,
            "win_turn": win_turn,
            "win_points": winner_points,
            "scores": scores,
            "deltas": deltas,
            "point_deltas": list(deltas),
            "hand_luck": hand_luck,
            "transactions": transactions,
            "bao": {
                "seat": bao.liable_seat,
                "reason": bao.reason,
                "target_winner": bao.target_winner,
                "source_event_id": bao.source_event_id,
            } if bao is not None else None,
            "duration_sec": round(time.time() - self.round_started_at, 2),
        }
        self._log("win", f"{self._seat_label(winner)}{win_type}，筹码变化 {deltas}", winner=winner, win_type=win_type, reason=reason)
        recorder = getattr(self, "stats_recorder", None)
        if recorder is not None:
            recorder.record_win(self._stats_key(winner), win_type, win_turn=win_turn, win_points=winner_points)
        if self.persist_logs:
            self._persist_round_log()
        if winner == self.dealer:
            self.next_dealer = self.dealer
        else:
            self.next_dealer = (self.dealer + 1) % 4

    def _draw_game(self, reason: str) -> None:
        if self.phase == "round_over":
            return
        self.phase = "round_over"
        self.winner = None
        self.win_type = "黄牌"
        hand_luck = self._record_hand_luck(None)
        self.settlement = {
            "winner": None,
            "discarder": None,
            "win_type": "黄牌",
            "reason": reason,
            "scores": [],
            "deltas": [0, 0, 0, 0],
            "point_deltas": [0, 0, 0, 0],
            "hand_luck": hand_luck,
            "duration_sec": round(time.time() - self.round_started_at, 2),
        }
        self._log("draw_game", f"黄牌：{reason}")
        if self.persist_logs:
            self._persist_round_log()
        self.next_dealer = self.dealer

    def observation(self, seat: int) -> dict[str, Any]:
        player = self.players[seat]
        public_players = []
        for idx, other in enumerate(self.players):
            public_players.append(
                {
                    "seat": idx,
                    "name": other.name,
                    "wind": self._seat_wind(idx),
                    "wind_index": self._seat_wind_index(idx),
                    "melds": other.melds,
                    "discards": other.discards,
                    "flowers": list(other.flowers),
                    "flower_count": len(other.flowers),
                    "hand_count": sum(other.hand.values()),
                    "chips": other.chips,
                    "claim_warning": self.claim_warnings.get(idx),
                }
            )
        return {
            "seat": seat,
            "hand": dict(player.hand),
            "last_draw": self.last_draw.get(seat)
            if self.last_draw.get(seat) in player.hand
            else None,
            "flowers": list(player.flowers),
            "de_count": sum(player.hand.get(code, 0) for code in self.de_set),
            "public": {
                "round_no": self.round_no,
                "dealer": self.dealer,
                "current_player": self.current_player,
                "wall_remaining": len(self.wall),
                "wall_to_draw_game": self._wall_to_draw_game(),
                "bao_phase": self.bao_phase,
                "supplement_count": self.supplement_count,
                "bao_phase_wall_threshold": self.bao_phase_wall_threshold,
                "draw_wall_threshold": self.draw_wall_threshold,
                "center_indicator_mode": "bao" if self.bao_phase else "de",
                "discarded_tile_kinds": sorted(self.discarded_tile_kinds),
                "temporary_bao": {
                    "seat": self.temporary_bao_seat,
                    "reason": self.temporary_bao_reason,
                    "source_event_id": self.temporary_bao_started_event_id,
                }
                if self.temporary_bao_seat is not None
                else None,
                "de_indicator": self.de_indicator,
                "de_set": sorted(self.de_set),
                "flower_set": sorted(self.flower_set),
                "players": public_players,
                "history": self.history[-24:],
            },
        }

    def serialize(self, viewer_seat: int | None = None) -> dict[str, Any]:
        active_human_seat = self.human_seat if viewer_seat is None else viewer_seat
        players = []
        for seat, player in enumerate(self.players):
            show_hand = seat == active_human_seat or self.training or self.phase == "round_over"
            players.append(
                {
                    "seat": seat,
                    "name": player.name,
                    "wind": self._seat_wind(seat),
                    "wind_index": self._seat_wind_index(seat),
                    "label": self._seat_label(seat),
                    "is_human": seat == active_human_seat,
                    "hand": dict(player.hand) if show_hand else {},
                    "last_draw": self.last_draw.get(seat)
                    if show_hand
                    and seat == self.current_player
                    and self.phase == "turn"
                    and self.last_draw.get(seat) in player.hand
                    else None,
                    "hand_count": sum(player.hand.values()),
                    "flowers": list(player.flowers),
                    "flower_count": len(player.flowers),
                    "melds": player.melds,
                    "discards": player.discards,
                    "chips": player.chips,
                    "claim_warning": self.claim_warnings.get(seat),
                }
            )
        if self.pending:
            current_responder = self.pending.get("current_responder")
            if self.pending.get("kind") == "response_poll":
                actions = self._pending_actions_for_seat(active_human_seat)
            elif active_human_seat is not None and current_responder in {None, active_human_seat}:
                actions = list(self.pending.get("human_actions") or [])
            else:
                actions = []
        elif active_human_seat is not None and self.phase == "turn" and self.current_player == active_human_seat:
            actions = self.legal_turn_actions(active_human_seat)
        else:
            actions = []
        safe_pending = None
        if self.pending:
            decision_seats = sorted(int(seat) for seat in (self.pending.get("decisions_by_seat") or {}).keys())
            responders = [int(seat) for seat in self.pending.get("responders", [])]
            safe_pending = {
                "kind": self.pending.get("kind"),
                "source_event_id": self.pending.get("source_event_id"),
                "created_at": self.pending.get("created_at"),
                "response_kind": self.pending.get("response_kind"),
                "from": self.pending.get("from"),
                "tile": self.pending.get("tile"),
                "deferred": bool(self.pending.get("deferred")),
                "deadline": self.pending.get("deadline"),
                "responders": responders,
                "waiting_for_seats": [seat for seat in responders if seat not in decision_seats],
                "poll_index": self.pending.get("poll_index"),
                "ai_candidates": list(self.pending.get("ai_candidates", [])),
                "pending_id": self.pending.get("pending_id"),
                "room_generation": self.pending.get("room_generation"),
                "decision_seats": decision_seats,
            }
        return {
            "round_no": self.round_no,
            "phase": self.phase,
            "pending": safe_pending,
            "server_time": time.time(),
            "dealer": self.dealer,
            "next_dealer": self.next_dealer,
            "current_player": self.current_player,
            "wall_remaining": len(self.wall),
            "wall_to_draw_game": self._wall_to_draw_game(),
            "bao_phase": self.bao_phase,
            "supplement_count": self.supplement_count,
            "bao_phase_wall_threshold": self.bao_phase_wall_threshold,
            "draw_wall_threshold": self.draw_wall_threshold,
            "center_indicator_mode": "bao" if self.bao_phase else "de",
            "discarded_tile_kinds": sorted(self.discarded_tile_kinds),
            "de_indicator": self.de_indicator,
            "de_set": sorted(self.de_set),
            "flower_set": sorted(self.flower_set),
            "players": players,
            "legal_actions": actions,
            "history": self.history[-80:],
            "discard_events": list(self.discard_events),
            "bao_liabilities": [self._serialize_bao_liability(item) for item in self.bao_liabilities],
            "claim_warnings": {str(seat): dict(warning) for seat, warning in self.claim_warnings.items()},
            "temporary_bao": {
                "seat": self.temporary_bao_seat,
                "reason": self.temporary_bao_reason,
                "source_event_id": self.temporary_bao_started_event_id,
            }
            if self.temporary_bao_seat is not None
            else None,
            "winner": self.winner,
            "win_type": self.win_type,
            "settlement": self.settlement,
            "analysis": self.human_analysis,
            "player_stats": self.player_stat_summary(),
        }

    def final_rewards(self) -> dict[int, float]:
        if not self.settlement:
            return {i: 0.0 for i in range(4)}
        return {i: float(delta) for i, delta in enumerate(self.settlement.get("deltas", [0, 0, 0, 0]))}

    def _record_human_decision(self, seat: int, action: dict[str, Any], legal: list[dict[str, Any]]) -> None:
        obs = self.observation(seat)
        if getattr(self.model, "backend", "") == "tile_efficiency":
            explanation = {
                "score": 100,
                "chosen": action_label(action),
                "best": None,
                "reason": "牌效模型的人类详细复盘已跳过，避免在人机对战中阻塞出牌响应。",
                "ranked": [],
            }
        else:
            explanation = self.model.explain_decision(obs, action, legal)
        explanation.update(
            {
                "round_no": self.round_no,
                "turn": len(self.history),
                "action": action,
                "context": "响应操作" if self.pending else "回合操作",
            }
        )
        self.human_analysis.append(explanation)

    def _log(self, event: str, message: str, **data: Any) -> None:
        entry = {"ts": round(time.time(), 3), "event": event, "message": message, **data}
        self.history.append(entry)

    def _persist_round_log(self) -> None:
        path = self.log_dir / f"round_{int(time.time())}_{self.round_no}.json"
        payload = {
            "round_no": self.round_no,
            "de_indicator": self.de_indicator,
            "de_set": sorted(self.de_set),
            "flower_set": sorted(self.flower_set),
            "wall_remaining": len(self.wall),
            "wall_to_draw_game": self._wall_to_draw_game(),
            "bao_phase": self.bao_phase,
            "supplement_count": self.supplement_count,
            "bao_phase_wall_threshold": self.bao_phase_wall_threshold,
            "draw_wall_threshold": self.draw_wall_threshold,
            "center_indicator_mode": "bao" if self.bao_phase else "de",
            "discarded_tile_kinds": sorted(self.discarded_tile_kinds),
            "discard_events": self.discard_events,
            "bao_liabilities": [self._serialize_bao_liability(item) for item in self.bao_liabilities],
            "claim_warnings": {str(seat): dict(warning) for seat, warning in self.claim_warnings.items()},
            "history": self.history,
            "settlement": self.settlement,
            "analysis": self.human_analysis,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _seat_label(self, seat: int) -> str:
        return f"{self._seat_wind(seat)} {self.players[seat].name}"

    def _seat_wind_index(self, seat: int) -> int:
        return (seat - self.dealer) % 4

    def _seat_wind(self, seat: int) -> str:
        return ["东", "南", "西", "北"][self._seat_wind_index(seat)]

    def _tile_list(self, tiles: list[str]) -> str:
        return "、".join(tile_name(code) for code in tiles)
