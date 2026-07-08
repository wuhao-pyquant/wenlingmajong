from __future__ import annotations

import threading
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
import sqlite3

from wenling_lan_host.battle_app import BattleSession
from wenling_lan_host.battle_db import AI_ACCOUNTS, BattleDatabase
from wenling_lan_host.auth import hash_password, verify_password
from wenling_lan_host.config import HostConfig
from wenling_lan_host.server import BattleApplication


class OnlineDatabaseTests(unittest.TestCase):
    def test_config_reads_zeabur_port_and_online_data_dir(self) -> None:
        config = HostConfig.from_env(
            {
                "PORT": "9001",
                "WENLING_DATA_DIR": "/data",
                "WENLING_ADMIN_USERNAME": "root",
                "WENLING_ADMIN_PASSWORD": "secret",
                "WENLING_INVITE_CODES": "7392,WL8K2",
                "WENLING_MAX_ROOMS": "3",
            }
        )

        self.assertEqual(config.port, 9001)
        self.assertEqual(config.data_dir, Path("/data"))
        self.assertEqual(config.admin_username, "root")
        self.assertEqual(config.admin_password, "secret")
        self.assertEqual(config.initial_invite_codes, ["WL1234", "7392", "WL8K2"])
        self.assertEqual(config.max_rooms, 3)
        self.assertFalse(config.allow_public_register)

    def test_config_requires_env_for_admin_and_disables_public_register(self) -> None:
        config = HostConfig.from_env({})

        self.assertEqual(config.admin_username, "")
        self.assertEqual(config.admin_password, "")
        self.assertEqual(config.initial_invite_codes, ["WL1234"])
        self.assertFalse(config.allow_public_register)

    def test_application_bootstraps_default_invite_and_resets_human_passwords_to_1234(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            db = BattleDatabase(data_dir / "battle.sqlite3")
            self._seed_invite(db, "7392")
            db.create_player_account("alice", hash_password("secret123"), "7392")
            db.bootstrap_admin("root", hash_password("admin123"))

            app = BattleApplication(
                data_dir,
                Path(__file__).resolve().parents[1] / "static",
                admin_username="root",
                admin_password_hash=hash_password("admin123"),
                initial_invite_codes=[],
                quiet_http_logs=True,
            )
            try:
                self.assertEqual(app.database.invite_code("WL1234")["code"], "WL1234")
                self.assertTrue(verify_password("1234", app.database.account("alice")["password_hash"]))
                self.assertTrue(verify_password("1234", app.database.account("root")["password_hash"]))
                self.assertFalse(verify_password("secret123", app.database.account("alice")["password_hash"]))
                self.assertFalse(verify_password("admin123", app.database.account("root")["password_hash"]))
            finally:
                app.close()

    def test_new_database_schema_has_roles_passwords_ai_and_invites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            admin = db.bootstrap_admin("root", "hash-admin")
            self._seed_invite(db, "7392")
            player = db.create_player_account("alice", "hash-player", "7392")

            self.assertEqual(admin["role"], "admin")
            self.assertEqual(admin["password_hash"], "hash-admin")
            self.assertTrue(admin["enabled"])
            self.assertEqual(player["role"], "player")
            self.assertEqual(player["password_hash"], "hash-player")
            self.assertEqual(
                db.info()["tables"],
                ["accounts", "invite_codes", "audit_events", "battle_stats"],
            )

            for ai_name in AI_ACCOUNTS:
                row = db.account(ai_name)
                self.assertTrue(row["is_ai"])
                self.assertEqual(row["role"], "ai")
                with self.assertRaisesRegex(ValueError, "AI"):
                    db.require_active_human_account(ai_name)

    def test_old_schema_is_upgraded_to_online_schema_without_deleting_legacy_account(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "battle.sqlite3"
            with closing(sqlite3.connect(db_path)) as con, con:
                con.executescript(
                    """
                    CREATE TABLE accounts (
                        account_name TEXT PRIMARY KEY,
                        is_ai INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE battle_stats (
                        account_name TEXT NOT NULL,
                        period TEXT NOT NULL,
                        rounds INTEGER NOT NULL DEFAULT 0,
                        opening_shanten_total REAL NOT NULL DEFAULT 0,
                        de_draw_total INTEGER NOT NULL DEFAULT 0,
                        fan_flower_draw_total INTEGER NOT NULL DEFAULT 0,
                        normal_wins INTEGER NOT NULL DEFAULT 0,
                        leizi_wins INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (account_name, period)
                    );
                    """
                )
                con.execute(
                    "INSERT INTO accounts(account_name, is_ai, created_at) VALUES('legacy', 0, 0)"
                )

            db = BattleDatabase(db_path)

            self.assertEqual(
                db.info()["tables"],
                ["accounts", "invite_codes", "audit_events", "battle_stats"],
            )
            legacy = db.account("legacy")
            self.assertEqual(legacy["account_name"], "legacy")
            self.assertEqual(legacy["role"], "player")
            self.assertEqual(legacy["password_hash"], "")
            self.assertTrue(legacy["enabled"])
            with closing(db.connect()) as con:
                account_columns = {
                    str(row["name"]) for row in con.execute("PRAGMA table_info(accounts)").fetchall()
                }
                invite_columns = {
                    str(row["name"]) for row in con.execute("PRAGMA table_info(invite_codes)").fetchall()
                }
                audit_columns = {
                    str(row["name"]) for row in con.execute("PRAGMA table_info(audit_events)").fetchall()
                }
                stat_columns = {
                    str(row["name"]) for row in con.execute("PRAGMA table_info(battle_stats)").fetchall()
                }
            self.assertTrue({"enabled", "role", "password_hash", "last_login_at"}.issubset(account_columns))
            self.assertTrue(
                {"code", "enabled", "max_uses", "used_count", "created_by", "created_at", "disabled_at"}.issubset(
                    invite_columns
                )
            )
            self.assertTrue(
                {"id", "event_type", "actor", "target", "details_json", "created_at"}.issubset(audit_columns)
            )
            self.assertTrue(
                {"win_turn_total", "win_point_total", "luck_score_total", "luck_score_count"}.issubset(stat_columns)
            )
            for ai_name in AI_ACCOUNTS:
                row = db.account(ai_name)
                self.assertTrue(row["is_ai"])
                self.assertEqual(row["role"], "ai")
            self._seed_invite(db, "7392")
            player = db.create_player_account("alice", "hash-player", "7392")
            self.assertEqual(player["role"], "player")
            self.assertEqual(player["password_hash"], "hash-player")

    def test_disabled_player_cannot_be_required_for_gameplay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            self._seed_invite(db, "7392")
            db.create_player_account("alice", "hash-player", "7392")
            db.set_account_enabled("alice", False)

            with self.assertRaisesRegex(ValueError, "disabled"):
                db.require_active_human_account("alice")

    def test_create_player_account_rejects_empty_unknown_and_invalid_invites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")

            with self.assertRaisesRegex(ValueError, "invite"):
                db.create_player_account("alice", "hash-player", "")
            with self.assertRaisesRegex(ValueError, "invite"):
                db.create_player_account("alice", "hash-player", "ZZZZ")
            with self.assertRaisesRegex(ValueError, "invite"):
                db.create_player_account("alice", "hash-player", "abc")
            with self.assertRaisesRegex(ValueError, "invite"):
                db.create_player_account("alice", "hash-player", "AB-12")

    def test_create_player_account_rejects_duplicate_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            self._seed_invite(db, "7392", max_uses=2)
            db.create_player_account("alice", "hash-player", "7392")

            with self.assertRaisesRegex(ValueError, "exists|already"):
                db.create_player_account("alice", "hash-player-2", "7392")

    def test_register_player_rejects_passwordless_public_registration_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            session = BattleSession.__new__(BattleSession)
            session.db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            session.lock = threading.RLock()

            with self.assertRaisesRegex(ValueError, "invite|password"):
                session.register_player("alice")

    @staticmethod
    def _seed_invite(db: BattleDatabase, code: str, *, max_uses: int | None = 1) -> None:
        with closing(db.connect()) as con, con:
            con.execute(
                """
                INSERT INTO invite_codes(code, enabled, max_uses, used_count, created_by, created_at, disabled_at)
                VALUES(?, 1, ?, 0, 'root', 0, NULL)
                """,
                (code, max_uses),
            )


if __name__ == "__main__":
    unittest.main()
