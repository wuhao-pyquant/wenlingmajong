from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from wenling_lan_host.bug_reports import BugReportStore, json_safe


class BugReportStoreTests(unittest.TestCase):
    def test_latest_cache_survives_restart_and_report_preserves_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "bug_reports"
            snapshot = {
                "captured_at": 123.5,
                "room": {
                    "room_generation": 7,
                    "room_revision": 19,
                },
                "game": {
                    "round_no": 3,
                    "wall": ["m1", "m2"],
                    "players": [
                        {"seat": 0, "hand": Counter({"secret_alice": 2})},
                        {"seat": 1, "hand": Counter({"secret_bob": 1})},
                    ],
                    "history": [{"event": "discard", "tile": "m9"}],
                },
            }
            store = BugReportStore(root, persist_interval_sec=0)
            store.update(snapshot, force_persist=True)
            store.close()

            reopened = BugReportStore(root, persist_interval_sec=0)
            self.assertTrue(reopened.status()["available"])
            self.assertEqual(reopened.status()["round_no"], 3)
            result = reopened.create_report(
                reporter_account="alice",
                note="牌局卡住",
                client_context={"errors": {"one", "two"}},
            )
            reopened.close()

            with gzip.open(root / result["file_name"], "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertEqual(payload["reporter_account"], "alice")
            self.assertEqual(payload["note"], "牌局卡住")
            self.assertEqual(payload["cached_round"]["game"]["wall"], ["m1", "m2"])
            self.assertEqual(
                payload["cached_round"]["game"]["players"][1]["hand"]["secret_bob"],
                1,
            )

    def test_client_context_is_bounded_and_json_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = BugReportStore(Path(temp_dir), persist_interval_sec=0)
            store.update(
                {
                    "captured_at": 1,
                    "room": {},
                    "game": {"round_no": 1},
                },
                force_persist=True,
            )
            result = store.create_report(
                reporter_account="alice",
                client_context={"oversized": "x" * (80 * 1024)},
            )
            store.close()

            with gzip.open(Path(temp_dir) / result["file_name"], "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            self.assertTrue(payload["client_context"]["truncated"])
            self.assertGreater(payload["client_context"]["original_bytes"], 64 * 1024)

    def test_json_safe_handles_diagnostic_container_types(self) -> None:
        payload = json_safe(
            {
                "counts": Counter({"m1": 2}),
                "tiles": {"m2", "m1"},
                "path": Path("logs/report"),
            }
        )
        self.assertEqual(payload["counts"], {"m1": 2})
        self.assertEqual(payload["tiles"], ["m1", "m2"])
        self.assertEqual(payload["path"], str(Path("logs/report")))


if __name__ == "__main__":
    unittest.main()

