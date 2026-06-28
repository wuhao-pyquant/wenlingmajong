from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

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

    def test_health_and_host_info(self) -> None:
        self.assertTrue(self.get_json("/api/health")["ok"])
        info = self.get_json("/api/host/info")
        self.assertEqual(info["host"], "0.0.0.0")
        self.assertTrue(info["capabilities"]["lan_browser_clients"])
        self.assertFalse(info["capabilities"]["cloudflare"])

    def test_training_surface_does_not_exist(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(self.base + "/api/training/status", timeout=3)
        self.assertEqual(raised.exception.code, 404)

    def test_local_accounts_page_loads_its_script(self) -> None:
        with urllib.request.urlopen(self.base + "/battle/accounts", timeout=3) as response:
            self.assertEqual(response.status, 200)
        with urllib.request.urlopen(self.base + "/battle_accounts.js", timeout=3) as response:
            self.assertEqual(response.status, 200)

    def test_lan_client_gets_host_info_but_not_admin_pages(self) -> None:
        headers = {"X-Forwarded-For": "192.168.1.22"}
        for path in ("/api/health", "/api/host/info", "/battle-login"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with urllib.request.urlopen(request, timeout=3) as response:
                self.assertEqual(response.status, 200)
        for path in ("/battle/accounts", "/battle_accounts.js"):
            request = urllib.request.Request(self.base + path, headers=headers)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(request, timeout=3)
            self.assertEqual(raised.exception.code, 404)
