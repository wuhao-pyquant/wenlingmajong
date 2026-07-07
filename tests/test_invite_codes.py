from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.auth import PlayerSessionStore, hash_password, verify_password
from wenling_lan_host.battle_db import BattleDatabase


class InviteCodeTests(unittest.TestCase):
    def test_password_hash_round_trip_and_wrong_password_rejected(self) -> None:
        encoded = hash_password("secret123")

        self.assertTrue(verify_password("secret123", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        self.assertNotIn("secret123", encoded)

    def test_register_consumes_invite_and_login_returns_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_invite_code("7392", created_by="root", max_uses=1)
            store = PlayerSessionStore(db)

            registered = store.register_player("alice", "secret123", "7392")
            self.assertEqual(registered["account"], "alice")
            self.assertEqual(registered["role"], "player")
            self.assertTrue(registered["session_token"])

            identity = store.resolve_identity(registered["session_token"])
            self.assertEqual(identity.account, "alice")
            self.assertEqual(identity.role, "player")

            with self.assertRaisesRegex(ValueError, "invite"):
                store.register_player("bob", "secret123", "7392")

            relogged = store.login_password("alice", "secret123")
            self.assertEqual(relogged["role"], "player")
            self.assertEqual(store.resolve_identity(relogged["session_token"]).role, "player")

    def test_admin_can_disable_invite_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_invite_code("WL8K2", created_by="root")
            disabled = db.disable_invite_code("WL8K2")

            self.assertFalse(disabled["enabled"])
            with self.assertRaisesRegex(ValueError, "invite"):
                db.consume_invite_code("WL8K2")

    def test_recreating_exhausted_invite_code_resets_used_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_invite_code("7392", created_by="root", max_uses=1)
            consumed = db.consume_invite_code("7392")
            self.assertEqual(consumed["used_count"], 1)
            self.assertFalse(consumed["enabled"])

            recreated = db.create_invite_code("7392", created_by="root", max_uses=1)
            self.assertEqual(recreated["used_count"], 0)
            self.assertTrue(recreated["enabled"])

            consumed_again = db.consume_invite_code("7392")
            self.assertEqual(consumed_again["used_count"], 1)
            self.assertFalse(consumed_again["enabled"])


if __name__ == "__main__":
    unittest.main()
