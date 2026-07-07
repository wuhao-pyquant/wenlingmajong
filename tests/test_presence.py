from __future__ import annotations

import unittest

from wenling_lan_host.presence import PresenceTracker


class PresenceTrackerTests(unittest.TestCase):
    def test_tracks_logged_in_and_guest_visitors_without_private_state(self) -> None:
        tracker = PresenceTracker(online_sec=30.0)

        tracker.touch(
            "guest-1",
            account=None,
            role=None,
            page="/battle-login",
            room_id=None,
            seat=None,
            ip="203.0.113.5",
            user_agent="GuestBrowser",
        )
        tracker.touch(
            "token-1",
            account="alice",
            role="player",
            page="/battle",
            room_id="R001",
            seat=2,
            ip="203.0.113.6",
            user_agent="PlayerBrowser",
        )

        snapshot = tracker.snapshot()
        self.assertEqual(snapshot["online_count"], 2)
        self.assertEqual(snapshot["logged_in_count"], 1)
        rows = {row["visitor_id"]: row for row in snapshot["visitors"]}
        self.assertIsNone(rows["guest-1"]["account"])
        self.assertEqual(rows["token-1"]["account"], "alice")
        self.assertEqual(rows["token-1"]["room_id"], "R001")
        self.assertNotIn("hand", str(snapshot).lower())

    def test_stale_visitors_are_not_online(self) -> None:
        tracker = PresenceTracker(online_sec=5.0)
        tracker.touch(
            "old",
            account="alice",
            role="player",
            page="/lobby",
            room_id=None,
            seat=None,
            ip="127.0.0.1",
            user_agent="Test",
        )
        old_seen = tracker._visitors["old"]["last_seen_at"]
        snapshot = tracker.snapshot(now=old_seen + 10.0)

        self.assertEqual(snapshot["online_count"], 0)
        self.assertEqual(snapshot["visitors"], [])


if __name__ == "__main__":
    unittest.main()
