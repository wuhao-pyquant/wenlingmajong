from __future__ import annotations

from contextlib import contextmanager
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from collections.abc import Iterator
from pathlib import Path

from wenling_lan_host.auth import hash_password
from wenling_lan_host.server import BattleApplication, ReusableThreadingHTTPServer, make_handler


ROOT = Path(__file__).resolve().parents[1]


class OnlineServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.application = BattleApplication(
            Path(self.temp.name),
            ROOT / "static",
            service_name="wenling-online-test",
            bind_host="127.0.0.1",
            bind_port=0,
            expose_host_info=True,
            admin_username="root",
            admin_password_hash=hash_password("admin123"),
            initial_invite_codes=["7392"],
            max_rooms=3,
            quiet_http_logs=True,
        )
        self.server = ReusableThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.application))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.application.close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        token: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict:
        request_headers = dict(headers or {})
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        if token:
            request_headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=request_headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def open_path(self, path: str, *, headers: dict[str, str] | None = None) -> bytes:
        request = urllib.request.Request(self.base + path, headers=headers or {})
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.read()

    @contextmanager
    def expect_http_error(self, expected_code: int) -> Iterator[None]:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            yield
        try:
            self.assertEqual(raised.exception.code, expected_code)
        finally:
            raised.exception.close()

    def register_player(self, account: str, password: str = "secret123") -> dict:
        return self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": account, "password": password, "invite_code": "7392"},
        )

    def login_admin(self) -> dict:
        return self.request_json(
            "/api/auth/login",
            method="POST",
            body={"account": "root", "password": "admin123"},
        )

    def test_online_pages_load_expected_scripts(self) -> None:
        for path, expected in (
            ("/battle-login", "battle_lobby.js"),
            ("/battle", "battle_app.js"),
            ("/battle-admin", "battle_admin.js"),
            ("/battle/admin", "battle_admin.js"),
        ):
            request = urllib.request.Request(self.base + path)
            with urllib.request.urlopen(request, timeout=5) as response:
                html = response.read().decode("utf-8")
            self.assertIn(expected, html)

    def test_task6_review_owner_controls_frontend_contract(self) -> None:
        battle_html = (ROOT / "static" / "battle.html").read_text(encoding="utf-8")
        battle_app = (ROOT / "static" / "battle_app.js").read_text(encoding="utf-8")
        lobby_app = (ROOT / "static" / "battle_lobby.js").read_text(encoding="utf-8")

        self.assertIn('id="ownerRoomControls"', battle_html)
        self.assertIn("BATTLE_ROOM_SUMMARY_STORAGE_KEY", battle_app)
        self.assertIn("refreshBattleRoomSummary", battle_app)
        self.assertIn("isBattleRoomOwner", battle_app)
        self.assertIn("ownerApplyRoomSettings", battle_app)
        self.assertIn("ownerKickRoomPlayer", battle_app)
        self.assertIn("ownerCloseBattleRoom", battle_app)
        self.assertIn('/api/lobby/rooms/${encodeURIComponent(roomId)}/settings', battle_app)
        self.assertIn('/api/lobby/rooms/${encodeURIComponent(roomId)}/kick', battle_app)
        self.assertIn('/api/lobby/rooms/${encodeURIComponent(roomId)}/close', battle_app)
        self.assertIn('{ confirm: "CLOSE_ROOM" }', battle_app)
        self.assertIn("ROOM_SUMMARY_KEY", lobby_app)
        self.assertIn("saveRoomSummary", lobby_app)
        self.assertIn("updateCreateRoomAvailability", lobby_app)
        self.assertIn("owner_account", lobby_app)
        self.assertIn('"waiting"', lobby_app)
        self.assertIn('"round_over"', lobby_app)
        self.assertIn('"closing"', lobby_app)
        self.assertNotIn("?{", battle_app)
        self.assertNotIn("?{", lobby_app)

    def test_task6_admin_room_frontend_contract(self) -> None:
        admin_html = (ROOT / "static" / "battle_admin.html").read_text(encoding="utf-8")
        admin_app = (ROOT / "static" / "battle_admin.js").read_text(encoding="utf-8")

        self.assertIn('id="adminRoomList"', admin_html)
        self.assertIn("房间监控", admin_html)
        self.assertIn('api("/api/admin/rooms")', admin_app)
        self.assertIn("renderRooms", admin_app)
        self.assertIn("统一 AI", admin_app)
        self.assertIn("关闭房间", admin_app)
        self.assertIn('/api/admin/rooms/${encodeURIComponent(roomId)}/close', admin_app)
        self.assertIn('{ confirm: "CLOSE_ROOM" }', admin_app)
        self.assertGreaterEqual(admin_app.count("window.confirm("), 3)
        self.assertNotIn('api("/api/lobby/rooms")', admin_app)
        self.assertNotIn('/api/lobby/rooms/${encodeURIComponent(roomId)}/close', admin_app)
        self.assertNotIn("?{", admin_app)

    def test_register_login_create_room_and_enter_room_state(self) -> None:
        registered = self.register_player("alice")
        self.assertEqual(registered["role"], "player")
        token = registered["session_token"]

        created = self.request_json(
            "/api/lobby/rooms",
            method="POST",
            body={"room_name": "first room", "ai_policy": "low"},
            token=token,
        )
        room_id = created["room_id"]
        self.assertEqual(created["owner_account"], "alice")

        state = self.request_json(f"/api/battle/{room_id}/state", token=token)
        self.assertFalse(state["game_started"])
        self.assertEqual(state["room_id"], room_id)

    def test_room_wait_heartbeat_ready_and_leave_routes(self) -> None:
        player = self.register_player("alice")
        token = player["session_token"]
        created = self.request_json(
            "/api/lobby/rooms",
            method="POST",
            body={"room_name": "route room", "ai_policy": "low"},
            token=token,
        )
        room_id = created["room_id"]

        waited = self.request_json(f"/api/battle/{room_id}/wait?since=0&timeout=0.01", token=token)
        self.assertEqual(waited["room_id"], room_id)

        heartbeat = self.request_json(
            f"/api/battle/{room_id}/heartbeat",
            method="POST",
            body={"room_generation": waited["room_generation"]},
            token=token,
        )
        self.assertTrue(heartbeat["ok"])
        self.assertEqual(heartbeat["account"], "alice")

        seated = self.request_json(
            f"/api/battle/{room_id}/sit",
            method="POST",
            body={"seat": 0, "room_generation": waited["room_generation"]},
            token=token,
        )
        self.assertEqual(seated["seats"][0]["account"], "alice")

        ready = self.request_json(
            f"/api/battle/{room_id}/ready",
            method="POST",
            body={"room_generation": seated["room_generation"]},
            token=token,
        )
        self.assertTrue(ready["game_started"])

        left = self.request_json(
            f"/api/battle/{room_id}/leave",
            method="POST",
            body={"room_generation": ready["room_generation"]},
            token=token,
        )
        self.assertIn("seats", left)

    def test_auth_me_logout_and_admin_auth_semantics(self) -> None:
        with self.expect_http_error(401):
            self.request_json("/api/auth/me")
        with self.expect_http_error(401):
            self.request_json("/api/auth/me", token="bad-token")
        with self.expect_http_error(401):
            self.request_json("/api/admin/accounts")

        registered = self.register_player("alice")
        token = registered["session_token"]
        me = self.request_json("/api/auth/me", token=token)
        self.assertEqual(me["account"], "alice")
        self.assertEqual(me["role"], "player")

        with self.expect_http_error(403):
            self.request_json("/api/admin/accounts", token=token)

        self.assertTrue(
            self.request_json("/api/auth/logout", method="POST", body={}, token=token)["ok"]
        )
        with self.expect_http_error(401):
            self.request_json("/api/auth/me", token=token)

    def test_lobby_room_owner_management_and_room_scoped_sit(self) -> None:
        owner = self.register_player("alice")
        guest = self.register_player("bob")
        owner_token = owner["session_token"]
        guest_token = guest["session_token"]

        created = self.request_json(
            "/api/lobby/rooms",
            method="POST",
            body={"room_name": "first room", "ai_policy": "low"},
            token=owner_token,
        )
        room_id = created["room_id"]
        rooms = self.request_json("/api/lobby/rooms", token=guest_token)
        self.assertEqual([room["room_id"] for room in rooms["rooms"]], [room_id])

        updated = self.request_json(
            f"/api/lobby/rooms/{room_id}/settings",
            method="POST",
            body={"room_name": "owner room", "ai_policy": "high"},
            token=owner_token,
        )
        self.assertEqual(updated["room_name"], "owner room")
        self.assertEqual(updated["ai_policy"], "high")
        with self.expect_http_error(403):
            self.request_json(
                f"/api/lobby/rooms/{room_id}/settings",
                method="POST",
                body={"room_name": "guest room"},
                token=guest_token,
            )

        seated = self.request_json(
            f"/api/battle/{room_id}/sit",
            method="POST",
            body={"seat": 0, "room_generation": updated["room_generation"]},
            token=guest_token,
        )
        self.assertEqual(seated["seats"][0]["account"], "bob")

        kicked = self.request_json(
            f"/api/lobby/rooms/{room_id}/kick",
            method="POST",
            body={"target": "bob", "room_generation": seated["room_generation"]},
            token=owner_token,
        )
        self.assertNotIn("bob", [seat["account"] for seat in kicked["seats"] if seat["account"]])

        closed = self.request_json(
            f"/api/lobby/rooms/{room_id}/close",
            method="POST",
            body={"confirm": "CLOSE_ROOM"},
            token=owner_token,
        )
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(self.request_json("/api/lobby/rooms", token=owner_token)["rooms"], [])

    def test_admin_account_and_invite_management(self) -> None:
        player = self.register_player("alice")
        admin_token = self.login_admin()["session_token"]

        accounts = self.request_json("/api/admin/accounts", token=admin_token)["accounts"]
        self.assertIn("alice", [account["account"] for account in accounts])
        roles = {account["account"]: account["role"] for account in accounts}
        self.assertEqual(roles["root"], "admin")
        self.assertEqual(roles["alice"], "player")
        self.assertEqual(roles["AI1"], "ai")

        disabled = self.request_json(
            "/api/admin/accounts/alice/disable",
            method="POST",
            body={},
            token=admin_token,
        )
        self.assertFalse(disabled["enabled"])
        with self.expect_http_error(401):
            self.request_json("/api/auth/me", token=player["session_token"])

        enabled = self.request_json(
            "/api/admin/accounts/alice/enable",
            method="POST",
            body={},
            token=admin_token,
        )
        self.assertTrue(enabled["enabled"])
        reset = self.request_json(
            "/api/admin/accounts/alice/reset-password",
            method="POST",
            body={"password": "newpass123"},
            token=admin_token,
        )
        self.assertTrue(reset["ok"])
        with self.expect_http_error(401):
            self.request_json(
                "/api/auth/login",
                method="POST",
                body={"account": "alice", "password": "secret123"},
            )
        self.assertEqual(
            self.request_json(
                "/api/auth/login",
                method="POST",
                body={"account": "alice", "password": "newpass123"},
            )["account"],
            "alice",
        )

        generated = self.request_json(
            "/api/admin/invite-codes",
            method="POST",
            body={"code": "WL8K2", "max_uses": 2},
            token=admin_token,
        )
        self.assertEqual(generated["code"], "WL8K2")
        disabled_invite = self.request_json(
            "/api/admin/invite-codes/WL8K2/disable",
            method="POST",
            body={},
            token=admin_token,
        )
        self.assertFalse(disabled_invite["enabled"])
        with self.expect_http_error(400):
            self.request_json(
                "/api/auth/register",
                method="POST",
                body={"account": "charlie", "password": "secret123", "invite_code": "WL8K2"},
            )

    def test_admin_presence_includes_anonymous_visitors_and_logged_in_sessions(self) -> None:
        self.open_path("/battle-login", headers={"X-Visitor-ID": "anon-browser"})
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "alice", "password": "secret123", "invite_code": "7392"},
            headers={"X-Visitor-ID": "alice-browser"},
        )
        login = self.login_admin()
        admin_token = login["session_token"]

        presence = self.request_json("/api/admin/presence", token=admin_token)
        visitors = presence["visitors"]
        anonymous = [row for row in visitors if row["visitor_id"] == "anon-browser"]
        logged_in_accounts = {row["account"] for row in visitors if row.get("account")}
        visitor_ids = {row["visitor_id"] for row in visitors}

        self.assertEqual(len(anonymous), 1)
        self.assertIsNone(anonymous[0]["account"])
        self.assertIn("alice", logged_in_accounts)
        self.assertIn("root", logged_in_accounts)
        self.assertNotIn(registered["session_token"], visitor_ids)
        self.assertNotIn(admin_token, visitor_ids)

    def test_admin_room_routes_require_admin_and_allow_admin_close(self) -> None:
        owner = self.register_player("alice")
        guest = self.register_player("bob")
        owner_token = owner["session_token"]
        guest_token = guest["session_token"]
        admin_token = self.login_admin()["session_token"]

        created = self.request_json(
            "/api/lobby/rooms",
            method="POST",
            body={"room_name": "admin watch", "ai_policy": "high"},
            token=owner_token,
        )
        room_id = created["room_id"]

        admin_rooms = self.request_json("/api/admin/rooms", token=admin_token)
        self.assertEqual(admin_rooms["max_rooms"], 3)
        self.assertEqual([room["room_id"] for room in admin_rooms["rooms"]], [room_id])
        self.assertEqual(admin_rooms["rooms"][0]["owner_account"], "alice")
        self.assertEqual(admin_rooms["rooms"][0]["ai_policy"], "high")

        with self.expect_http_error(403):
            self.request_json("/api/admin/rooms", token=guest_token)
        with self.expect_http_error(401):
            self.request_json("/api/admin/rooms")

        with self.expect_http_error(400):
            self.request_json(
                f"/api/admin/rooms/{room_id}/close",
                method="POST",
                body={},
                token=admin_token,
            )

        closed = self.request_json(
            f"/api/admin/rooms/{room_id}/close",
            method="POST",
            body={"confirm": "CLOSE_ROOM"},
            token=admin_token,
        )
        self.assertEqual(closed["status"], "closed")
        self.assertEqual(self.request_json("/api/admin/rooms", token=admin_token)["rooms"], [])

    def test_logout_without_visitor_header_removes_account_presence(self) -> None:
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "alice", "password": "secret123", "invite_code": "7392"},
            headers={"X-Visitor-ID": "alice-browser"},
        )

        self.assertTrue(
            self.request_json(
                "/api/auth/logout",
                method="POST",
                body={},
                token=registered["session_token"],
            )["ok"]
        )

        admin_token = self.login_admin()["session_token"]
        presence = self.request_json("/api/admin/presence", token=admin_token)
        logged_in_accounts = {row["account"] for row in presence["visitors"] if row.get("account")}
        self.assertNotIn("alice", logged_in_accounts)


if __name__ == "__main__":
    unittest.main()
