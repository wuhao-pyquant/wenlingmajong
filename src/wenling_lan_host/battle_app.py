from __future__ import annotations

import threading
import json
import gc
import os
import platform
import random
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any

from .battle_db import AI_ACCOUNTS, BattleDatabase
from .bug_reports import BUG_REPORT_SCHEMA_VERSION, BugReportStore, json_safe
from wenling_core.game import WenlingMahjongGame
from wenling_core.tiles import TILE_ORDER, build_wall, is_suited
from wenling_core.validation import validate_game_state


PRESENCE_ONLINE_SEC = 35.0
PRESENCE_SWEEP_SEC = 1.0
BATTLE_ACTION_DELAY_SEC = 0.0
BATTLE_AI_DECISION_TIMEOUT_SEC = 8.0
RUNTIME_EVENT_LOG_LIMIT = 50
SLOW_API_THRESHOLD_MS = 200.0
BUG_SNAPSHOT_INTERVAL_SEC = 0.5
AI_POLICY_LOW = "low"
AI_POLICY_HIGH = "high"
DEFAULT_AI_POLICY = AI_POLICY_LOW
AVAILABLE_AI_POLICIES = [AI_POLICY_LOW, AI_POLICY_HIGH]
AI_POLICY_ALIASES = {
    "low": AI_POLICY_LOW,
    "low_latency": AI_POLICY_LOW,
    "fast": AI_POLICY_LOW,
    "medium": AI_POLICY_HIGH,
    "normal": AI_POLICY_HIGH,
    "tile_efficiency": AI_POLICY_HIGH,
    "high": AI_POLICY_HIGH,
    "unlimited": AI_POLICY_HIGH,
}
AI_POLICY_LABELS = {
    AI_POLICY_LOW: "低级",
    AI_POLICY_HIGH: "高级",
}
AI_POLICY_TIMEOUTS = {
    AI_POLICY_LOW: 0.1,
    AI_POLICY_HIGH: 60.0 * 60.0,
}


class LowLatencyPolicyModel:
    """Very cheap runtime policy for constrained Android hosts.

    It intentionally avoids normal shanten / ukeire search. The goal is to keep
    LAN play responsive on phones; desktop debug still uses the full
    TileEfficiencyPolicyModel.
    """

    backend = "low_latency"

    def summary(self) -> dict[str, Any]:
        return {"backend": self.backend, "trained_games": 0, "experience_count": 0, "weights": 0}

    def choose_action(
        self,
        observation: dict[str, Any],
        legal_actions: list[dict[str, Any]],
        explore: float = 0.0,
    ) -> dict[str, Any]:
        if not legal_actions:
            return {"type": "pass"}
        hu = next((dict(action) for action in legal_actions if action.get("type") == "hu"), None)
        if hu is not None:
            return hu
        discards = [dict(action) for action in legal_actions if action.get("type") == "discard"]
        if discards:
            last_draw = str(observation.get("last_draw") or "")
            if last_draw:
                drawn_discard = next(
                    (action for action in discards if str(action.get("tile") or "") == last_draw),
                    None,
                )
                if drawn_discard is not None:
                    return drawn_discard
            return min(discards, key=lambda action: self._discard_keep_score(observation, str(action.get("tile") or "")))
        pass_action = next((dict(action) for action in legal_actions if action.get("type") == "pass"), None)
        if pass_action is not None:
            return pass_action
        return dict(legal_actions[0])

    def score_action(self, observation: dict[str, Any], action: dict[str, Any]) -> float:
        if action.get("type") == "hu":
            return 10_000.0
        if action.get("type") == "discard":
            keep, count_bias, order = self._discard_keep_score(observation, str(action.get("tile") or ""))
            return -float(keep * 1000 + count_bias * 10 + order / 100.0)
        if action.get("type") == "pass":
            return 0.0
        return -10.0

    def score_actions(
        self,
        observation: dict[str, Any],
        legal_actions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows = [
            {"action": dict(action), "label": str(action.get("type") or ""), "score": self.score_action(observation, action)}
            for action in legal_actions
        ]
        rows.sort(key=lambda item: float(item["score"]), reverse=True)
        return rows

    def explain_decision(
        self,
        observation: dict[str, Any],
        chosen: dict[str, Any],
        legal_actions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ranked = self.score_actions(observation, legal_actions)[:5]
        return {
            "score": 80,
            "chosen": str(chosen.get("type") or ""),
            "best": ranked[0]["label"] if ranked else None,
            "bad": False,
            "reason": "安卓低延迟模式使用轻量策略，优先保证联机响应速度。",
            "suggestion": "需要完整牌效复盘时使用 PC 端或公网服务端。",
            "ranked": [{"label": item["label"], "score": round(float(item["score"]), 2)} for item in ranked],
        }

    def _discard_keep_score(self, observation: dict[str, Any], tile: str) -> tuple[int, int, int]:
        hand = Counter(observation.get("hand") or {})
        public = observation.get("public") or {}
        de_set = set(public.get("de_set") or observation.get("de_set") or [])
        count = int(hand.get(tile, 0))
        keep = 0
        if tile in de_set:
            keep += 100
        if count >= 2:
            keep += 20 + count * 4
        if is_suited(tile) and len(tile) >= 2:
            suit = tile[0]
            try:
                rank = int(tile[1:])
            except ValueError:
                rank = 0
            for delta, weight in ((-2, 1), (-1, 4), (1, 4), (2, 1)):
                near = rank + delta
                if 1 <= near <= 9:
                    keep += int(hand.get(f"{suit}{near}", 0)) * weight
            if rank in {1, 9}:
                keep -= 2
        else:
            keep += count * 2
        order = TILE_ORDER.index(tile) if tile in TILE_ORDER else 999
        return (keep, -count, order)


class BattleSession:
    def __init__(
        self,
        db: BattleDatabase,
        log_dir: str,
        model_factory: Any,
        analysis_model_factory: Any,
        runtime_context: dict[str, Any] | None = None,
        bug_report_export_dir: str | Path | None = None,
        auto_bug_snapshots: bool = True,
        low_latency_ai: bool = False,
        ticker_interval_sec: float = 0.05,
    ):
        self.db = db
        self.log_dir = log_dir
        self.model_factory = model_factory
        self.analysis_model_factory = analysis_model_factory
        self.lock = threading.RLock()
        self.ai_policy = DEFAULT_AI_POLICY
        self.seats: list[str | None] = [None, None, None, None]
        self.ready: set[str] = set()
        self.game: WenlingMahjongGame | None = None
        self.account_chips: dict[str, int] = {}
        self.room_luck: dict[str, dict[str, float | int]] = {}
        self.room_round_count = 0
        self.revision = 0
        self.room_generation = 1
        self.event_seq = 0
        self.pending_seq = 0
        self.room_events: list[dict[str, Any]] = []
        self.last_slow_events: list[dict[str, Any]] = []
        self.api_timing_buckets: dict[str, dict[str, Any]] = {}
        self.runtime_context = dict(runtime_context or {})
        self.auto_bug_snapshots = bool(auto_bug_snapshots)
        self.low_latency_ai = bool(low_latency_ai)
        self.ticker_interval_sec = max(0.05, float(ticker_interval_sec))
        self._active_room_events: list[dict[str, Any]] = []
        self._room_event_queue: deque[dict[str, Any]] = deque()
        self._room_event_next_id = 0
        self._processing_room_event = False
        self._room_tick_queued = False
        self._closed = False
        self._waiter_count = 0
        self._ai_thinking_count = 0
        self.bug_report_store = BugReportStore(
            Path(log_dir) / "bug_reports",
            export_root=bug_report_export_dir,
        )
        self._last_bug_snapshot_at = 0.0
        self.condition = threading.Condition(self.lock)
        self.last_seen: dict[str, float] = {}
        self.last_rule_issues: list[str] = []
        self._last_online_accounts: set[str] = set()
        self._last_presence_sweep = 0.0
        self._room_worker = threading.Thread(target=self._room_worker_loop, daemon=True, name="battle-room-worker")
        self._room_worker.start()
        self._ticker = threading.Thread(target=self._ticker_loop, daemon=True, name="battle-room-ticker")
        self._ticker.start()

    def close(self) -> None:
        condition = getattr(self, "condition", None)
        if condition is None:
            return
        with condition:
            self._closed = True
            for queued_event in list(getattr(self, "_room_event_queue", [])):
                queued_event["done"] = True
                queued_event["error"] = RuntimeError("battle session is closed")
            self._room_event_queue = deque()
            self._room_tick_queued = False
            condition.notify_all()
        for thread_name in ("_room_worker", "_ticker"):
            thread = getattr(self, thread_name, None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)
        store = getattr(self, "bug_report_store", None)
        if store is not None:
            store.close()

    def close_room(self, reason: str = "closed") -> dict[str, Any]:
        with self.condition:
            self._ensure_runtime_fields_locked()
            self._snapshot_game_chips_locked()
            self.game = None
            self.seats = [None, None, None, None]
            self.ready.clear()
            self.account_chips.clear()
            self._new_room_generation_locked(reason)
            self._bump_revision("room_closed", {"reason": reason})
            self.condition.notify_all()
            return self.serialize_for_account(None)

    def register(self, account: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.ensure_account(account, is_ai=False)
            return {"ok": True, "account": row["account_name"], "db": self.db.info()}

    def register_player(self, account: str) -> dict[str, Any]:
        raise ValueError("public registration requires an invite code and password")

    def record_opening(
        self,
        account_name: str,
        opening_shanten: int,
        de_draws: int,
        fan_flower_draws: int,
    ) -> None:
        self.db.record_opening(account_name, opening_shanten, de_draws, fan_flower_draws)

    def record_win(
        self,
        account_name: str,
        win_type: str,
        win_turn: int | None = None,
        win_points: int | None = None,
    ) -> None:
        self.db.record_win(account_name, win_type, win_turn=win_turn, win_points=win_points)

    def record_hand_luck(self, account_name: str, luck_score: float) -> None:
        self.db.record_hand_luck(account_name, luck_score)
        with self.lock:
            current = self.room_luck.setdefault(
                account_name,
                {"luck_score_total": 0.0, "luck_score_count": 0},
            )
            current["luck_score_total"] = float(current["luck_score_total"]) + float(luck_score)
            current["luck_score_count"] = int(current["luck_score_count"]) + 1

    def login(self, account: str) -> dict[str, Any]:
        with self.lock:
            row = self.db.require_active_human_account(account)
            return {"ok": True, "account": row["account_name"], "db": self.db.info()}

    def sit(
        self,
        account: str,
        seat: int,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "sit",
            "sit",
            lambda _started_at: self._sit_impl(account, seat, room_generation),
            {"account": account, "seat": int(seat)},
        )

    def _sit_impl(
        self,
        account: str,
        seat: int,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            name = self.db.require_active_human_account(account)["account_name"]
            self._touch_account(name)
            seat = int(seat)
            if seat < 0 or seat >= 4:
                raise ValueError("座位必须是 0-3")
            if self.game and self.game.phase != "round_over":
                if self.seats[seat] == name:
                    self._sync_blocking_human_seat()
                    payload = self.serialize_for_account(name)
                    return payload
                raise ValueError("当前小局进行中，结束后才能换座")
            joining_new_human = name not in self.seats
            if joining_new_human and self.game is not None and self.game.phase == "round_over":
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self._new_room_generation_locked("new_human_after_round")
            elif joining_new_human and self._human_accounts():
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self._new_room_generation_locked("new_human_join")
            for idx, current in enumerate(self.seats):
                if current == name:
                    self.seats[idx] = None
            if self.seats[seat] and self.seats[seat] != name:
                raise ValueError("这个位置已经有人坐下")
            self.seats[seat] = name
            self.ready.discard(name)
            self._bump_revision("sit", {"account": name, "seat": seat})
            payload = self.serialize_for_account(name)
            return payload

    def leave(
        self,
        account: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "leave",
            "leave",
            lambda _started_at: self._leave_impl(account, room_generation),
            {"account": account},
        )

    def _leave_impl(
        self,
        account: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            name = self.db.normalize_account(account)
            self._touch_account(name)
            active_round = self.game is not None and self.game.phase != "round_over"
            if active_round and name in self.seats:
                self.ready.discard(name)
                self.last_seen.pop(name, None)
                self._sync_blocking_human_seat()
                self._bump_revision("leave_active_reserved", {"account": name})
                payload = self.serialize_for_account(name)
                return payload
            self.seats = [None if item == name else item for item in self.seats]
            self.ready.discard(name)
            self.last_seen.pop(name, None)
            if not self._human_accounts():
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self.account_chips.clear()
                self._new_room_generation_locked("last_human_left")
            elif self.game is not None:
                self._sync_blocking_human_seat()
            self._bump_revision("leave", {"account": name})
            payload = self.serialize_for_account(name)
            return payload

    def kick(
        self,
        requester: str,
        target: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "kick",
            "kick",
            lambda _started_at: self._kick_impl(requester, target, room_generation),
            {"requester": requester, "target": target},
        )

    def _kick_impl(
        self,
        requester: str,
        target: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            requester_name = self.db.normalize_account(requester)
            target_name = self.db.normalize_account(target)
            self._touch_account(requester_name)
            if not requester_name or requester_name not in self.seats:
                raise ValueError("只有房间内玩家可以踢人")
            if not target_name or target_name not in self.seats or target_name in AI_ACCOUNTS:
                raise ValueError("只能踢出房间内的人类玩家")
            seat = self.seats.index(target_name)
            if self.game is not None and self.game.phase != "round_over":
                self.ready.discard(target_name)
                self.last_seen.pop(target_name, None)
                self._sync_blocking_human_seat()
                self._bump_revision(
                    "kick_active_reserved",
                    {"requester": requester_name, "target": target_name, "seat": seat},
                )
                return self.serialize_for_account(requester_name)
            self._snapshot_game_chips_locked()
            self.seats[seat] = None
            self.ready.discard(target_name)
            self.last_seen.pop(target_name, None)
            if self.game is not None and self.game.phase == "round_over":
                self.game = None
            if not self._human_accounts():
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self.account_chips.clear()
                self._new_room_generation_locked("last_human_kicked")
            self._bump_revision("kick", {"requester": requester_name, "target": target_name, "seat": seat})
            payload = self.serialize_for_account(requester_name)
            return payload

    def set_ai_policy(self, policy: str) -> None:
        self.ai_policy = self._normalize_ai_policy(policy)

    def _apply_ready_ai_policy_locked(self, policy: str | None) -> None:
        if policy is None:
            self.set_ai_policy(getattr(self, "ai_policy", DEFAULT_AI_POLICY))
            return
        normalized = self._normalize_ai_policy(policy)
        current = self._active_ai_policy_locked()
        if current == AI_POLICY_HIGH and normalized == AI_POLICY_LOW:
            return
        self.ai_policy = normalized

    def _normalize_ai_policy(self, policy: str | None) -> str:
        key = str(policy or "").strip().lower()
        if not key:
            key = str(getattr(self, "ai_policy", "") or DEFAULT_AI_POLICY).strip().lower()
        normalized = AI_POLICY_ALIASES.get(key)
        if normalized is None:
            raise ValueError("AI 等级必须是 low 或 high")
        return normalized

    def _active_ai_policy_locked(self) -> str:
        self._ensure_runtime_fields_locked()
        return self._normalize_ai_policy(getattr(self, "ai_policy", DEFAULT_AI_POLICY))

    def _ai_policy_payload_locked(self) -> dict[str, Any]:
        active = self._active_ai_policy_locked()
        return {
            "current": active,
            "available": [
                {"value": policy, "label": AI_POLICY_LABELS[policy]}
                for policy in AVAILABLE_AI_POLICIES
            ],
            "timeout_sec": AI_POLICY_TIMEOUTS[active],
        }

    def _ai_policy_uses_tile_efficiency(self, policy: str) -> bool:
        return policy == AI_POLICY_HIGH

    def _make_analysis_model_locked(self, policy: str) -> Any:
        return self.analysis_model_factory() if self._ai_policy_uses_tile_efficiency(policy) else LowLatencyPolicyModel()

    def _make_ai_model_locked(self, policy: str) -> Any:
        return self.model_factory("tile_efficiency") if self._ai_policy_uses_tile_efficiency(policy) else LowLatencyPolicyModel()

    def admin_set_seat(
        self,
        account: str,
        seat: int,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "admin_set_seat",
            "admin_set_seat",
            lambda _started_at: self._admin_set_seat_impl(account, seat, room_generation),
            {"account": account, "seat": int(seat)},
        )

    def _admin_set_seat_impl(
        self,
        account: str,
        seat: int,
        room_generation: int | str | None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            if self.game is not None and self.game.phase != "round_over":
                raise ValueError("当前小局进行中，结束后才能调整座位")
            name = str(self.db.require_active_human_account(account)["account_name"])
            destination = int(seat)
            if not 0 <= destination < 4:
                raise ValueError("座位必须是 0-3")
            source = self._seat_for(name)
            displaced = self.seats[destination]
            if source == destination:
                return self.serialize_for_account(None)
            if source is not None:
                self.seats[source] = displaced
            self.seats[destination] = name
            self.ready.discard(name)
            if displaced:
                self.ready.discard(displaced)
            if self.game is not None:
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self._new_room_generation_locked("admin_set_seat")
            self._bump_revision(
                "admin_set_seat",
                {"account": name, "seat": destination, "displaced": displaced},
            )
            return self.serialize_for_account(None)

    def admin_clear_seat(
        self,
        seat: int,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "admin_clear_seat",
            "admin_clear_seat",
            lambda _started_at: self._admin_clear_seat_impl(seat, room_generation),
            {"seat": int(seat)},
        )

    def _admin_clear_seat_impl(
        self,
        seat: int,
        room_generation: int | str | None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            if self.game is not None and self.game.phase != "round_over":
                raise ValueError("当前小局进行中，结束后才能清空座位")
            index = int(seat)
            if not 0 <= index < 4:
                raise ValueError("座位必须是 0-3")
            removed = self.seats[index]
            self.seats[index] = None
            if removed:
                self.ready.discard(removed)
                self.last_seen.pop(removed, None)
            if self.game is not None:
                self._snapshot_game_chips_locked()
                self.game = None
                self.ready.clear()
                self._new_room_generation_locked("admin_clear_seat")
            if not self._human_accounts():
                self.account_chips.clear()
            self._bump_revision("admin_clear_seat", {"seat": index, "account": removed})
            return self.serialize_for_account(None)

    def ready_account(
        self,
        account: str,
        ai_policy: str | None = None,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        return self._run_room_event(
            "ready",
            "ready",
            lambda _started_at: self._ready_account_impl(account, ai_policy, room_generation),
            {"account": account},
        )

    def _ready_account_impl(
        self,
        account: str,
        ai_policy: str | None = None,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            self._apply_ready_ai_policy_locked(ai_policy)
            name = self.db.normalize_account(account)
            self._touch_account(name)
            if name not in self.seats:
                raise ValueError("请先选择一个位置坐下")
            if self.game is not None and self.game.phase != "round_over":
                payload = self.serialize_for_account(name)
                return payload
            if name in self.ready:
                self.ready.remove(name)
                self._bump_revision("ready_cancel", {"account": name})
                payload = self.serialize_for_account(name)
                return payload
            self.ready.add(name)
            if self._all_humans_ready():
                if self.game is None:
                    self._start_game()
                elif self.game.phase == "round_over":
                    self._snapshot_game_chips_locked()
                    self.ready.clear()
                    self.game.new_round()
                    self.room_round_count += 1
            self._bump_revision("ready", {"account": name})
            payload = self.serialize_for_account(name)
            return payload

    def reset_match(
        self,
        account: str | None = None,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        def run(started_at: float) -> dict[str, Any]:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            if account:
                self._touch_account(account)
                if account not in self.seats:
                    raise ValueError("只有已入座玩家才能重新换座")
            if self.game is not None and self.game.phase != "round_over":
                raise ValueError("本局进行中，结算后才能重新换座")
            self._snapshot_game_chips_locked()
            humans = [seat_account for seat_account in self.seats if seat_account and seat_account not in AI_ACCOUNTS]
            if humans:
                positions = list(range(4))
                random.shuffle(positions)
                self.seats = [None, None, None, None]
                for seat_account, seat in zip(humans, positions):
                    self.seats[seat] = seat_account
            self.game = None
            self.ready.clear()
            self._new_room_generation_locked("reset_match")
            self._bump_revision("reset_match", {"account": account})
            payload = self.serialize_for_account(account)
            return payload

        return self._run_room_event(
            "reset",
            "reset",
            run,
            {"account": account},
        )

    def report_bug(
        self,
        account: str,
        *,
        note: str = "",
        client_context: dict[str, Any] | None = None,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        def run(_started_at: float) -> dict[str, Any]:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            name = self.db.normalize_account(account)
            if not name or name not in self.seats:
                raise ValueError("only a seated player can report a battle bug")
            self._touch_account(name)
            if self.game is None:
                raise ValueError("no battle round is available to report")
            self._bump_revision("bug_report_requested", {"account": name})
            snapshot = self._build_bug_snapshot_locked("bug_report_requested")
            self.bug_report_store.update(snapshot, force_persist=True)
            result = self.bug_report_store.create_report(
                reporter_account=name,
                note=note,
                client_context=client_context,
            )
            result["bug_report"] = self.bug_report_store.status()
            return result

        return self._run_room_event(
            "bug_report",
            "bug_report",
            run,
            {"account": account},
        )

    def action(
        self,
        account: str,
        action: dict[str, Any],
        action_token: str | None = None,
        room_generation: int | str | None = None,
        pending_id: str | None = None,
    ) -> dict[str, Any]:
        def run(started_at: float) -> dict[str, Any]:
            self._ensure_runtime_fields_locked()
            self._touch_account(account)
            game = self._require_game()
            seat = self._seat_for(account)
            if seat is None:
                raise ValueError("请先入座")
            expected_token = self._action_token_for(seat)
            current_pending_id = self._current_pending_id_locked(create=False)
            if not action_token:
                raise ValueError("动作已过期，请刷新当前牌局状态后重试")
            if room_generation is None:
                raise ValueError("动作缺少房间 generation，请刷新当前牌局状态后重试")
            if int(room_generation) != int(self.room_generation):
                raise ValueError("房间状态已更新，请刷新当前牌局状态后重试")
            if str(pending_id or "") != str(current_pending_id or ""):
                raise ValueError("响应状态已更新，请按当前画面重新选择动作")
            if str(action_token) != expected_token:
                raise ValueError("牌局状态已更新，请按当前画面重新选择动作")
            game.apply_human_action_for_seat(seat, action)
            if game.phase == "round_over":
                self.ready.clear()
                self._snapshot_game_chips_locked()
            self._validate_game_locked()
            self._bump_revision("player_action", {"account": account, "seat": seat, "action": action.get("type")})
            payload = self.serialize_for_account(account)
            return payload

        return self._run_room_event(
            "player_action",
            "action",
            run,
            {"account": account, "action": action.get("type") if isinstance(action, dict) else None},
        )

    def step(self, account: str | None = None) -> dict[str, Any]:
        def run(_started_at: float) -> dict[str, Any]:
            if account:
                self._touch_account(account)
            if self.game is None:
                return self.serialize_for_account(account)
            self._step_locked()
            return self.serialize_for_account(account)

        return self._run_room_event(
            "manual_step",
            "step",
            run,
            {"account": account},
        )

    def wait_state(self, account: str | None = None, since: int | None = None, timeout: float = 15.0) -> dict[str, Any]:
        started_at = time.time()
        deadline = time.time() + max(0.1, min(float(timeout or 15.0), 30.0))
        waited_ms = 0.0
        timed_out = False
        with self.condition:
            self._ensure_runtime_fields_locked()
            self._waiter_count += 1
            wait_started_at = time.time()
            try:
                while since is not None and self.revision <= int(since):
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        timed_out = True
                        break
                    self.condition.wait(timeout=remaining)
            finally:
                waited_ms = (time.time() - wait_started_at) * 1000.0
                self._waiter_count = max(0, self._waiter_count - 1)
            payload = self.serialize_for_account(account)
            self._record_api_timing_locked(
                "wait",
                started_at,
                {
                    "waited_ms": round(waited_ms, 1),
                    "timed_out": timed_out,
                    "since": since,
                },
                excluded_elapsed_ms=waited_ms,
            )
            return payload

    def serialize_for_account(self, account: str | None = None) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        name = self.db.normalize_account(account) if account else None
        if self.game is None:
            return self._lobby_state(name)
        seat = self._seat_for(name) if name else None
        self._current_pending_id_locked()
        payload = self.game.serialize(viewer_seat=seat if seat is not None else -1)
        if seat is None:
            payload["legal_actions"] = []
        return self._view_payload(payload, name)

    def state(self, account: str | None = None) -> dict[str, Any]:
        started_at = time.time()
        with self.lock:
            self._ensure_runtime_fields_locked()
            name = self.db.normalize_account(account) if account else None
            payload = self.serialize_for_account(name)
            self._record_api_timing_locked("state", started_at)
            return payload

    def host_status(self) -> dict[str, Any]:
        with self.lock:
            self._ensure_runtime_fields_locked()
            return {
                "room_generation": self.room_generation,
                "room_revision": self.revision,
                "event_seq": self.event_seq,
                "phase": self.game.phase if self.game is not None else None,
                "game_started": self.game is not None,
                "seats": self._seat_payload(),
                "ready_accounts": sorted(self.ready),
            }

    def db_info(self) -> dict[str, Any]:
        return self.db.info()

    def accounts(self) -> dict[str, Any]:
        with self.lock:
            return {"db": self.db.info(), "accounts": self.db.accounts()}

    def reset_stats(self) -> dict[str, Any]:
        with self.lock:
            result = self.db.reset_stats()
            result["db"] = self.db.info()
            return result

    def heartbeat(
        self,
        account: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        started_at = time.time()
        with self.condition:
            self._ensure_runtime_fields_locked()
            self._validate_supplied_room_generation_locked(room_generation)
            name = self.db.normalize_account(account)
            self._touch_account(name)
            payload = {"ok": True, "account": name, "presence": self._presence_payload(name)}
            self._record_api_timing_locked("heartbeat", started_at)
            return payload

    def _start_game(self) -> None:
        self._ensure_runtime_fields_locked()
        self._new_room_generation_locked("start_game")
        accounts = self._effective_accounts()
        policy = self._active_ai_policy_locked()
        low_policy = policy == AI_POLICY_LOW
        analysis = self._make_analysis_model_locked(policy)
        ai_model = self._make_ai_model_locked(policy)
        seat_models = [analysis if account not in AI_ACCOUNTS else ai_model for account in accounts]
        human_seats = {idx for idx, account in enumerate(accounts) if account not in AI_ACCOUNTS}
        defer_responses = bool(human_seats)
        self.game = WenlingMahjongGame(
            model=analysis,
            log_dir=self.log_dir,
            human_seat=self._first_human_seat(),
            human_seats=human_seats,
            training=False,
            seat_models=seat_models,
            persist_logs=not low_policy,
            defer_ai_responses=defer_responses,
            response_delay_sec=BATTLE_ACTION_DELAY_SEC,
            ai_decision_timeout_sec=AI_POLICY_TIMEOUTS[policy],
            stats_recorder=self,
            ai_result_callback=self._submit_ai_result_event if defer_responses else None,
            ai_context_provider=self._ai_result_context_for_game if defer_responses else None,
        )
        for player, account in zip(self.game.players, accounts):
            player.name = account
            player.chips = int(getattr(self, "account_chips", {}).get(account, 0))
        self.ready.clear()
        self.game.new_round()
        self.room_round_count += 1
        self._validate_game_locked()

    def _all_humans_ready(self) -> bool:
        humans = self._human_accounts()
        return bool(humans) and all(account in self.ready for account in humans)

    def _human_accounts(self) -> list[str]:
        return [account for account in self.seats if account and account not in AI_ACCOUNTS]

    def _effective_accounts(self) -> list[str]:
        ai_iter = iter(AI_ACCOUNTS)
        accounts: list[str] = []
        used = set(account for account in self.seats if account)
        for account in self.seats:
            if account:
                accounts.append(account)
                continue
            next_ai = next((ai for ai in ai_iter if ai not in used), None)
            accounts.append(next_ai or "AI1")
        return accounts

    def _seat_effective_accounts(self) -> list[str | None]:
        if self.game is None and not self._human_accounts():
            return list(self.seats)
        return self._effective_accounts()

    def _seat_for(self, account: str | None) -> int | None:
        if not account:
            return None
        for idx, item in enumerate(self.seats):
            if item == account:
                return idx
        if self.game:
            for idx, player in enumerate(self.game.players):
                if player.name == account and account not in AI_ACCOUNTS:
                    return idx
        return None

    def _first_human_seat(self) -> int | None:
        for idx, account in enumerate(self.seats):
            if account and account not in AI_ACCOUNTS:
                return idx
        return None

    def _sync_blocking_human_seat(self) -> None:
        if not self.game:
            return
        human_seats = {idx for idx, account in enumerate(self._effective_accounts()) if account not in AI_ACCOUNTS}
        self.game.set_human_seats(human_seats)
        pending = self.game.pending or {}
        current_responder = pending.get("current_responder")
        if current_responder in human_seats:
            self.game.human_seat = int(current_responder)
        elif self.game.phase == "turn" and self.game.current_player in human_seats:
            self.game.human_seat = self.game.current_player
        elif self.game.human_seat not in human_seats:
            self.game.human_seat = next(iter(human_seats), None)

    def _sync_active_game_accounts_locked(self) -> None:
        if self.game is None:
            return
        effective = self._effective_accounts()
        for seat, account in enumerate(effective):
            if seat >= len(self.game.players):
                continue
            self.game.players[seat].name = account
            if account in AI_ACCOUNTS and 0 <= seat < len(self.game.seat_models):
                self.game.seat_models[seat] = self._make_ai_model_locked(self._active_ai_policy_locked())

    def _ai_result_context_for_game(self, metadata: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        seat = metadata.get("seat")
        pending_id = self._current_pending_id_locked()
        return {
            "room_generation": self.room_generation,
            "pending_id": pending_id,
            "action_token": self._action_token_for(int(seat)) if seat is not None else None,
        }

    def _submit_ai_result_event(self, result: dict[str, Any]) -> None:
        with self.condition:
            self._ensure_runtime_fields_locked()
            self._enqueue_room_event_locked(
                "ai_action_result",
                "ai_action_result",
                lambda _started_at: self._apply_ai_result_event(result),
                {
                    "seat": result.get("seat"),
                    "kind": result.get("kind"),
                    "pending_id": result.get("pending_id"),
                    "room_generation": result.get("room_generation"),
                },
                wait_for_result=False,
            )

    def _apply_ai_result_event(self, result: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        if self.game is None:
            return {"accepted": False, "reason": "no_game"}
        try:
            result_generation = int(result.get("room_generation"))
        except (TypeError, ValueError):
            return {"accepted": False, "reason": "missing_generation"}
        if result_generation != int(self.room_generation):
            return {"accepted": False, "reason": "stale_generation"}
        current_pending_id = self._current_pending_id_locked(create=False)
        if str(result.get("pending_id") or "") != str(current_pending_id or ""):
            return {"accepted": False, "reason": "stale_pending"}
        try:
            seat = int(result.get("seat"))
        except (TypeError, ValueError):
            return {"accepted": False, "reason": "missing_seat"}
        expected_token = self._action_token_for(seat)
        if str(result.get("action_token") or "") != str(expected_token or ""):
            return {"accepted": False, "reason": "stale_action_token"}

        before_signature = self._game_signature()
        if hasattr(self.game, "_queue_ai_result_local"):
            self.game._queue_ai_result_local(result)
        else:
            self.game._queue_ai_result(result)
        self.game.resolve_deferred_pending(force=False)
        if self.game.phase == "round_over":
            self.ready.clear()
            self._snapshot_game_chips_locked()
        self._validate_game_locked()
        if self._game_signature() != before_signature:
            self._bump_revision("ai_action_result", {"seat": seat, "kind": result.get("kind")})
        return {"accepted": True}

    def _require_game(self) -> WenlingMahjongGame:
        if self.game is None:
            raise ValueError("所有人类玩家准备后才会开始游戏")
        return self.game

    def _lobby_state(self, account: str | None) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        return {
            "app": "battle",
            "account": account,
            "game_started": False,
            "phase": "lobby",
            "room_revision": self.revision,
            "room_generation": self.room_generation,
            "event_seq": self.event_seq,
            "pending_id": None,
            "room_round_count": self.room_round_count,
            "runtime": self._runtime_payload_locked(pending_id=None),
            "seats": self._seat_payload(),
            "ready_accounts": sorted(self.ready),
            "all_humans_ready": self._all_humans_ready(),
            "ai_policy": self._active_ai_policy_locked(),
            "available_ai_policies": list(AVAILABLE_AI_POLICIES),
            "ai_policy_info": self._ai_policy_payload_locked(),
            "player_stats": self._stats_payload(),
            "bug_report": self.bug_report_store.status(),
            "db": self.db.info(),
            "network": {
                "reserved": True,
                "endpoints": [
                    "/api/battle/login",
                    "/api/battle/heartbeat",
                    "/api/battle/sit",
                    "/api/battle/ready",
                    "/api/battle/action",
                ],
            },
        }

    def _decorate_state(self, payload: dict[str, Any], account: str | None) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        viewer = self._seat_for(account) if account and self.game is not None else None
        now = time.time()
        pending_id = self._current_pending_id_locked()
        payload["app"] = "battle"
        payload["account"] = account
        payload["game_started"] = self.game is not None
        if viewer is not None:
            payload["viewer_absolute_seat"] = viewer
            payload["action_token"] = self._action_token_for(viewer)
        payload["room_revision"] = self.revision
        payload["room_generation"] = self.room_generation
        payload["event_seq"] = self.event_seq
        payload["pending_id"] = pending_id
        payload["room_round_count"] = int(getattr(self, "room_round_count", 0) or 0)
        payload["runtime"] = self._runtime_payload_locked(pending_id=pending_id)
        payload["seats"] = self._seat_payload(viewer)
        effective = self._seat_effective_accounts()
        for player in payload.get("players", []):
            absolute = player.get("absolute_seat", player.get("seat"))
            try:
                absolute_index = int(absolute)
            except (TypeError, ValueError):
                continue
            if not 0 <= absolute_index < len(effective):
                continue
            player_account = effective[absolute_index]
            player["account"] = player_account
            if player_account in AI_ACCOUNTS:
                player["online"] = True
                player["last_seen_age_sec"] = 0.0
            else:
                presence = self._presence_payload(player_account, now)
                player["online"] = presence["online"]
                player["last_seen_age_sec"] = presence["last_seen_age_sec"]
        payload["ready_accounts"] = sorted(self.ready)
        payload["ai_policy"] = self._active_ai_policy_locked()
        payload["available_ai_policies"] = list(AVAILABLE_AI_POLICIES)
        payload["ai_policy_info"] = self._ai_policy_payload_locked()
        payload["rule_issues"] = list(getattr(self, "last_rule_issues", []))
        payload["player_stats"] = self._stats_payload()
        payload["bug_report"] = self.bug_report_store.status()
        payload["db"] = self.db.info()
        payload["network"] = {
            "reserved": True,
            "transport": "HTTP long-poll plus heartbeat",
            "endpoints": [
                "/api/battle/wait",
                "/api/battle/heartbeat",
                "/api/battle/action",
            ],
        }
        return payload

    def _ensure_runtime_fields_locked(self) -> None:
        if not hasattr(self, "room_luck"):
            self.room_luck = {}
        if not hasattr(self, "room_round_count"):
            self.room_round_count = int(getattr(self.game, "round_no", 0) or 0) if self.game is not None else 0
        if not hasattr(self, "room_generation"):
            self.room_generation = 1
        if not hasattr(self, "event_seq"):
            self.event_seq = 0
        if not hasattr(self, "pending_seq"):
            self.pending_seq = 0
        if not hasattr(self, "room_events"):
            self.room_events = []
        if not hasattr(self, "last_slow_events"):
            self.last_slow_events = []
        if not hasattr(self, "api_timing_buckets"):
            self.api_timing_buckets = {}
        if not hasattr(self, "ai_policy"):
            self.ai_policy = DEFAULT_AI_POLICY
        self.ai_policy = self._normalize_ai_policy(self.ai_policy)
        if not hasattr(self, "runtime_context"):
            self.runtime_context = {}
        if not hasattr(self, "auto_bug_snapshots"):
            self.auto_bug_snapshots = True
        if not hasattr(self, "low_latency_ai"):
            self.low_latency_ai = False
        if not hasattr(self, "ticker_interval_sec"):
            self.ticker_interval_sec = 0.05
        if not hasattr(self, "_active_room_events"):
            self._active_room_events = []
        if not hasattr(self, "_room_event_queue"):
            self._room_event_queue = deque()
        if not hasattr(self, "_room_event_next_id"):
            self._room_event_next_id = 0
        if not hasattr(self, "_processing_room_event"):
            self._processing_room_event = False
        if not hasattr(self, "_room_tick_queued"):
            self._room_tick_queued = False
        if not hasattr(self, "_closed"):
            self._closed = False
        if not hasattr(self, "_waiter_count"):
            self._waiter_count = 0
        if not hasattr(self, "_ai_thinking_count"):
            self._ai_thinking_count = 0
        if not hasattr(self, "account_chips"):
            self.account_chips = {}
        if not hasattr(self, "bug_report_store"):
            self.bug_report_store = BugReportStore(Path(self.log_dir) / "bug_reports")
        if not hasattr(self, "_last_bug_snapshot_at"):
            self._last_bug_snapshot_at = 0.0
        if not getattr(self, "_synchronous_room_events", False):
            self._ensure_room_worker_locked()

    def _ensure_room_worker_locked(self) -> None:
        if getattr(self, "_closed", False):
            return
        worker = getattr(self, "_room_worker", None)
        if worker is not None and worker.is_alive():
            return
        self._room_worker = threading.Thread(target=self._room_worker_loop, daemon=True, name="battle-room-worker")
        self._room_worker.start()

    def _new_room_generation_locked(self, reason: str) -> None:
        self._ensure_runtime_fields_locked()
        self.room_generation += 1
        self.pending_seq = 0
        if self.game is not None:
            if hasattr(self.game, "cancel_async_ai_jobs"):
                self.game.cancel_async_ai_jobs()
            if getattr(self.game, "pending", None):
                self.game.pending = None
        self._append_room_event_locked("room_generation", {"reason": reason})

    def _append_room_event_locked(self, event_type: str, details: dict[str, Any] | None = None) -> None:
        self._ensure_runtime_fields_locked()
        event = {
            "event_seq": self.event_seq,
            "event_type": event_type,
            "room_generation": self.room_generation,
            "pending_id": self._current_pending_id_locked(create=False),
            "ts": round(time.time(), 3),
        }
        active = self._active_room_events[-1] if self._active_room_events else None
        if active:
            event["source_event_type"] = active.get("event_type")
            event["source_queue_id"] = active.get("queue_id")
            event["source_started_at"] = active.get("started_at")
            event["source_elapsed_ms"] = round((time.time() - float(active.get("started_at_raw", time.time()))) * 1000.0, 1)
        if details:
            event["details"] = details
        self.room_events.append(event)
        del self.room_events[:-RUNTIME_EVENT_LOG_LIMIT]

    def _run_room_event(
        self,
        event_type: str,
        api: str,
        handler: Any,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started_at = time.time()
        if getattr(self, "_synchronous_room_events", False):
            with self.condition:
                self._ensure_runtime_fields_locked()
                self._room_event_next_id += 1
                active = {
                    "event_type": event_type,
                    "queue_id": self._room_event_next_id,
                    "started_at_raw": started_at,
                    "started_at": round(started_at, 3),
                    "details": dict(details or {}),
                }
                self._processing_room_event = True
                self._active_room_events.append(active)
                handler_started_at = time.time()
                try:
                    with self.lock:
                        result = handler(started_at)
                    return result
                finally:
                    self._record_api_timing_locked(
                        str(api),
                        started_at,
                        {
                            "event_type": event_type,
                            "queue_wait_ms": round((handler_started_at - started_at) * 1000.0, 1),
                            **dict(details or {}),
                        },
                        queue_wait_ms=(handler_started_at - started_at) * 1000.0,
                    )
                    if self._active_room_events and self._active_room_events[-1] is active:
                        self._active_room_events.pop()
                    elif active in self._active_room_events:
                        self._active_room_events.remove(active)
                    self._processing_room_event = False
                    self.condition.notify_all()
        with self.condition:
            if getattr(self, "_closed", False):
                raise RuntimeError("battle session is closed")
            queued_event = self._enqueue_room_event_locked(
                event_type,
                api,
                handler,
                details,
                started_at=started_at,
                wait_for_result=True,
            )
            while True:
                if queued_event["done"]:
                    error = queued_event.get("error")
                    if error is not None:
                        raise error
                    return queued_event["result"]
                self.condition.wait(timeout=0.1)

    def _enqueue_room_event_locked(
        self,
        event_type: str,
        api: str,
        handler: Any,
        details: dict[str, Any] | None = None,
        *,
        started_at: float | None = None,
        wait_for_result: bool = False,
        coalesce_key: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        event_started_at = time.time() if started_at is None else float(started_at)
        self._room_event_next_id += 1
        queued_event = {
            "queue_id": self._room_event_next_id,
            "event_type": event_type,
            "api": api,
            "handler": handler,
            "details": dict(details or {}),
            "started_at_raw": event_started_at,
            "started_at": round(event_started_at, 3),
            "wait_for_result": bool(wait_for_result),
            "coalesce_key": coalesce_key,
            "done": False,
            "result": None,
            "error": None,
        }
        self._room_event_queue.append(queued_event)
        self.condition.notify_all()
        return queued_event

    def _room_worker_loop(self) -> None:
        while True:
            with self.condition:
                while not self._room_event_queue:
                    if getattr(self, "_closed", False):
                        return
                    self.condition.wait()
                if getattr(self, "_closed", False):
                    return
                queued_event = self._room_event_queue[0]
                self._processing_room_event = True
                active = {
                    "event_type": queued_event["event_type"],
                    "queue_id": queued_event["queue_id"],
                    "started_at_raw": queued_event["started_at_raw"],
                    "started_at": queued_event["started_at"],
                    "details": dict(queued_event.get("details") or {}),
                }
                self._active_room_events.append(active)
            error: BaseException | None = None
            result: Any = None
            handler_started_at = time.time()
            queue_wait_ms = max(
                0.0,
                (handler_started_at - float(queued_event["started_at_raw"])) * 1000.0,
            )
            try:
                with self.lock:
                    result = queued_event["handler"](queued_event["started_at_raw"])
            except BaseException as exc:  # propagate to the event owner after releasing active context
                error = exc
            with self.condition:
                queued_event["result"] = result
                queued_event["error"] = error
                self._record_api_timing_locked(
                    str(queued_event["api"]),
                    float(queued_event["started_at_raw"]),
                    {
                        "event_type": queued_event["event_type"],
                        "queue_wait_ms": round(queue_wait_ms, 1),
                        **dict(queued_event.get("details") or {}),
                    },
                    queue_wait_ms=queue_wait_ms,
                )
                if self._active_room_events and self._active_room_events[-1] is active:
                    self._active_room_events.pop()
                elif active in self._active_room_events:
                    self._active_room_events.remove(active)
                if self._room_event_queue and self._room_event_queue[0] is queued_event:
                    self._room_event_queue.popleft()
                elif queued_event in self._room_event_queue:
                    self._room_event_queue.remove(queued_event)
                if queued_event.get("coalesce_key") == "tick":
                    self._room_tick_queued = False
                queued_event["done"] = True
                self._processing_room_event = False
                self.condition.notify_all()

    def _runtime_payload_locked(self, pending_id: str | None = None) -> dict[str, Any]:
        self._ensure_runtime_fields_locked()
        current_pending_id = pending_id if pending_id is not None else self._current_pending_id_locked(create=False)
        ai_thinking_count = self._ai_thinking_count_locked()
        model_backends: list[str] = []
        if self.game is not None:
            model_backends = [
                str(getattr(model, "backend", type(model).__name__))
                for model in getattr(self.game, "seat_models", [])
            ]
        policy = self._active_ai_policy_locked()
        return {
            "room_generation": self.room_generation,
            "event_seq": self.event_seq,
            "pending_id": current_pending_id,
            "waiter_count": self._waiter_count,
            "ai_thinking_count": ai_thinking_count,
            "ai_policy": policy,
            "ai_policy_label": AI_POLICY_LABELS[policy],
            "ai_decision_timeout_sec": AI_POLICY_TIMEOUTS[policy],
            "low_latency_ai": policy == AI_POLICY_LOW,
            "ticker_interval_sec": float(getattr(self, "ticker_interval_sec", 0.05)),
            "model_backends": model_backends,
            "room_event_queue_length": len(self._room_event_queue),
            "processing_room_event": bool(self._processing_room_event),
            "api_timing_buckets": {
                api: {
                    key: (dict(value) if isinstance(value, dict) else value)
                    for key, value in timing.items()
                }
                for api, timing in self.api_timing_buckets.items()
            },
            "last_events": list(self.room_events[-10:]),
            "last_slow_events": list(self.last_slow_events[-10:]),
        }

    def _ai_thinking_count_locked(self) -> int:
        if self.game is None:
            return 0
        pending = getattr(self.game, "pending", None)
        if not isinstance(pending, dict) or not pending:
            return 0
        count = 1 if pending.get("ai_thinking") else 0
        count += sum(1 for value in (pending.get("ai_thinking_by_seat") or {}).values() if value)
        return count

    def _record_api_timing_locked(
        self,
        api: str,
        started_at: float,
        extra: dict[str, Any] | None = None,
        *,
        excluded_elapsed_ms: float = 0.0,
        queue_wait_ms: float = 0.0,
    ) -> None:
        self._ensure_runtime_fields_locked()
        elapsed_ms = (time.time() - started_at) * 1000.0
        queue_wait_ms = max(0.0, float(queue_wait_ms))
        processing_ms = max(
            0.0,
            elapsed_ms - max(0.0, float(excluded_elapsed_ms)) - queue_wait_ms,
        )
        self._record_api_bucket_locked(api, elapsed_ms, processing_ms, queue_wait_ms)
        if processing_ms < SLOW_API_THRESHOLD_MS and queue_wait_ms < SLOW_API_THRESHOLD_MS:
            return
        event = {
            "api": api,
            "elapsed_ms": round(elapsed_ms, 1),
            "processing_ms": round(processing_ms, 1),
            "queue_wait_ms": round(queue_wait_ms, 1),
            "room_generation": self.room_generation,
            "event_seq": self.event_seq,
            "pending_id": self._current_pending_id_locked(create=False),
            "waiter_count": self._waiter_count,
            "ai_thinking_count": self._ai_thinking_count_locked(),
            "ts": round(time.time(), 3),
        }
        if extra:
            event["details"] = extra
        self.last_slow_events.append(event)
        del self.last_slow_events[:-RUNTIME_EVENT_LOG_LIMIT]

    def _record_api_bucket_locked(
        self,
        api: str,
        elapsed_ms: float,
        processing_ms: float,
        queue_wait_ms: float = 0.0,
    ) -> None:
        timing = self.api_timing_buckets.setdefault(
            str(api),
            {
                "count": 0,
                "last_elapsed_ms": 0.0,
                "last_processing_ms": 0.0,
                "last_queue_wait_ms": 0.0,
                "total_elapsed_ms": 0.0,
                "total_processing_ms": 0.0,
                "total_queue_wait_ms": 0.0,
                "max_elapsed_ms": 0.0,
                "max_processing_ms": 0.0,
                "max_queue_wait_ms": 0.0,
                "processing_buckets": {
                    "lt_50_ms": 0,
                    "50_to_199_ms": 0,
                    "200_to_999_ms": 0,
                    "gte_1000_ms": 0,
                },
            },
        )
        timing["count"] = int(timing.get("count", 0)) + 1
        elapsed_ms = max(0.0, float(elapsed_ms))
        processing_ms = max(0.0, float(processing_ms))
        queue_wait_ms = max(0.0, float(queue_wait_ms))
        timing["last_elapsed_ms"] = round(elapsed_ms, 1)
        timing["last_processing_ms"] = round(processing_ms, 1)
        timing["last_queue_wait_ms"] = round(queue_wait_ms, 1)
        timing["total_elapsed_ms"] = round(float(timing.get("total_elapsed_ms", 0.0)) + elapsed_ms, 1)
        timing["total_processing_ms"] = round(float(timing.get("total_processing_ms", 0.0)) + processing_ms, 1)
        timing["total_queue_wait_ms"] = round(float(timing.get("total_queue_wait_ms", 0.0)) + queue_wait_ms, 1)
        timing["max_elapsed_ms"] = round(
            max(float(timing.get("max_elapsed_ms", 0.0)), elapsed_ms),
            1,
        )
        timing["max_processing_ms"] = round(
            max(float(timing.get("max_processing_ms", 0.0)), processing_ms),
            1,
        )
        timing["max_queue_wait_ms"] = round(
            max(float(timing.get("max_queue_wait_ms", 0.0)), queue_wait_ms),
            1,
        )
        buckets = timing["processing_buckets"]
        if processing_ms < 50.0:
            bucket = "lt_50_ms"
        elif processing_ms < 200.0:
            bucket = "50_to_199_ms"
        elif processing_ms < 1000.0:
            bucket = "200_to_999_ms"
        else:
            bucket = "gte_1000_ms"
        buckets[bucket] = int(buckets.get(bucket, 0)) + 1

    def _current_pending_id_locked(self, *, create: bool = True) -> str | None:
        self._ensure_runtime_fields_locked()
        if self.game is None:
            return None
        pending = getattr(self.game, "pending", None)
        if not isinstance(pending, dict) or not pending:
            return None
        pending["room_generation"] = int(self.room_generation)
        pending_id = pending.get("pending_id")
        if pending_id:
            return str(pending_id)
        if not create:
            return None
        self.pending_seq += 1
        pending_id = f"p{self.room_generation}-{self.pending_seq}"
        pending["pending_id"] = pending_id
        return pending_id

    def _validate_supplied_room_generation_locked(
        self,
        room_generation: int | str | None,
    ) -> None:
        if room_generation is None:
            return
        try:
            supplied = int(room_generation)
        except (TypeError, ValueError) as exc:
            raise ValueError("room_generation must be an integer") from exc
        if supplied != int(self.room_generation):
            raise ValueError("stale room_generation; refresh battle state and retry")

    def _bump_revision(self, event_type: str = "state_change", details: dict[str, Any] | None = None) -> None:
        self._ensure_runtime_fields_locked()
        self.revision += 1
        self.event_seq += 1
        self._append_room_event_locked(event_type, details)
        self._cache_latest_round_locked(event_type)
        condition = getattr(self, "condition", None)
        if condition is not None:
            condition.notify_all()

    def _cache_latest_round_locked(self, reason: str, *, force: bool = False) -> None:
        if self.game is None:
            return
        if not getattr(self, "auto_bug_snapshots", True):
            return
        now = time.monotonic()
        force = force or self.game.phase == "round_over"
        if (
            not force
            and self.bug_report_store.status().get("available")
            and now - self._last_bug_snapshot_at < BUG_SNAPSHOT_INTERVAL_SEC
        ):
            return
        try:
            self.bug_report_store.update(
                self._build_bug_snapshot_locked(reason),
                force_persist=force,
            )
            self._last_bug_snapshot_at = now
        except Exception:
            return

    def _build_bug_snapshot_locked(self, reason: str) -> dict[str, Any]:
        game = self.game
        if game is None:
            raise ValueError("no active game")
        physical_counts = Counter(build_wall())
        queued_events = [
            {
                "queue_id": item.get("queue_id"),
                "event_type": item.get("event_type"),
                "api": item.get("api"),
                "details": json_safe(item.get("details") or {}),
                "started_at": item.get("started_at"),
                "age_ms": round((time.time() - float(item.get("started_at_raw") or time.time())) * 1000.0, 1),
                "done": bool(item.get("done")),
                "error": repr(item.get("error")) if item.get("error") else None,
            }
            for item in self._room_event_queue
        ]
        players = [
            {
                "seat": seat,
                "name": player.name,
                "hand": dict(player.hand),
                "flowers": list(player.flowers),
                "melds": json_safe(player.melds),
                "discards": list(player.discards),
                "chips": int(player.chips),
            }
            for seat, player in enumerate(game.players)
        ]
        return {
            "schema_version": BUG_REPORT_SCHEMA_VERSION,
            "captured_at": time.time(),
            "capture_reason": reason,
            "room": {
                "room_generation": self.room_generation,
                "room_revision": self.revision,
                "event_seq": self.event_seq,
                "pending_id": self._current_pending_id_locked(create=False),
                "seats": list(self.seats),
                "effective_accounts": self._effective_accounts(),
                "ready_accounts": sorted(self.ready),
                "account_chips": dict(self.account_chips),
                "last_seen": dict(self.last_seen),
                "room_events": list(self.room_events),
                "active_room_events": [
                    {
                        "event_type": item.get("event_type"),
                        "queue_id": item.get("queue_id"),
                        "started_at": item.get("started_at"),
                        "age_ms": round((time.time() - float(item.get("started_at_raw") or time.time())) * 1000.0, 1),
                        "details": json_safe(item.get("details") or {}),
                    }
                    for item in self._active_room_events
                ],
                "queued_room_events": queued_events,
                "runtime": self._runtime_payload_locked(),
            },
            "game": {
                "round_no": game.round_no,
                "phase": game.phase,
                "dealer": game.dealer,
                "next_dealer": game.next_dealer,
                "current_player": game.current_player,
                "winner": game.winner,
                "win_type": game.win_type,
                "de_indicator": game.de_indicator,
                "de_set": sorted(game.de_set),
                "flower_set": sorted(game.flower_set),
                "wall": list(game.wall),
                "initial_wall": list(getattr(game, "initial_wall", [])),
                "initial_dealt_hands": json_safe(getattr(game, "initial_dealt_hands", [])),
                "opening_hands": json_safe(getattr(game, "opening_hands", [])),
                "last_draw": dict(game.last_draw),
                "pending_self_win_type": dict(game.pending_self_win_type),
                "supplement_count": game.supplement_count,
                "bao_phase": game.bao_phase,
                "bao_phase_wall_threshold": game.bao_phase_wall_threshold,
                "draw_wall_threshold": game.draw_wall_threshold,
                "discarded_tile_kinds": sorted(game.discarded_tile_kinds),
                "pending": json_safe(game.pending),
                "players": players,
                "history": json_safe(game.history),
                "discard_events": json_safe(game.discard_events),
                "bao_liabilities": [
                    game._serialize_bao_liability(item)
                    for item in game.bao_liabilities
                ],
                "claim_warnings": json_safe(game.claim_warnings),
                "temporary_bao": {
                    "seat": game.temporary_bao_seat,
                    "reason": game.temporary_bao_reason,
                    "source_event_id": game.temporary_bao_started_event_id,
                },
                "decisions": json_safe(game.decisions),
                "human_analysis": json_safe(game.human_analysis),
                "settlement": json_safe(game.settlement),
                "random_state": json_safe(game.random.getstate()),
                "serialized_views": {
                    "spectator": game.serialize(viewer_seat=-1),
                    **{
                        f"seat_{seat}": game.serialize(viewer_seat=seat)
                        for seat in range(4)
                    },
                },
            },
            "diagnostics": {
                "runtime_context": json_safe(self.runtime_context),
                "process": self._process_diagnostics_locked(),
                "bug_report_paths": {
                    "latest_path": str(self.bug_report_store.latest_path),
                    "export_latest_path": str(self.bug_report_store.export_latest_path) if self.bug_report_store.export_latest_path else None,
                },
                "rule_issues": validate_game_state(game),
                "physical_tile_counts": dict(physical_counts),
                "indicator_consumed": game.de_indicator,
                "last_slow_events": list(self.last_slow_events),
                "api_timing_buckets": json_safe(self.api_timing_buckets),
            },
        }

    def _process_diagnostics_locked(self) -> dict[str, Any]:
        threads = threading.enumerate()
        return {
            "pid": os.getpid(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "process_time_sec": round(time.process_time(), 3),
            "monotonic_sec": round(time.monotonic(), 3),
            "thread_count": len(threads),
            "threads": [
                {
                    "name": thread.name,
                    "daemon": thread.daemon,
                    "alive": thread.is_alive(),
                }
                for thread in threads
            ],
            "gc_count": list(gc.get_count()),
        }

    def _touch_account(self, account: str | None) -> None:
        name = self.db.normalize_account(account) if account else ""
        if not name:
            return
        now = time.time()
        was_online = name in self._online_accounts(now)
        self.last_seen[name] = now
        if not was_online:
            self._last_online_accounts = self._online_accounts(now)
            self._bump_revision()

    def _online_accounts(self, now: float | None = None) -> set[str]:
        now = time.time() if now is None else now
        return {
            account
            for account, seen_at in getattr(self, "last_seen", {}).items()
            if now - seen_at <= PRESENCE_ONLINE_SEC
        }

    def _presence_payload(self, account: str | None, now: float | None = None) -> dict[str, Any]:
        name = self.db.normalize_account(account) if account else ""
        now = time.time() if now is None else now
        seen_at = getattr(self, "last_seen", {}).get(name)
        age = None if seen_at is None else max(0.0, now - seen_at)
        return {
            "online": bool(name and seen_at is not None and age is not None and age <= PRESENCE_ONLINE_SEC),
            "last_seen_age_sec": None if age is None else round(age, 1),
            "online_timeout_sec": PRESENCE_ONLINE_SEC,
        }

    def _sweep_presence_locked(self) -> None:
        now = time.time()
        if now - getattr(self, "_last_presence_sweep", 0.0) < PRESENCE_SWEEP_SEC:
            return
        self._last_presence_sweep = now
        online = self._online_accounts(now)
        if online != getattr(self, "_last_online_accounts", set()):
            self._last_online_accounts = online
            self._bump_revision()

    def _ticker_loop(self) -> None:
        while True:
            time.sleep(max(0.05, float(getattr(self, "ticker_interval_sec", 0.05))))
            try:
                with self.condition:
                    if getattr(self, "_closed", False):
                        return
                    presence_due = (
                        time.time() - getattr(self, "_last_presence_sweep", 0.0)
                        >= PRESENCE_SWEEP_SEC
                    )
                    if (self.game is not None or presence_due) and not self._room_tick_queued:
                        self._room_tick_queued = True
                        self._enqueue_room_event_locked(
                            "tick",
                            "tick",
                            lambda _started_at: self._tick_impl(),
                            {"source": "ticker"},
                            wait_for_result=False,
                            coalesce_key="tick",
                        )
            except Exception:
                continue

    def _tick_impl(self) -> dict[str, Any]:
        with self.lock:
            self._sweep_presence_locked()
            self._step_locked()
            return {"ok": True}

    def _step_locked(self) -> None:
        if self.game is None:
            return
        self._sync_blocking_human_seat()
        before_signature = self._game_signature()
        before_phase = self.game.phase
        if self.game.phase != "round_over":
            self.game.resolve_deferred_pending(force=False)
            if not self.game.pending:
                if not self.game.prepare_deferred_ai_turn():
                    self.game.advance_until_human(max_steps=1, draw_on_limit=False)
        if before_phase != "round_over" and self.game.phase == "round_over":
            self.ready.clear()
            self._snapshot_game_chips_locked()
        self._validate_game_locked()
        if self._game_signature() != before_signature:
            self._bump_revision()

    def _validate_game_locked(self) -> None:
        if self.game is None or not isinstance(self.game, WenlingMahjongGame):
            self.last_rule_issues = []
            return
        issues = validate_game_state(self.game)
        if issues != getattr(self, "last_rule_issues", []):
            self.last_rule_issues = issues[:20]
            if issues:
                try:
                    log_dir = Path(self.log_dir)
                    log_dir.mkdir(parents=True, exist_ok=True)
                    with (log_dir / "rule_issues.jsonl").open("a", encoding="utf-8") as handle:
                        handle.write(
                            json.dumps(
                                {
                                    "ts": time.time(),
                                    "round_no": self.game.round_no,
                                    "issues": issues[:20],
                                    "de_indicator": self.game.de_indicator,
                                    "wall_remaining": len(self.game.wall),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )
                except OSError:
                    pass

    def _snapshot_game_chips_locked(self) -> None:
        if self.game is None:
            return
        chips = getattr(self, "account_chips", None)
        if chips is None:
            self.account_chips = {}
            chips = self.account_chips
        for player in self.game.players:
            name = getattr(player, "name", "")
            if name:
                chips[str(name)] = int(getattr(player, "chips", 0))

    def _game_signature(self) -> tuple[Any, ...] | None:
        if self.game is None:
            return None
        pending = self.game.pending or {}
        decisions = pending.get("decisions_by_seat") or {}
        ai_precomputed = pending.get("ai_precomputed_actions") or {}
        ai_thinking_by_seat = pending.get("ai_thinking_by_seat") or {}
        return (
            getattr(self, "room_generation", 1),
            self.game.round_no,
            self.game.phase,
            self.game.current_player,
            self.game.winner,
            len(self.game.wall),
            len(self.game.history),
            pending.get("kind"),
            pending.get("pending_id"),
            pending.get("from"),
            pending.get("tile"),
            pending.get("current_responder"),
            tuple(pending.get("responders", [])),
            tuple(pending.get("ai_candidates", [])),
            tuple(sorted(int(seat) for seat in decisions.keys())),
            tuple(sorted((int(seat), str(action)) for seat, action in ai_precomputed.items())),
            tuple(sorted((int(seat), bool(value)) for seat, value in ai_thinking_by_seat.items())),
            bool(pending.get("ai_thinking")),
            str(pending.get("ai_precomputed_action")),
        )

    def _action_token_for(self, seat: int | None) -> str | None:
        self._ensure_runtime_fields_locked()
        if self.game is None or seat is None:
            return None
        pending = self.game.pending or {}
        pending_id = self._current_pending_id_locked()
        parts = [
            self.room_generation,
            self.game.round_no,
            self.game.phase,
            self.game.current_player,
            self.game.winner,
            len(self.game.wall),
            len(self.game.history),
            seat,
            pending_id,
            pending.get("kind"),
            pending.get("response_kind"),
            pending.get("from"),
            pending.get("tile"),
            pending.get("current_responder"),
            pending.get("poll_index"),
        ]
        return "|".join("" if item is None else str(item) for item in parts)

    def _view_payload(self, payload: dict[str, Any], account: str | None) -> dict[str, Any]:
        viewer = self._seat_for(account) if account else None
        if viewer is not None:
            payload = self._rotate_payload_for_viewer(payload, viewer)
        return self._decorate_state(payload, account)

    @staticmethod
    def _relative_seat(absolute_seat: Any, viewer_seat: int) -> Any:
        if absolute_seat is None:
            return None
        try:
            return (int(absolute_seat) - viewer_seat) % 4
        except (TypeError, ValueError):
            return absolute_seat

    @staticmethod
    def _absolute_order(viewer_seat: int) -> list[int]:
        return [(viewer_seat + offset) % 4 for offset in range(4)]

    @staticmethod
    def _table_position_label(relative_seat: int) -> str:
        return ["\u4e0b", "\u53f3", "\u4e0a", "\u5de6"][int(relative_seat) % 4]

    def _rotate_payload_for_viewer(self, payload: dict[str, Any], viewer_seat: int) -> dict[str, Any]:
        order = self._absolute_order(viewer_seat)
        relative_by_absolute = {absolute: relative for relative, absolute in enumerate(order)}

        def rel(value: Any) -> Any:
            return self._relative_seat(value, viewer_seat)

        def rotate_meld(meld: dict[str, Any]) -> dict[str, Any]:
            item = dict(meld)
            if "from" in item:
                item["absolute_from"] = item.get("from")
                item["from"] = rel(item.get("from"))
            return item

        players_by_abs: dict[int, dict[str, Any]] = {}
        for raw_player in payload.get("players", []):
            absolute = int(raw_player.get("seat", 0))
            player = dict(raw_player)
            player["absolute_seat"] = absolute
            player["seat"] = relative_by_absolute.get(absolute, rel(absolute))
            player["table_position"] = ["下", "右", "上", "左"][int(player["seat"])]
            player["table_position"] = self._table_position_label(int(player["seat"]))
            player["melds"] = [rotate_meld(dict(meld)) for meld in player.get("melds", [])]
            players_by_abs[absolute] = player
        if players_by_abs:
            payload["players"] = [players_by_abs[absolute] for absolute in order if absolute in players_by_abs]

        for key in ("dealer", "next_dealer", "current_player", "winner"):
            if key in payload:
                payload[key] = rel(payload.get(key))

        pending = payload.get("pending")
        if isinstance(pending, dict):
            pending = dict(pending)
            pending.pop("current_responder", None)
            for key in ("from",):
                if key in pending:
                    pending[f"absolute_{key}"] = pending.get(key)
                    pending[key] = rel(pending.get(key))
            for key in ("responders", "ai_candidates", "decision_seats", "waiting_for_seats"):
                if isinstance(pending.get(key), list):
                    pending[f"absolute_{key}"] = list(pending[key])
                    pending[key] = [rel(value) for value in pending[key]]
            payload["pending"] = pending

        settlement = payload.get("settlement")
        if isinstance(settlement, dict):
            settlement = dict(settlement)
            if "winner" in settlement:
                settlement["absolute_winner"] = settlement.get("winner")
                settlement["winner"] = rel(settlement.get("winner"))
            if settlement.get("discarder") is not None:
                settlement["absolute_discarder"] = settlement.get("discarder")
                settlement["discarder"] = rel(settlement.get("discarder"))
            for key in ("scores", "deltas", "point_deltas"):
                values = settlement.get(key)
                if isinstance(values, list) and len(values) >= 4:
                    settlement[key] = [values[absolute] for absolute in order]
            hand_luck = settlement.get("hand_luck")
            if isinstance(hand_luck, list) and len(hand_luck) >= 4:
                rotated_luck = []
                for absolute in order:
                    item = dict(hand_luck[absolute])
                    item["absolute_seat"] = absolute
                    item["seat"] = relative_by_absolute[absolute]
                    rotated_luck.append(item)
                settlement["hand_luck"] = rotated_luck
            payload["settlement"] = settlement

        temporary_bao = payload.get("temporary_bao")
        if isinstance(temporary_bao, dict):
            temporary_bao = dict(temporary_bao)
            if "seat" in temporary_bao:
                temporary_bao["absolute_seat"] = temporary_bao.get("seat")
                temporary_bao["seat"] = rel(temporary_bao.get("seat"))
            payload["temporary_bao"] = temporary_bao

        bao_liabilities = payload.get("bao_liabilities")
        if isinstance(bao_liabilities, list):
            rotated_liabilities = []
            for raw_item in bao_liabilities:
                if not isinstance(raw_item, dict):
                    rotated_liabilities.append(raw_item)
                    continue
                item = dict(raw_item)
                if "liable_seat" in item:
                    item["absolute_liable_seat"] = item.get("liable_seat")
                    item["liable_seat"] = rel(item.get("liable_seat"))
                if "target_winner" in item:
                    item["absolute_target_winner"] = item.get("target_winner")
                    item["target_winner"] = rel(item.get("target_winner"))
                rotated_liabilities.append(item)
            payload["bao_liabilities"] = rotated_liabilities

        history = []
        for raw_entry in payload.get("history", []):
            entry = dict(raw_entry)
            for key in ("seat", "winner", "from", "player"):
                if key in entry:
                    entry[f"absolute_{key}"] = entry.get(key)
                    entry[key] = rel(entry.get(key))
            history.append(entry)
        payload["history"] = history

        return payload

    def _seat_payload(self, viewer_seat: int | None = None) -> list[dict[str, Any]]:
        effective = self._seat_effective_accounts()
        order = self._absolute_order(viewer_seat) if viewer_seat is not None else list(range(4))
        now = time.time()
        return [
            {
                "seat": relative if viewer_seat is not None else seat,
                "absolute_seat": seat,
                "table_position": ["下", "右", "上", "左"][seat],
                "table_position": self._table_position_label(relative if viewer_seat is not None else seat),
                "account": account,
                "effective_account": effective[seat],
                "is_ai": bool(effective[seat] and effective[seat] in AI_ACCOUNTS),
                "online": True if effective[seat] in AI_ACCOUNTS else self._presence_payload(account, now)["online"],
                "last_seen_age_sec": 0.0 if effective[seat] in AI_ACCOUNTS else self._presence_payload(account, now)["last_seen_age_sec"],
                "online_timeout_sec": PRESENCE_ONLINE_SEC,
                "ready": bool(account and account in self.ready),
            }
            for relative, seat in enumerate(order)
            for account in [self.seats[seat]]
        ]

    def _stats_payload(self) -> list[dict[str, Any]]:
        if self.game is None and not self._human_accounts():
            return []
        rows = self.db.stats_for_accounts(self._effective_accounts())
        for row in rows:
            account = str(row.get("account") or "")
            room = self.room_luck.get(account) or {}
            count = int(room.get("luck_score_count") or 0)
            for period in ("all", "today"):
                period_stats = row.get(period)
                if isinstance(period_stats, dict):
                    period_stats.pop("luck_score", None)
                    period_stats.pop("luck_hands", None)
            row["room"] = {
                "luck_score": round(float(room.get("luck_score_total") or 0) / count, 1) if count else None,
                "luck_hands": count,
            }
        return rows

