from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import gzip
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from wenling_lan_host.auth import hash_password
from wenling_lan_host.server import BattleApplication, ReusableThreadingHTTPServer, make_handler


ROOT = Path(__file__).resolve().parents[1]


class LanServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.application = BattleApplication(
            Path(self.temp.name),
            ROOT / "static",
            service_name="wenling-lan-mobile-foundation",
            bind_host="0.0.0.0",
            bind_port=8765,
            expose_host_info=True,
            initial_invite_codes=["7392"],
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

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    def request_json(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict | None = None,
        token: str | None = None,
        remote: bool = False,
    ) -> dict:
        if path == "/api/auth/register" and body is not None:
            body = {**body}
            body.setdefault("password", "secret123")
            body.setdefault("invite_code", "7392")
        if path == "/api/auth/login" and body is not None:
            body = {**body}
            body.setdefault("password", "secret123")
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if remote:
            headers["X-Forwarded-For"] = "192.168.1.22"
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.loads(response.read().decode("utf-8"))

    @contextmanager
    def expect_http_error(self, expected_code: int) -> Iterator[None]:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            yield
        try:
            self.assertEqual(raised.exception.code, expected_code)
        finally:
            raised.exception.close()

    def test_health_and_host_info(self) -> None:
        self.assertTrue(self.get_json("/api/health")["ok"])
        info = self.get_json("/api/host/info")
        self.assertEqual(info["host"], "0.0.0.0")
        self.assertTrue(info["capabilities"]["lan_browser_clients"])
        self.assertFalse(info["capabilities"]["cloudflare"])

    def test_http11_gzip_and_static_cache_headers(self) -> None:
        request = urllib.request.Request(
            self.base + "/api/tiles",
            headers={"Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(request, timeout=3) as response:
            self.assertEqual(response.version, 11)
            self.assertEqual(response.headers.get("Content-Encoding"), "gzip")
            payload = json.loads(gzip.decompress(response.read()).decode("utf-8"))
        self.assertIn("m1", payload)

        with urllib.request.urlopen(self.base + "/battle_app.js", timeout=3) as response:
            self.assertEqual(response.headers.get("Cache-Control"), "public, max-age=3600")
        with urllib.request.urlopen(self.base + "/battle_geometry_v7.css", timeout=3) as response:
            self.assertEqual(response.status, 200)
        with urllib.request.urlopen(self.base + "/battle_table_model.js", timeout=3) as response:
            self.assertEqual(response.status, 200)
        with urllib.request.urlopen(self.base + "/battle_table_renderer.js", timeout=3) as response:
            self.assertEqual(response.status, 200)
        for removed_ui_path in (
            "/battle_geometry_v4.css",
            "/battle_geometry_v3.css",
            "/battle_geometry_v5.css",
            "/battle_geometry_v6.css",
            "/battle_device_check.html",
            "/battle_device_check.js",
            "/battle_ui_qa.html",
            "/battle_ui_qa.js",
            "/assets/battle_table_v7/atlas.json",
        ):
            with self.expect_http_error(404):
                urllib.request.urlopen(self.base + removed_ui_path, timeout=3)

    def test_training_surface_does_not_exist(self) -> None:
        with self.expect_http_error(404):
            urllib.request.urlopen(self.base + "/api/training/status", timeout=3)

    def test_local_accounts_page_loads_its_script(self) -> None:
        with urllib.request.urlopen(self.base + "/battle/accounts", timeout=3) as response:
            self.assertEqual(response.status, 200)
        with urllib.request.urlopen(self.base + "/battle_accounts.js", timeout=3) as response:
            self.assertEqual(response.status, 200)

    def test_local_layout_editor_is_available_for_pc_debug_only(self) -> None:
        for path in ("/battle-layout-editor", "/battle_layout_box_editor.html"):
            with urllib.request.urlopen(self.base + path, timeout=3) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("温岭麻将牌桌框线编辑器", response.read().decode("utf-8"))

    def test_lan_client_gets_host_info_but_not_admin_pages(self) -> None:
        headers = {"X-Forwarded-For": "192.168.1.22"}
        for path in ("/api/health", "/api/host/info", "/battle-login"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
        for path in ("/battle/accounts", "/battle_accounts.js"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with self.expect_http_error(404):
                urllib.request.urlopen(request, timeout=3)
        for path in ("/battle_device_check.html", "/battle_device_check.js"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with self.expect_http_error(404):
                urllib.request.urlopen(request, timeout=3)
        for path in ("/battle-layout-editor", "/battle_layout_box_editor.html"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with self.expect_http_error(404):
                urllib.request.urlopen(request, timeout=3)

    def test_remote_player_can_register_chinese_username(self) -> None:
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "温岭玩家甲"},
            remote=True,
        )
        self.assertEqual(registered["account"], "温岭玩家甲")
        self.assertTrue(registered["session_token"])
        self.assertTrue(
            self.request_json(
                "/api/battle/state",
                token=registered["session_token"],
                remote=True,
            )
        )
        self.assertIn(
            "温岭玩家甲",
            self.request_json("/api/battle/available-accounts", remote=True)["accounts"],
        )

        for invalid in ("温岭玩家甲", "一" * 13, "带 空格", "AI1"):
            with self.expect_http_error(400):
                self.request_json(
                    "/api/auth/register",
                    method="POST",
                    body={"account": invalid},
                    remote=True,
                )

    def test_seated_player_can_reseat_after_round_over(self) -> None:
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "alice"},
            remote=True,
        )
        token = registered["session_token"]
        state = self.request_json("/api/battle/state", token=token, remote=True)
        state = self.request_json(
            "/api/battle/sit",
            method="POST",
            body={"seat": 0, "room_generation": state["room_generation"]},
            token=token,
            remote=True,
        )
        state = self.request_json(
            "/api/battle/ready",
            method="POST",
            body={"room_generation": state["room_generation"]},
            token=token,
            remote=True,
        )
        assert self.application.session.game is not None
        with self.application.session.lock:
            if hasattr(self.application.session.game, "cancel_async_ai_jobs"):
                self.application.session.game.cancel_async_ai_jobs()
            self.application.session.game.phase = "turn"
            self.application.session.game.pending = None
            self.application.session.game.current_player = 0
        with self.expect_http_error(400):
            self.request_json(
                "/api/battle/reset",
                method="POST",
                body={"account": "mallory", "room_generation": state["room_generation"]},
                token=token,
                remote=True,
            )

        assert self.application.session.game is not None
        self.application.session.game.phase = "round_over"
        current = self.request_json("/api/battle/state", token=token, remote=True)
        reseated = self.request_json(
            "/api/battle/reset",
            method="POST",
            body={"account": "mallory", "room_generation": current["room_generation"]},
            token=token,
            remote=True,
        )
        self.assertFalse(reseated["game_started"])
        self.assertIn("alice", [seat["account"] for seat in reseated["seats"]])
        self.assertGreater(reseated["room_generation"], current["room_generation"])

    def test_player_login_uses_token_and_body_cannot_spoof_account(self) -> None:
        self.application.database.create_player_account("alice", hash_password("secret123"), "7392")
        self.application.database.create_player_account("bob", hash_password("secret123"), "7392")
        available = self.request_json("/api/battle/available-accounts", remote=True)
        self.assertEqual(available["accounts"], ["alice", "bob"])

        login = self.request_json(
            "/api/auth/login",
            method="POST",
            body={"account": "alice"},
            remote=True,
        )
        token = login["session_token"]
        state = self.request_json("/api/battle/state", token=token, remote=True)
        seated = self.request_json(
            "/api/battle/sit",
            method="POST",
            body={
                "account": "bob",
                "seat": 0,
                "room_generation": state["room_generation"],
            },
            token=token,
            remote=True,
        )
        self.assertEqual(seated["seats"][0]["account"], "alice")

        with self.expect_http_error(401):
            self.request_json("/api/battle/state", remote=True)

    def test_new_login_invalidates_old_token_and_disabled_account_cannot_login(self) -> None:
        self.application.database.create_player_account("alice", hash_password("secret123"), "7392")
        first = self.request_json(
            "/api/auth/login",
            method="POST",
            body={"account": "alice"},
            remote=True,
        )
        second = self.request_json(
            "/api/auth/login",
            method="POST",
            body={"account": "alice"},
            remote=True,
        )
        with self.expect_http_error(401):
            self.request_json("/api/battle/state", token=first["session_token"], remote=True)
        self.assertTrue(self.request_json("/api/battle/state", token=second["session_token"], remote=True))

        self.application.database.set_account_enabled("alice", False)
        with self.expect_http_error(400):
            self.request_json(
                "/api/auth/login",
                method="POST",
                body={"account": "alice"},
                remote=True,
            )

    def test_local_stats_reset_route_is_reachable(self) -> None:
        reset = self.request_json("/api/battle/stats/reset", method="POST", body={})
        self.assertTrue(reset["ok"])
        self.assertIn("deleted", reset)

    def test_remote_player_cannot_call_admin_routes_or_spoof_forwarded_loopback(self) -> None:
        for path, body in (
            ("/api/battle/kick", {"account": "mallory", "target": "alice", "room_generation": 1}),
            ("/api/battle/stats/reset", {}),
        ):
            request = urllib.request.Request(
                self.base + path,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json", "X-Forwarded-For": "192.168.1.22"},
                method="POST",
            )
            with self.expect_http_error(404):
                urllib.request.urlopen(request, timeout=3)

        request = urllib.request.Request(
            self.base + "/battle/accounts",
            headers={"X-Forwarded-For": "127.0.0.1, 192.168.1.22"},
        )
        with self.expect_http_error(404):
            urllib.request.urlopen(request, timeout=3)
