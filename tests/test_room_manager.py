from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.auth import AuthIdentity
from wenling_lan_host.battle_db import BattleDatabase
from wenling_lan_host.rooms import RoomManager


class RoomManagerTests(unittest.TestCase):
    def make_manager(self, max_rooms: int = 3) -> tuple[RoomManager, tempfile.TemporaryDirectory]:
        temp = tempfile.TemporaryDirectory()
        db = BattleDatabase(Path(temp.name) / "battle.sqlite3")
        db.create_invite_code("7392", created_by="root", max_uses=8)
        for account in ("owner", "bob", "admin"):
            db.create_player_account(account, f"hash-{account}", "7392")
        db.bootstrap_admin("admin", "hash-admin")
        return RoomManager(db, Path(temp.name) / "logs", max_rooms=max_rooms, default_ai_policy="low"), temp

    def test_create_room_sets_owner_and_enforces_limits(self) -> None:
        manager, temp = self.make_manager(max_rooms=1)
        with temp:
            room = manager.create_room("owner", "room one")
            self.assertEqual(room["owner_account"], "owner")
            self.assertEqual(room["ai_policy"], "low")
            self.assertEqual(room["seats"][0]["account"], "owner")
            self.assertEqual(room["ready_accounts"], [])

            with self.assertRaisesRegex(ValueError, "already owns"):
                manager.create_room("owner", "room two")
            with self.assertRaisesRegex(ValueError, "room limit"):
                manager.create_room("bob", "room two")

    def test_owner_and_admin_can_close_room_only_with_confirmation(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "room one")
            owner = AuthIdentity(account="owner", role="player", token="tok-owner")

            with self.assertRaisesRegex(ValueError, "confirmation"):
                manager.close_room(room["room_id"], owner, confirm="")

            closed = manager.close_room(room["room_id"], owner, confirm="CLOSE_ROOM")
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(manager.list_rooms()["rooms"], [])

    def test_close_room_retires_room_stops_threads_and_allows_recreate(self) -> None:
        manager, temp = self.make_manager(max_rooms=1)
        with temp:
            room = manager.create_room("owner", "room one")
            owner = AuthIdentity(account="owner", role="player", token="tok-owner")
            room_obj = manager.get_room(room["room_id"])
            worker = room_obj.session._room_worker
            ticker = room_obj.session._ticker

            self.assertTrue(worker.is_alive())
            self.assertTrue(ticker.is_alive())

            closed = manager.close_room(room["room_id"], owner, confirm="CLOSE_ROOM")

            self.assertEqual(closed["status"], "closed")
            self.assertEqual(manager.list_rooms()["rooms"], [])
            with self.assertRaisesRegex(ValueError, "room not found"):
                manager.get_room(room["room_id"])
            self.assertFalse(worker.is_alive())
            self.assertFalse(ticker.is_alive())

            replacement = manager.create_room("owner", "room two")
            self.assertEqual(replacement["owner_account"], "owner")
            self.assertNotEqual(replacement["room_id"], room["room_id"])

    def test_non_owner_cannot_change_room_settings(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "room one")
            bob = AuthIdentity(account="bob", role="player", token="tok-bob")

            with self.assertRaises(PermissionError):
                manager.set_room_settings(room["room_id"], bob, ai_policy="high")

            admin = AuthIdentity(account="admin", role="admin", token="tok-admin")
            updated = manager.set_room_settings(room["room_id"], admin, ai_policy="high")
            self.assertEqual(updated["ai_policy"], "high")

    def test_owner_and_admin_can_only_change_settings_outside_playing(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "room one")
            owner = AuthIdentity(account="owner", role="player", token="tok-owner")
            room_obj = manager.get_room(room["room_id"])
            for account, seat in [("owner", 0), ("bob", 1)]:
                room_obj.session.register(account)
                room_obj.session.sit(account, seat)
            room_obj.session.ready_account("owner", "low")
            room_obj.session.ready_account("bob", "low")

            with self.assertRaisesRegex(ValueError, "playing"):
                manager.set_room_settings(room["room_id"], owner, room_name="renamed")

    def test_room_manager_disallows_kick_while_playing(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "room one")
            owner = AuthIdentity(account="owner", role="player", token="tok-owner")
            room_obj = manager.get_room(room["room_id"])
            for account, seat in [("owner", 0), ("bob", 1)]:
                room_obj.session.register(account)
                room_obj.session.sit(account, seat)
            room_obj.session.ready_account("owner", "low")
            room_obj.session.ready_account("bob", "low")

            with self.assertRaisesRegex(ValueError, "playing"):
                manager.kick(room["room_id"], owner, "bob")

    def test_room_manager_caps_constructed_max_rooms_at_three(self) -> None:
        manager, temp = self.make_manager(max_rooms=99)
        with temp:
            self.assertEqual(manager.max_rooms, 3)
            self.assertEqual(manager.list_rooms()["max_rooms"], 3)

            manager.create_room("owner", "room one")
            manager.create_room("bob", "room two")
            manager.database.create_player_account("carol", "hash-carol", "7392")
            manager.create_room("carol", "room three")
            manager.database.create_player_account("dave", "hash-dave", "7392")
            with self.assertRaisesRegex(ValueError, "room limit"):
                manager.create_room("dave", "room four")


if __name__ == "__main__":
    unittest.main()
