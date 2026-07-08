from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wenling_core.tile_efficiency import TileEfficiencyPolicyModel

from .auth import AuthIdentity
from .battle_app import AI_POLICY_ALIASES, DEFAULT_AI_POLICY, BattleSession
from .battle_db import AI_ACCOUNTS, BattleDatabase


@dataclass
class BattleRoom:
    room_id: str
    room_name: str
    owner_account: str
    ai_policy: str
    session: BattleSession
    created_at: float
    last_active_at: float
    closed_at: float | None = None

    @property
    def status(self) -> str:
        if self.closed_at is not None:
            return "closed"
        phase = self.session.game.phase if self.session.game is not None else None
        if phase == "round_over":
            return "round_over"
        if self.session.game is not None:
            return "playing"
        return "waiting"


class RoomManager:
    def __init__(
        self,
        database: BattleDatabase,
        log_dir: Path,
        *,
        max_rooms: int = 3,
        default_ai_policy: str = DEFAULT_AI_POLICY,
    ):
        self.database = database
        self.log_dir = Path(log_dir)
        self.max_rooms = max(1, min(3, int(max_rooms)))
        self.default_ai_policy = self._normalize_ai_policy(default_ai_policy)
        self._lock = threading.RLock()
        self._rooms: dict[str, BattleRoom] = {}

    def create_room(
        self,
        owner_account: str,
        room_name: str | None = None,
        ai_policy: str | None = None,
    ) -> dict[str, Any]:
        owner = str(self.database.require_active_human_account(owner_account)["account_name"])
        policy = self._normalize_ai_policy(ai_policy or self.default_ai_policy)
        with self._lock:
            if any(room.owner_account == owner and room.closed_at is None for room in self._rooms.values()):
                raise ValueError("same player already owns an active room")
            active_rooms = [room for room in self._rooms.values() if room.closed_at is None]
            if len(active_rooms) >= self.max_rooms:
                raise ValueError("active room limit reached")
            room_id = self._new_room_id_locked()
            session = BattleSession(
                self.database,
                str(self.log_dir / room_id),
                model_factory=lambda _policy=None: TileEfficiencyPolicyModel(),
                analysis_model_factory=TileEfficiencyPolicyModel,
                runtime_context={"room_id": room_id, "owner_account": owner},
            )
            session.set_ai_policy(policy)
            now = time.time()
            room = BattleRoom(
                room_id=room_id,
                room_name=self._normalize_room_name(room_name, owner),
                owner_account=owner,
                ai_policy=policy,
                session=session,
                created_at=now,
                last_active_at=now,
            )
            self._rooms[room_id] = room
            room.session.sit(owner, 0)
            return self._summary(room)

    def list_rooms(self, viewer: str | None = None) -> dict[str, Any]:
        if viewer:
            self.database.require_active_human_account(viewer)
        with self._lock:
            rooms = [self._summary(room) for room in self._rooms.values() if room.closed_at is None]
        rooms.sort(key=lambda item: (float(item["created_at"]), str(item["room_id"])))
        return {"rooms": rooms, "max_rooms": self.max_rooms}

    def get_room(self, room_id: str) -> BattleRoom:
        with self._lock:
            return self._require_active_room_locked(room_id)

    def set_room_settings(
        self,
        room_id: str,
        actor: AuthIdentity,
        *,
        room_name: str | None = None,
        ai_policy: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            room = self._require_active_room_locked(room_id)
            self._require_owner_or_admin(room, actor)
            if room.status == "playing":
                raise ValueError("cannot change room settings while playing")
            if room_name is not None:
                room.room_name = self._normalize_room_name(room_name, room.owner_account)
            if ai_policy is not None:
                room.ai_policy = self._normalize_ai_policy(ai_policy)
                room.session.set_ai_policy(room.ai_policy)
            room.last_active_at = time.time()
            return self._summary(room)

    def close_room(self, room_id: str, actor: AuthIdentity, *, confirm: str) -> dict[str, Any]:
        with self._lock:
            room = self._require_active_room_locked(room_id)
            self._require_owner_or_admin(room, actor)
            if str(confirm or "").strip() != "CLOSE_ROOM":
                raise ValueError("room close requires confirmation")
            reason = "owner_closed" if actor.account == room.owner_account else "admin_closed"
            room.session.close_room(reason)
            room.closed_at = time.time()
            room.last_active_at = room.closed_at
            summary = self._summary(room)
            self._rooms.pop(room.room_id, None)
        room.session.close()
        return summary

    def kick(
        self,
        room_id: str,
        actor: AuthIdentity,
        target: str,
        room_generation: int | str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            room = self._require_active_room_locked(room_id)
            self._require_owner_or_admin(room, actor)
            if room.status == "playing":
                raise ValueError("cannot kick while playing")
            target_name = self.database.normalize_account(target)
            if target_name in AI_ACCOUNTS:
                raise ValueError("can only kick human players")
            if target_name not in room.session.seats:
                raise ValueError("target is not seated in this room")
            requester = actor.account if actor.account in room.session.seats else room.owner_account
            if requester in room.session.seats:
                payload = room.session.kick(requester, target_name, room_generation)
            else:
                seat = room.session.seats.index(target_name)
                payload = room.session.admin_clear_seat(seat, room_generation)
            room.last_active_at = time.time()
            return payload

    def close(self) -> None:
        with self._lock:
            rooms = list(self._rooms.values())
            self._rooms.clear()
        for room in rooms:
            room.session.close()

    def _summary(self, room: BattleRoom) -> dict[str, Any]:
        state = room.session.host_status()
        return {
            "room_id": room.room_id,
            "room_name": room.room_name,
            "owner_account": room.owner_account,
            "ai_policy": room.ai_policy,
            "status": room.status,
            "created_at": room.created_at,
            "last_active_at": room.last_active_at,
            "closed_at": room.closed_at,
            "seats": state["seats"],
            "ready_accounts": state["ready_accounts"],
            "game_started": state["game_started"],
            "room_generation": state["room_generation"],
            "room_revision": state["room_revision"],
        }

    def _require_active_room_locked(self, room_id: str) -> BattleRoom:
        key = str(room_id or "").strip().upper()
        room = self._rooms.get(key)
        if room is None or room.closed_at is not None:
            raise ValueError("room not found")
        return room

    def _require_owner_or_admin(self, room: BattleRoom, actor: AuthIdentity) -> None:
        if actor.role == "admin" or actor.account == room.owner_account:
            return
        raise PermissionError("only the room owner or an admin can manage this room")

    def _new_room_id_locked(self) -> str:
        while True:
            room_id = secrets.token_hex(2).upper()
            if room_id not in self._rooms:
                return room_id

    @staticmethod
    def _normalize_ai_policy(policy: str | None) -> str:
        key = str(policy or "").strip().lower()
        normalized = AI_POLICY_ALIASES.get(key)
        if normalized is None:
            raise ValueError("AI policy must be low or high")
        return normalized

    @staticmethod
    def _normalize_room_name(room_name: str | None, owner_account: str) -> str:
        value = str(room_name or "").strip()
        if not value:
            value = f"{owner_account} room"
        return value[:24]
