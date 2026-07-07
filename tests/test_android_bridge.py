from __future__ import annotations

import socket
import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.android_bridge import AndroidHostBridge


ROOT = Path(__file__).resolve().parents[1]


class AndroidHostBridgeTests(unittest.TestCase):
    @staticmethod
    def free_port() -> int:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])

    def test_offline_account_management_and_room_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bridge = AndroidHostBridge()
            bridge.configure(temp_dir, str(ROOT / "static"), self.free_port())
            bridge.account_command("create", {"account": "alice"})
            bridge.account_command("create", {"account": "alice-old"})
            bridge.account_command("disable", {"account": "alice-old"})
            rows = {row["account"]: row for row in bridge.accounts()["accounts"]}
            self.assertFalse(rows["alice-old"]["enabled"])
            bridge.account_command("enable", {"account": "alice-old"})

            status = bridge.start()
            self.assertTrue(status["running"])
            with self.assertRaisesRegex(ValueError, "房间运行中"):
                bridge.account_command("delete", {"account": "alice-old"})
            generation = status["room_generation"]
            room = bridge.room_command(
                "set_seat",
                {"account": "alice", "seat": 2, "room_generation": generation},
            )
            self.assertEqual(room["seats"][2]["account"], "alice")
            status = bridge.status()
            self.assertEqual(status["seats"][2]["account"], "alice")
            self.assertNotIn("players", status)
            stopped = bridge.stop()
            self.assertFalse(stopped["running"])

            result = bridge.account_command(
                "merge",
                {"sources": ["alice-old"], "target": "alice"},
            )
            self.assertEqual(result["deleted_sources"], ["alice-old"])
            self.assertTrue(Path(result["backup"]).is_file())


if __name__ == "__main__":
    unittest.main()
