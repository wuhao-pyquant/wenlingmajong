import json
import threading
import time
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from wenling_lan_host.battle_db import BattleDatabase
from wenling_lan_host.battle_app import BattleSession, LowLatencyPolicyModel


class FakeBattleDb:
    def normalize_account(self, account):
        return str(account or "").strip()

    def info(self):
        return {"path": ":memory:"}

    def stats_for_accounts(self, accounts):
        return [{"account": account, "all": {}, "today": {}} for account in accounts]


class PassPolicy:
    def choose_action(self, observation, legal_actions, explore=0.0):
        return next((action for action in legal_actions if action.get("type") == "pass"), legal_actions[0])

    def explain_decision(self, observation, chosen, legal_actions):
        return {"score": 100, "chosen": str(chosen), "best": str(chosen), "reason": "test"}


class DiscardPolicy:
    def __init__(self, tile: str = "m1"):
        self.tile = tile

    def choose_action(self, observation, legal_actions, explore=0.0):
        return next(
            (
                action
                for action in legal_actions
                if action.get("type") == "discard" and action.get("tile") == self.tile
            ),
            next((action for action in legal_actions if action.get("type") == "discard"), legal_actions[0]),
        )


class FakeGame:
    def __init__(self):
        self.human_seat = None
        self.round_no = 1
        self.phase = "turn"
        self.current_player = 3
        self.winner = None
        self.wall = ["m9"] * 50
        self.pending = {
            "kind": "response_poll",
            "response_kind": "discard",
            "from": 1,
            "tile": "m1",
            "responders": [2, 3],
            "current_responder": 3,
            "ai_candidates": [2],
            "poll_index": 1,
        }
        self.applied_actions = []
        self.history = [{"event": "discard", "seat": 1, "tile": "m1"}]
        self.bao_liabilities_payload = []
        self.temporary_bao_payload = None

    def serialize(self, viewer_seat=None):
        active_human_seat = self.human_seat if viewer_seat is None else viewer_seat
        players = []
        names = ["AI1", "alice", "AI2", "bob"]
        for seat, name in enumerate(names):
            show = seat == active_human_seat
            players.append(
                {
                    "seat": seat,
                    "name": name,
                    "wind": ["东", "南", "西", "北"][seat],
                    "is_human": show,
                    "hand": {"m1": 2, "m2": 1} if show else {},
                    "hand_count": 3,
                    "flowers": [],
                    "flower_count": 0,
                    "melds": [{"type": "peng", "from": (seat + 1) % 4, "tile": "b1", "tiles": ["b1"] * 3}],
                    "discards": ["m1"],
                    "chips": seat * 10,
                }
            )
        return {
            "round_no": 1,
            "phase": self.phase,
            "pending": dict(self.pending) if self.pending else None,
            "dealer": 1,
            "next_dealer": 2,
            "current_player": 3,
            "wall_remaining": 50,
            "de_indicator": "m9",
            "de_set": ["m9"],
            "flower_set": ["rh1"],
            "players": players,
            "legal_actions": [{"type": "discard", "tile": "m1"}] if active_human_seat == 3 else [],
            "history": list(self.history),
            "bao_liabilities": list(self.bao_liabilities_payload),
            "temporary_bao": dict(self.temporary_bao_payload) if self.temporary_bao_payload else None,
            "winner": None,
            "win_type": "",
            "settlement": None,
            "analysis": [],
            "player_stats": [],
        }

    def apply_human_action(self, action):
        self.applied_actions.append((self.human_seat, dict(action)))
        self.history.append({"event": "human_action", "seat": self.human_seat, "action": dict(action)})
        self.pending = None
        return self.serialize()

    def apply_human_action_for_seat(self, seat, action):
        self.human_seat = seat
        return self.apply_human_action(action)


def fake_session():
    session = BattleSession.__new__(BattleSession)
    session.db = FakeBattleDb()
    session.log_dir = ""
    session.model_factory = None
    session.analysis_model_factory = None
    session.ai_policy = "tile_efficiency"
    session.lock = threading.RLock()
    session.seats = [None, "alice", None, "bob"]
    session.ready = set()
    session.game = FakeGame()
    session.revision = 7
    session.condition = threading.Condition(session.lock)
    session.last_seen = {}
    session._last_online_accounts = set()
    session._last_presence_sweep = 0.0
    session._synchronous_room_events = True
    return session


def real_session(temp_dir: str) -> BattleSession:
    session = BattleSession.__new__(BattleSession)
    session.db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
    session.log_dir = temp_dir
    session.model_factory = lambda policy=None: PassPolicy()
    session.analysis_model_factory = lambda: PassPolicy()
    session.ai_policy = "tile_efficiency"
    session.lock = threading.RLock()
    session.seats = [None, None, None, None]
    session.ready = set()
    session.game = None
    session.account_chips = {}
    session.revision = 0
    session.condition = threading.Condition(session.lock)
    session.last_seen = {}
    session._last_online_accounts = set()
    session._last_presence_sweep = 0.0
    return session


def wait_for(predicate, timeout: float = 2.0, interval: float = 0.02):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    return last


def assert_json_contains_only_allowed_secrets(testcase, payload, allowed: set[str]) -> None:
    raw = json.dumps(payload, ensure_ascii=False)
    for secret in {"secret_alice", "secret_bob", "secret_carol", "secret_ai"} - set(allowed):
        testcase.assertNotIn(secret, raw)
    for secret in allowed:
        testcase.assertIn(secret, raw)


class BattleMultiplayerViewTests(unittest.TestCase):
    def test_low_ai_policy_discards_last_draw_and_legacy_tile_efficiency_maps_to_high(self):
        policy = LowLatencyPolicyModel()
        action = policy.choose_action(
            {"hand": {"m1": 1, "m9": 1}, "last_draw": "m9", "public": {}},
            [{"type": "discard", "tile": "m1"}, {"type": "discard", "tile": "m9"}],
        )

        self.assertEqual(action, {"type": "discard", "tile": "m9"})

        session = fake_session()
        session.set_ai_policy("tile_efficiency")
        self.assertEqual(session.ai_policy, "high")

    def test_default_low_ready_from_joining_player_does_not_downgrade_high_ai_policy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.set_ai_policy("high")
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)

            session.ready_account("alice", "high")
            session.ready_account("bob", "low")
            payload = session.ready_account("carol", "low")

            self.assertEqual(session.ai_policy, "high")
            self.assertEqual(payload["runtime"]["ai_policy"], "high")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            self.assertFalse(payload["runtime"]["low_latency_ai"])

    def test_low_ai_policy_keeps_other_human_response_window_open(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)

            session.ready_account("alice", "low")
            session.ready_account("bob", "low")
            session.ready_account("carol", "low")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            self.assertTrue(game.defer_ai_responses)

            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.current_player = 0
            game.pending = None
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m3": 1})
            game.players[1].hand = Counter({"m2": 2, "m4": 1})
            game.players[2].hand = Counter({"m2": 2, "m5": 1})
            game.players[3].hand = Counter({"t1": 1})

            game._open_discard_response(0, "m2")

            self.assertIsNotNone(game.pending)
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertEqual(game.pending["human_responders"], [1, 2])
            bob = session.state("bob")
            carol = session.state("carol")
            self.assertTrue(any(action.get("type") == "peng" for action in bob["legal_actions"]))
            self.assertTrue(any(action.get("type") == "peng" for action in carol["legal_actions"]))

    def test_three_human_one_ai_real_session_starts_private_rotated_game(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)

            session.ready_account("alice")
            session.ready_account("bob")
            payload = session.ready_account("carol")

            self.assertTrue(payload["game_started"])
            self.assertIsNotNone(session.game)
            self.assertEqual(session._effective_accounts(), ["alice", "bob", "carol", "AI1"])
            self.assertEqual(session.game.human_seats, {0, 1, 2})
            self.assertEqual(session.game.response_delay_sec, 0.0)
            self.assertEqual([player.name for player in session.game.players], ["alice", "bob", "carol", "AI1"])

            session.game.phase = "turn"
            session.game.winner = None
            session.game.pending = None
            session.game.current_player = 1
            session.game.de_indicator = "bai"
            session.game.de_set = {"bai"}
            session.game.flower_set = set()
            for index, player in enumerate(session.game.players):
                player.hand = Counter({f"m{index + 1}": 2})

            alice = session.state("alice")
            bob = session.state("bob")
            carol = session.state("carol")

            self.assertEqual(alice["players"][0]["account"], "alice")
            self.assertEqual(bob["players"][0]["account"], "bob")
            self.assertEqual(carol["players"][0]["account"], "carol")
            self.assertTrue(alice["players"][0]["hand"])
            self.assertTrue(bob["players"][0]["hand"])
            self.assertTrue(carol["players"][0]["hand"])
            self.assertEqual(alice["players"][1]["hand"], {})
            self.assertEqual(bob["players"][1]["hand"], {})
            self.assertEqual(carol["players"][1]["hand"], {})
            self.assertTrue(bob["legal_actions"])
            self.assertEqual(alice["legal_actions"], [])
            self.assertIsInstance(bob.get("action_token"), str)

            before_history = len(session.game.history)
            session._step_locked()
            self.assertEqual(session.game.current_player, 1)
            self.assertIsNone(session.game.pending)
            self.assertEqual(len(session.game.history), before_history)

    def test_ai_discard_broadcast_advances_without_artificial_pause(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.model_factory = lambda policy=None: DiscardPolicy("m1")
            session.analysis_model_factory = lambda: PassPolicy()
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            game = session.game
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.winner = None
            game.win_type = ""
            game.settlement = None
            game.pending = None
            game.current_player = 1
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m2": 2, "m3": 2, "m4": 2})
            game.players[1].hand = Counter({"m1": 1, "m2": 1, "m3": 1, "m4": 1, "m5": 1})
            game.players[2].hand = Counter({"b1": 1, "b2": 1, "b3": 1})
            game.players[3].hand = Counter({"t1": 1, "t2": 1, "t3": 1})

            with session.lock:
                session._step_locked()
            self.assertEqual(game.pending["kind"], "ai_turn")
            self.assertEqual(game.pending["from"], 1)

            game.pending["deadline"] = time.time() - 0.01
            with session.lock:
                session._step_locked()

            if game.pending:
                self.assertNotEqual(game.pending["kind"], "post_action_pause")
            alice = wait_for(
                lambda: session.state("alice")
                if any(entry.get("event") == "discard" and entry.get("tile") == "m1" for entry in session.state("alice")["history"])
                else None
            )
            self.assertIsNotNone(alice)
            if alice["pending"]:
                self.assertNotEqual(alice["pending"]["kind"], "post_action_pause")
            self.assertTrue(any(entry.get("event") == "discard" and entry.get("tile") == "m1" for entry in alice["history"]))

    def test_discarder_cannot_see_other_human_hand_during_claim_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1)]:
                session.register(account)
                session.sit(account, seat)
            session.ready_account("alice")
            session.ready_account("bob")
            self.assertIsNotNone(session.game)
            game = session.game
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.current_player = 0
            game.pending = None
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m1": 2, "m3": 2})
            game.players[1].hand = Counter({"m2": 2, "m4": 1})

            game._open_discard_response(0, "m2")
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertIsNone(game.pending["current_responder"])
            self.assertIn(1, game.pending["responders"])
            self.assertIn("source_event_id", game.pending)
            self.assertIn("created_at", game.pending)
            self.assertEqual(game.pending["source_seat"], 0)
            self.assertIn(1, game.pending["candidates"])
            self.assertEqual(game.pending["decisions_by_seat"], {})

            alice = session.state("alice")
            bob = session.state("bob")

            self.assertEqual(alice["players"][0]["account"], "alice")
            self.assertEqual(alice["players"][1]["account"], "bob")
            self.assertEqual(alice["players"][1]["hand"], {})
            self.assertEqual(alice["players"][1]["hand_count"], 3)
            self.assertNotIn("candidates", alice["pending"])
            self.assertNotIn("legal_by_seat", alice["pending"])
            self.assertEqual(bob["players"][0]["account"], "bob")
            self.assertEqual(bob["players"][0]["hand"], {"m2": 2, "m4": 1})

    def test_multiple_human_claims_are_collected_before_priority_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)
            session.ready_account("alice")
            session.ready_account("bob")
            session.ready_account("carol")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.current_player = 0
            game.pending = None
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m3": 1})
            game.players[1].hand = Counter({"m2": 2, "m4": 1})
            game.players[2].hand = Counter({"m2": 2, "m5": 1})
            game.players[3].hand = Counter({"t1": 1})

            game._open_discard_response(0, "m2")
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertIsNone(game.pending.get("current_responder"))

            bob = session.state("bob")
            carol = session.state("carol")
            self.assertTrue(any(action.get("type") == "peng" for action in bob["legal_actions"]))
            self.assertTrue(any(action.get("type") == "peng" for action in carol["legal_actions"]))
            self.assertNotIn("current_responder", bob["pending"])
            self.assertEqual(bob["pending"]["absolute_responders"], [1, 2])
            self.assertEqual(bob["pending"]["absolute_waiting_for_seats"], [1, 2])
            self.assertEqual(bob["pending"]["absolute_decision_seats"], [])
            self.assertEqual(bob["pending"]["room_generation"], bob["room_generation"])

            carol_after = session.action(
                "carol",
                {"type": "peng", "tile": "m2"},
                action_token=carol["action_token"],
                room_generation=carol["room_generation"],
                pending_id=carol["pending_id"],
            )
            self.assertEqual(carol_after["pending"]["kind"], "response_poll")
            self.assertEqual(carol_after["legal_actions"], [])
            self.assertEqual(carol_after["pending"]["absolute_decision_seats"], [2])
            self.assertEqual(carol_after["pending"]["absolute_waiting_for_seats"], [1])
            self.assertIn(2, game.pending["decisions_by_seat"])

            bob_after_carol = session.state("bob")
            self.assertTrue(any(action.get("type") == "peng" for action in bob_after_carol["legal_actions"]))
            self.assertEqual(bob_after_carol["pending"]["absolute_decision_seats"], [2])
            self.assertEqual(bob_after_carol["pending"]["absolute_waiting_for_seats"], [1])

            bob_after = session.action(
                "bob",
                {"type": "peng", "tile": "m2"},
                action_token=bob["action_token"],
                room_generation=bob["room_generation"],
                pending_id=bob["pending_id"],
            )
            self.assertIsNone(game.pending)
            self.assertEqual(game.current_player, 1)
            self.assertTrue(any(meld.get("type") == "peng" and meld.get("tiles") == ["m2", "m2", "m2"] for meld in game.players[1].melds))
            self.assertEqual(bob_after["players"][0]["account"], "bob")

    def test_spectator_state_never_uses_current_responder_private_hand(self):
        session = fake_session()
        session.game.human_seat = 3

        spectator = session.state(None)

        self.assertIsNone(spectator.get("account"))
        self.assertEqual(spectator["legal_actions"], [])
        self.assertTrue(all(player["hand"] == {} for player in spectator["players"]))

    def test_serialize_for_account_is_the_single_private_snapshot_exit(self):
        session = fake_session()

        via_state = session.state("bob")
        via_exit = session.serialize_for_account("bob")

        self.assertEqual(via_state["account"], via_exit["account"])
        self.assertEqual(via_state["viewer_absolute_seat"], via_exit["viewer_absolute_seat"])
        self.assertEqual(via_state["players"][0]["hand"], via_exit["players"][0]["hand"])
        self.assertEqual(via_state["players"][2]["hand"], via_exit["players"][2]["hand"])
        self.assertEqual(via_state["legal_actions"], via_exit["legal_actions"])

    def test_bao_status_seats_rotate_with_viewer(self):
        session = fake_session()
        session.game.temporary_bao_payload = {
            "seat": 1,
            "reason": "temporary",
            "source_event_id": "d1",
        }
        session.game.bao_liabilities_payload = [
            {
                "seq": 1,
                "liable_seat": 3,
                "target_winner": 1,
                "reason": "permanent",
                "source_event_id": "d2",
                "active": True,
            }
        ]

        bob = session.state("bob")

        self.assertEqual(bob["viewer_absolute_seat"], 3)
        self.assertEqual(bob["temporary_bao"]["seat"], 2)
        self.assertEqual(bob["temporary_bao"]["absolute_seat"], 1)
        self.assertEqual(bob["bao_liabilities"][0]["liable_seat"], 0)
        self.assertEqual(bob["bao_liabilities"][0]["absolute_liable_seat"], 3)
        self.assertEqual(bob["bao_liabilities"][0]["target_winner"], 2)
        self.assertEqual(bob["bao_liabilities"][0]["absolute_target_winner"], 1)

    def test_room_round_count_survives_reseat_reset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)

            first = session.ready_account("alice")
            self.assertEqual(first["room_round_count"], 1)
            self.assertIsNotNone(session.game)
            session.game.phase = "round_over"

            second = session.ready_account("alice")
            self.assertEqual(second["room_round_count"], 2)
            session.game.phase = "round_over"

            reset = session.reset_match("alice")
            self.assertFalse(reset["game_started"])
            self.assertEqual(reset["room_round_count"], 2)

            session.sit("alice", 0, room_generation=reset["room_generation"])
            third = session.ready_account("alice")
            self.assertEqual(third["room_round_count"], 3)

    def test_response_waiting_snapshots_do_not_leak_candidate_private_hands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)
            session.ready_account("alice")
            session.ready_account("bob")
            session.ready_account("carol")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.current_player = 0
            game.pending = None
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m3": 1})
            game.players[1].hand = Counter({"m2": 2, "secret_bob": 1})
            game.players[2].hand = Counter({"m2": 2, "secret_carol": 1})
            game.players[3].hand = Counter({"t1": 1})

            game._open_discard_response(0, "m2")

            alice_json = json.dumps(session.serialize_for_account("alice"), ensure_ascii=False)
            spectator_json = json.dumps(session.serialize_for_account(None), ensure_ascii=False)
            bob_json = json.dumps(session.serialize_for_account("bob"), ensure_ascii=False)
            carol_json = json.dumps(session.serialize_for_account("carol"), ensure_ascii=False)

            self.assertNotIn("secret_bob", alice_json)
            self.assertNotIn("secret_carol", alice_json)
            self.assertNotIn("secret_bob", spectator_json)
            self.assertNotIn("secret_carol", spectator_json)
            self.assertIn("secret_bob", bob_json)
            self.assertNotIn("secret_carol", bob_json)
            self.assertIn("secret_carol", carol_json)
            self.assertNotIn("secret_bob", carol_json)

    def test_action_return_keeps_discarder_view_during_other_human_claim_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.register("bob")
            session.sit("alice", 0)
            session.sit("bob", 1)
            session.ready_account("alice")
            session.ready_account("bob")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.phase = "turn"
            game.pending = None
            game.current_player = 0
            game.wall = ["m9"] * 50
            game.players[0].hand = Counter({"m2": 1, "m5": 1})
            game.players[1].hand = Counter({"m2": 2, "m4": 1})
            game.players[2].hand = Counter({"t1": 1})
            game.players[3].hand = Counter({"b1": 1})

            before = session.state("alice")
            payload = session.action(
                "alice",
                {"type": "discard", "tile": "m2"},
                action_token=before["action_token"],
                room_generation=before["room_generation"],
                pending_id=before["pending_id"],
            )

            self.assertEqual(payload["players"][0]["account"], "alice")
            self.assertEqual(payload["players"][1]["account"], "bob")
            self.assertEqual(payload["players"][1]["hand"], {})
            self.assertEqual(payload["players"][1]["hand_count"], 3)
            self.assertEqual(session.state("bob")["players"][0]["hand"], {"m2": 2, "m4": 1})

    def test_human_leave_during_active_round_reserves_seat_for_reconnect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "turn"

            payload = session.leave("alice")

            self.assertIsNotNone(session.game)
            self.assertEqual(session.seats[0], "alice")
            self.assertEqual(session.ready, set())
            self.assertTrue(payload["game_started"])
            self.assertFalse(payload["seats"][0]["online"])

            session.register("bob")
            with self.assertRaises(ValueError):
                session.sit("bob", 0)

            reconnected = session.sit("alice", 0)
            self.assertTrue(reconnected["game_started"])
            self.assertEqual(reconnected["viewer_absolute_seat"], 0)

    def test_last_human_leave_before_or_after_round_releases_room(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "round_over"

            payload = session.leave("alice")

            self.assertIsNone(session.game)
            self.assertEqual(session.seats, [None, None, None, None])
            self.assertEqual(session.ready, set())
            self.assertFalse(payload["game_started"])
            self.assertIsNone(payload["seats"][0]["account"])

    def test_reset_match_preserves_chips_by_account_when_reseating(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.db.record_opening("alice", opening_shanten=3, de_draws=1, fan_flower_draws=2)
            session.db.record_win("alice", "劣子和", win_turn=7, win_points=120)
            session.db.record_hand_luck("alice", 88.5)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            stats_before = session.db.stats_for_accounts(["alice"])[0]["all"]
            for player, chips in zip(session.game.players, [54, -10, 3, -47]):
                player.chips = chips
            expected = {player.name: player.chips for player in session.game.players}
            session.game.phase = "round_over"

            session.reset_match("alice")
            self.assertIsNone(session.game)
            self.assertEqual(session.account_chips, expected)
            self.assertEqual(session.db.stats_for_accounts(["alice"])[0]["all"], stats_before)

            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            restored = {player.name: player.chips for player in session.game.players}
            settlement = session.game.settlement or {}
            deltas = settlement.get("deltas") or [0, 0, 0, 0]
            expected_after_round_start = {
                player.name: expected[player.name] + int(deltas[seat])
                for seat, player in enumerate(session.game.players)
            }
            self.assertEqual(restored, expected_after_round_start)

    def test_new_player_cannot_sit_during_active_round_but_same_account_can_reconnect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "turn"

            payload = session.sit("alice", 0)
            self.assertTrue(payload["game_started"])
            self.assertEqual(payload["viewer_absolute_seat"], 0)

            session.register("bob")
            with self.assertRaises(ValueError):
                session.sit("bob", 1)

    def test_kick_active_human_keeps_reserved_seat_for_reconnect(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.register("bob")
            session.sit("alice", 0)
            session.sit("bob", 1)
            session.ready_account("alice")
            session.ready_account("bob")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "turn"

            payload = session.kick("alice", "bob")

            self.assertEqual(session.seats[1], "bob")
            self.assertEqual(session.game.players[1].name, "bob")
            self.assertEqual(session.game.players[2].name, "AI1")
            self.assertEqual(session.game.human_seats, {0, 1})
            self.assertEqual(payload["seats"][1]["account"], "bob")
            self.assertFalse(payload["seats"][1]["online"])

            session.register("mallory")
            with self.assertRaises(ValueError):
                session.sit("mallory", 1)
            reconnected = session.sit("bob", 1)
            self.assertEqual(reconnected["players"][0]["account"], "bob")
            self.assertTrue(reconnected["seats"][0]["online"])

    def test_kick_active_human_does_not_leak_private_hands(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            for account, seat in [("alice", 0), ("bob", 1), ("carol", 2)]:
                session.register(account)
                session.sit(account, seat)
            session.ready_account("alice")
            session.ready_account("bob")
            session.ready_account("carol")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            game.phase = "turn"
            game.current_player = 3
            game.players[0].hand = Counter({"secret_alice": 1})
            game.players[1].hand = Counter({"secret_bob": 1})
            game.players[2].hand = Counter({"secret_carol": 1})
            game.players[3].hand = Counter({"secret_ai": 1})

            kick_payload = session.kick("alice", "bob")
            alice_view = session.state("alice")
            bob_view = session.state("bob")
            carol_view = session.state("carol")
            spectator = session.state(None)

            assert_json_contains_only_allowed_secrets(self, kick_payload, {"secret_alice"})
            assert_json_contains_only_allowed_secrets(self, alice_view, {"secret_alice"})
            assert_json_contains_only_allowed_secrets(self, bob_view, {"secret_bob"})
            assert_json_contains_only_allowed_secrets(self, carol_view, {"secret_carol"})
            assert_json_contains_only_allowed_secrets(self, spectator, set())

    def test_new_player_join_after_round_over_resets_old_game_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "round_over"
            session.game.players[1].name = "AI2-old"

            session.register("bob")
            payload = session.sit("bob", 1)

            self.assertIsNone(session.game)
            self.assertFalse(payload["game_started"])
            self.assertEqual(session.seats[0], "alice")
            self.assertEqual(session.seats[1], "bob")
            self.assertEqual(payload["seats"][1]["account"], "bob")
            self.assertEqual(payload["seats"][2]["effective_account"], "AI1")

    def test_new_player_replaces_previous_ai_name_when_next_game_starts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            session.game.phase = "round_over"
            session.game.players[1].name = "stale-ai-name"

            session.register("bob")
            session.sit("bob", 1)
            self.assertIsNone(session.game)
            session.ready_account("alice")
            payload = session.ready_account("bob")

            self.assertTrue(payload["game_started"])
            self.assertIsNotNone(session.game)
            assert session.game is not None
            self.assertEqual([player.name for player in session.game.players], ["alice", "bob", "AI1", "AI2"])

    def test_state_is_rotated_and_private_for_each_human_account(self):
        session = fake_session()

        alice = session.state("alice")
        bob = session.state("bob")

        self.assertEqual(alice["viewer_absolute_seat"], 1)
        self.assertEqual(bob["viewer_absolute_seat"], 3)

        self.assertEqual(alice["players"][0]["name"], "alice")
        self.assertTrue(alice["players"][0]["is_human"])
        self.assertEqual(alice["players"][0]["hand"], {"m1": 2, "m2": 1})
        self.assertEqual(alice["players"][2]["name"], "bob")
        self.assertEqual(alice["players"][2]["hand"], {})

        self.assertEqual(bob["players"][0]["name"], "bob")
        self.assertTrue(bob["players"][0]["is_human"])
        self.assertEqual(bob["players"][0]["hand"], {"m1": 2, "m2": 1})
        self.assertEqual(bob["players"][2]["name"], "alice")
        self.assertEqual(bob["players"][2]["hand"], {})

        self.assertEqual(alice["seats"][0]["account"], "alice")
        self.assertEqual(alice["seats"][0]["absolute_seat"], 1)
        self.assertEqual(alice["seats"][2]["account"], "bob")
        self.assertEqual(alice["seats"][2]["absolute_seat"], 3)
        self.assertEqual(bob["seats"][0]["account"], "bob")
        self.assertEqual(bob["seats"][0]["absolute_seat"], 3)
        self.assertEqual(bob["seats"][2]["account"], "alice")
        self.assertEqual(bob["seats"][2]["absolute_seat"], 1)

        self.assertEqual(alice["dealer"], 0)
        self.assertEqual(alice["current_player"], 2)
        self.assertEqual(bob["dealer"], 2)
        self.assertEqual(bob["current_player"], 0)
        self.assertEqual(bob["legal_actions"], [{"type": "discard", "tile": "m1"}])
        self.assertEqual(alice["legal_actions"], [])

    def test_wait_state_returns_when_room_revision_changes(self):
        session = fake_session()

        def bump_revision():
            time.sleep(0.05)
            with session.lock:
                session._bump_revision()

        worker = threading.Thread(target=bump_revision)
        worker.start()
        started = time.time()
        payload = session.wait_state("alice", since=7, timeout=1.0)
        worker.join(timeout=1.0)

        self.assertEqual(payload["room_revision"], 8)
        self.assertLess(time.time() - started, 0.8)

    def test_wait_timeout_records_processing_bucket_without_false_slow_event(self):
        session = fake_session()
        session.state("alice")
        since = session.revision

        session.wait_state("alice", since=since, timeout=0.25)
        payload = session.state("alice")

        timing = payload["runtime"]["api_timing_buckets"]["wait"]
        self.assertEqual(timing["count"], 1)
        self.assertGreaterEqual(timing["last_elapsed_ms"], 200.0)
        self.assertLess(timing["last_processing_ms"], 200.0)
        self.assertEqual(payload["runtime"]["last_slow_events"], [])

    def test_register_state_and_wait_are_read_only_until_queued_heartbeat(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            self.assertEqual(session.revision, 0)
            self.assertNotIn("alice", session.last_seen)

            first = session.state("alice")
            session.wait_state("alice", since=first["room_revision"], timeout=0.1)
            self.assertEqual(session.revision, 0)
            self.assertNotIn("alice", session.last_seen)

            heartbeat = session.heartbeat("alice", room_generation=first["room_generation"])
            self.assertTrue(heartbeat["presence"]["online"])
            self.assertGreater(session.revision, 0)
            self.assertIn("alice", session.last_seen)

    def test_manual_step_runs_through_room_event_queue(self):
        session = fake_session()
        session._step_locked = lambda: session._bump_revision("manual_step_test")  # type: ignore[method-assign]

        payload = session.step("bob")

        self.assertTrue(
            any(
                event["event_type"] == "manual_step_test"
                and event.get("source_event_type") == "manual_step"
                and isinstance(event.get("source_queue_id"), int)
                for event in payload["runtime"]["last_events"]
            )
        )

    def test_heartbeat_marks_human_seat_online_without_releasing_stale_seat(self):
        session = fake_session()
        session.game = None

        payload = session.heartbeat("alice")
        self.assertTrue(payload["presence"]["online"])

        lobby = session.state("alice")
        alice_seat = next(seat for seat in lobby["seats"] if seat["account"] == "alice")
        bob_seat = next(seat for seat in lobby["seats"] if seat["account"] == "bob")
        ai_seat = next(seat for seat in lobby["seats"] if seat["is_ai"])

        self.assertTrue(alice_seat["online"])
        self.assertFalse(bob_seat["online"])
        self.assertEqual(bob_seat["account"], "bob")
        self.assertTrue(ai_seat["online"])

        session.last_seen["alice"] = time.time() - 120
        stale = session.state("bob")
        stale_alice = next(seat for seat in stale["seats"] if seat["account"] == "alice")
        self.assertFalse(stale_alice["online"])
        self.assertEqual(stale_alice["account"], "alice")

    def test_action_token_rejects_stale_multiplayer_action(self):
        session = fake_session()
        current = session.state("bob")
        token = current["action_token"]

        session.game.pending["current_responder"] = 2

        with self.assertRaises(ValueError):
            session.action(
                "bob",
                {"type": "discard", "tile": "m1"},
                action_token=token,
                room_generation=current["room_generation"],
                pending_id=current["pending_id"],
            )
        self.assertEqual(session.game.applied_actions, [])

    def test_action_token_is_required_for_multiplayer_action(self):
        session = fake_session()

        with self.assertRaises(ValueError):
            session.action("bob", {"type": "discard", "tile": "m1"})
        self.assertEqual(session.game.applied_actions, [])

    def test_action_token_allows_current_multiplayer_action(self):
        session = fake_session()
        current = session.state("bob")

        payload = session.action(
            "bob",
            {"type": "discard", "tile": "m1"},
            action_token=current["action_token"],
            room_generation=current["room_generation"],
            pending_id=current["pending_id"],
        )

        self.assertEqual(session.game.applied_actions, [(3, {"type": "discard", "tile": "m1"})])
        self.assertEqual(payload["room_revision"], 9)
        self.assertTrue(
            any(
                event["event_type"] == "player_action"
                and event.get("source_event_type") == "player_action"
                and isinstance(event.get("source_queue_id"), int)
                and "source_elapsed_ms" in event
                for event in payload["runtime"]["last_events"]
            )
        )

    def test_action_requires_current_room_generation(self):
        session = fake_session()
        current = session.state("bob")

        with self.assertRaises(ValueError):
            session.action(
                "bob",
                {"type": "discard", "tile": "m1"},
                action_token=current["action_token"],
                pending_id=current["pending_id"],
            )
        with self.assertRaises(ValueError):
            session.action(
                "bob",
                {"type": "discard", "tile": "m1"},
                action_token=current["action_token"],
                room_generation=current["room_generation"] + 1,
                pending_id=current["pending_id"],
            )
        self.assertEqual(session.game.applied_actions, [])

    def test_action_rejects_stale_pending_id_even_with_current_token(self):
        session = fake_session()
        current = session.state("bob")

        with self.assertRaises(ValueError):
            session.action(
                "bob",
                {"type": "discard", "tile": "m1"},
                action_token=current["action_token"],
                room_generation=current["room_generation"],
                pending_id="stale-pending",
            )
        self.assertEqual(session.game.applied_actions, [])

    def test_action_token_includes_room_generation(self):
        session = fake_session()
        current = session.state("bob")
        token = current["action_token"]
        self.assertEqual(current["room_generation"], 1)

        with session.lock:
            session._new_room_generation_locked("test")

        refreshed = session.state("bob")
        self.assertEqual(refreshed["room_generation"], 2)
        self.assertNotEqual(refreshed["action_token"], token)
        with self.assertRaises(ValueError):
            session.action(
                "bob",
                {"type": "discard", "tile": "m1"},
                action_token=token,
                room_generation=current["room_generation"],
                pending_id=current["pending_id"],
            )
        self.assertEqual(session.game.applied_actions, [])

    def test_heartbeat_does_not_invalidate_current_action_token(self):
        session = fake_session()
        current = session.state("bob")
        token = current["action_token"]

        session.heartbeat("alice")
        refreshed = session.state("bob")

        self.assertEqual(refreshed["action_token"], token)

    def test_reset_match_increments_room_generation_and_event_seq(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            lobby_generation = session.state("alice")["room_generation"]
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            active_generation = session.state("alice")["room_generation"]
            self.assertGreater(active_generation, lobby_generation)
            session.game.phase = "round_over"

            payload = session.reset_match("alice")

            self.assertFalse(payload["game_started"])
            self.assertGreater(payload["room_generation"], active_generation)
            self.assertGreaterEqual(payload["event_seq"], payload["room_revision"])
            self.assertTrue(
                any(
                    event["event_type"] == "reset_match"
                    and event.get("source_event_type") == "reset"
                    and isinstance(event.get("source_queue_id"), int)
                    and "source_elapsed_ms" in event
                    for event in payload["runtime"]["last_events"]
                )
            )

    def test_lobby_write_events_include_source_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            sit_payload = session.sit("alice", 0)
            self.assertTrue(
                any(
                    event["event_type"] == "sit"
                    and event.get("source_event_type") == "sit"
                    and isinstance(event.get("source_queue_id"), int)
                    and "source_elapsed_ms" in event
                    for event in sit_payload["runtime"]["last_events"]
                )
            )
            self.assertIn("room_event_queue_length", sit_payload["runtime"])
            self.assertIn("processing_room_event", sit_payload["runtime"])

            session.register("bob")
            session.sit("bob", 1)
            ready_payload = session.ready_account("alice")
            self.assertTrue(
                any(
                    event["event_type"] == "ready"
                    and event.get("source_event_type") == "ready"
                    and isinstance(event.get("source_queue_id"), int)
                    and "source_elapsed_ms" in event
                    for event in ready_payload["runtime"]["last_events"]
                )
            )

            kick_payload = session.kick("alice", "bob")
            self.assertTrue(
                any(
                    event["event_type"] == "kick"
                    and event.get("source_event_type") == "kick"
                    and isinstance(event.get("source_queue_id"), int)
                    and "source_elapsed_ms" in event
                    for event in kick_payload["runtime"]["last_events"]
                )
            )

            leave_payload = session.leave("alice")
            self.assertTrue(
                any(
                    event["event_type"] == "leave"
                    and event.get("source_event_type") == "leave"
                    and isinstance(event.get("source_queue_id"), int)
                    and "source_elapsed_ms" in event
                    for event in leave_payload["runtime"]["last_events"]
                )
            )

    def test_room_write_events_are_processed_by_fifo_worker(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session._synchronous_room_events = False
            try:
                release_first = threading.Event()
                first_started = threading.Event()
                execution_order = []
                results = {}

                def submit(label, release=None):
                    def handler(_started_at):
                        first_started.set()
                        if release is not None:
                            release.wait(timeout=2.0)
                        execution_order.append(label)
                        with session.lock:
                            session._bump_revision(f"queued_{label}", {"label": label})
                        return {"label": label}

                    results[label] = session._run_room_event(
                        f"queued_{label}",
                        f"test_{label}",
                        handler,
                        {"label": label},
                    )

                first = threading.Thread(target=submit, args=("first", release_first))
                second = threading.Thread(target=submit, args=("second",))
                first.start()
                self.assertTrue(first_started.wait(timeout=2.0))
                second.start()
                time.sleep(0.05)
                self.assertEqual(execution_order, [])
                with session.lock:
                    self.assertGreaterEqual(len(session._room_event_queue), 1)
                    self.assertTrue(session._processing_room_event)
                release_first.set()
                first.join(timeout=2.0)
                second.join(timeout=2.0)

                self.assertFalse(first.is_alive())
                self.assertFalse(second.is_alive())
                self.assertEqual(execution_order, ["first", "second"])
                self.assertEqual(results["first"], {"label": "first"})
                self.assertEqual(results["second"], {"label": "second"})
                payload = session.state("alice")
                queued_events = [
                    event
                    for event in payload["runtime"]["last_events"]
                    if event["event_type"] in {"queued_first", "queued_second"}
                ]
                self.assertEqual([event["event_type"] for event in queued_events[-2:]], ["queued_first", "queued_second"])
                self.assertTrue(all(isinstance(event.get("source_queue_id"), int) for event in queued_events[-2:]))
            finally:
                session.close()

    def test_battle_session_close_stops_worker_and_rejects_new_events(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session._synchronous_room_events = False
            with session.condition:
                session._ensure_runtime_fields_locked()
                worker = session._room_worker
            self.assertTrue(worker.is_alive())

            session.close()

            self.assertTrue(session._closed)
            self.assertFalse(worker.is_alive())
            with self.assertRaisesRegex(RuntimeError, "closed"):
                session._run_room_event("closed_test", "closed_test", lambda _started_at: {"ok": True})

    def test_new_room_generation_cancels_stale_ai_results(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None

            game._ai_response_token = 10
            stale_token = game._ai_response_token
            game.pending = {
                "kind": "ai_turn",
                "from": 1,
                "deferred": True,
                "ai_thinking": True,
                "ai_think_token": stale_token,
                "ai_precomputed_action": None,
            }

            with session.lock:
                session._new_room_generation_locked("test_reset")

            self.assertIsNone(game.pending)
            self.assertGreater(game._ai_response_token, stale_token)

            game.pending = {
                "kind": "ai_turn",
                "from": 1,
                "deferred": True,
                "ai_thinking": True,
                "ai_think_token": game._ai_response_token,
                "ai_precomputed_action": None,
            }
            game._queue_ai_result({
                "kind": "ai_turn",
                "seat": 1,
                "token": stale_token,
                "action": {"type": "discard", "tile": "m1"},
                "observation": {},
                "legal_actions": [{"type": "discard", "tile": "m1"}],
            })

            game._drain_ai_results()

            self.assertIsNone(game.pending["ai_precomputed_action"])
            self.assertTrue(game.pending["ai_thinking"])

    def test_stale_ai_result_event_cannot_update_current_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            with session.lock:
                game.phase = "turn"
                game.current_player = 1
                game.pending = {
                    "kind": "ai_turn",
                    "from": 1,
                    "tile": "",
                    "human_actions": [],
                    "ai_candidates": [1],
                    "deferred": True,
                    "deadline": time.time() - 1.0,
                    "ai_thinking": True,
                    "ai_think_token": 77,
                    "ai_precomputed_action": None,
                    "ai_precomputed_observation": {},
                    "ai_precomputed_legal_actions": [{"type": "discard", "tile": "m1"}],
                }
                pending_id = session._current_pending_id_locked()
                action_token = session._action_token_for(1)
                before = session._game_signature()
                result = session._apply_ai_result_event({
                    "kind": "ai_turn",
                    "seat": 1,
                    "token": 77,
                    "action": {"type": "discard", "tile": "m1"},
                    "observation": {},
                    "legal_actions": [{"type": "discard", "tile": "m1"}],
                    "room_generation": session.room_generation - 1,
                    "pending_id": pending_id,
                    "action_token": action_token,
                })

            self.assertFalse(result["accepted"])
            self.assertEqual(result["reason"], "stale_generation")
            self.assertEqual(session._game_signature(), before)
            self.assertIsNone(game.pending["ai_precomputed_action"])
            self.assertTrue(game.pending["ai_thinking"])

    def test_ai_turn_timeout_uses_fallback_and_unblocks_room(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            try:
                session.register("alice")
                session.sit("alice", 0)
                session.ready_account("alice")
                self.assertIsNotNone(session.game)
                game = session.game
                assert game is not None
                with session.lock:
                    game.ai_decision_timeout_sec = 0.01
                    game.de_indicator = "bai"
                    game.de_set = {"bai"}
                    game.flower_set = set()
                    game.phase = "turn"
                    game.winner = None
                    game.win_type = ""
                    game.settlement = None
                    game.current_player = 1
                    game.wall = ["m9"] * 20
                    game.players[1].hand = Counter({"m1": 1, "m2": 1})
                    game.pending = {
                        "kind": "ai_turn",
                        "from": 1,
                        "tile": "",
                        "human_actions": [],
                        "ai_candidates": [1],
                        "deferred": True,
                        "deadline": time.time() - 1.0,
                        "ai_thinking": True,
                        "ai_started_at": time.time() - 1.0,
                        "ai_think_token": 101,
                        "ai_precomputed_action": None,
                        "ai_precomputed_observation": {},
                        "ai_precomputed_legal_actions": [{"type": "discard", "tile": "m1"}],
                    }
                    game.resolve_deferred_pending(force=False)

                self.assertNotEqual(game.pending["kind"] if game.pending else None, "ai_turn")
                self.assertTrue(any(entry.get("event") == "ai_timeout" for entry in game.history))
                self.assertTrue(any(entry.get("event") == "discard" and entry.get("tile") == "m1" for entry in game.history))
            finally:
                session.close()

    def test_ai_response_timeout_passes_without_closing_human_response(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.register("bob")
            session.sit("alice", 0)
            session.sit("bob", 1)
            session.ready_account("alice")
            session.ready_account("bob")
            self.assertIsNotNone(session.game)
            game = session.game
            assert game is not None
            with session.lock:
                game.ai_decision_timeout_sec = 0.01
                game.phase = "turn"
                game.current_player = 0
                game.de_indicator = "bai"
                game.de_set = {"bai"}
                game.flower_set = set()
                game.pending = {
                    "kind": "response_poll",
                    "response_kind": "discard",
                    "from": 0,
                    "tile": "m1",
                    "responders": [1, 2],
                    "order_index_by_seat": {1: 0, 2: 1},
                    "legal_by_seat": {
                        1: [{"type": "peng", "tile": "m1"}, {"type": "pass"}],
                        2: [{"type": "peng", "tile": "m1"}, {"type": "pass"}],
                    },
                    "responses": [],
                    "decisions_by_seat": {},
                    "human_responders": [1],
                    "human_actions": [{"type": "peng", "tile": "m1"}, {"type": "pass"}],
                    "ai_candidates": [2],
                    "ai_thinking_by_seat": {2: True},
                    "ai_started_at_by_seat": {2: time.time() - 1.0},
                    "ai_precomputed_actions": {},
                    "ai_precomputed_observations": {},
                    "ai_precomputed_legal_actions": {},
                    "deferred": True,
                    "deadline": None,
                }
                game.resolve_deferred_pending(force=False)

            self.assertIsNotNone(game.pending)
            self.assertEqual(game.pending["decisions_by_seat"].get(2), {"type": "pass"})
            self.assertNotIn(1, game.pending["decisions_by_seat"])
            self.assertTrue(any(entry.get("event") == "ai_timeout" for entry in game.history))

    def test_repeated_reset_does_not_leave_stale_pending(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            session.register("alice")
            session.sit("alice", 0)
            session.ready_account("alice")
            self.assertIsNotNone(session.game)
            assert session.game is not None
            start_generation = session.room_generation

            for index in range(10):
                session.game.pending = {
                    "kind": "response_poll",
                    "from": 1,
                    "tile": "m1",
                    "responders": [0],
                    "decisions_by_seat": {},
                    "ai_thinking_by_seat": {2: True},
                }
                with session.lock:
                    session._new_room_generation_locked(f"rapid_reset_{index}")

            self.assertGreaterEqual(session.room_generation, start_generation + 10)
            self.assertIsNone(session.game.pending)
            self.assertTrue(
                any(
                    event["event_type"] == "room_generation"
                    and event.get("details", {}).get("reason") == "rapid_reset_9"
                    for event in session.room_events
                )
            )

    def test_ten_concurrent_reset_events_accept_only_current_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = real_session(temp_dir)
            try:
                session.register("alice")
                session.sit("alice", 0)
                session.ready_account("alice")
                self.assertIsNotNone(session.game)
                assert session.game is not None
                with session.lock:
                    session.game.phase = "round_over"
                    generation = session.room_generation

                barrier = threading.Barrier(10)
                successes: list[dict] = []
                errors: list[BaseException] = []

                def reset_once() -> None:
                    try:
                        barrier.wait(timeout=2.0)
                        successes.append(
                            session.reset_match("alice", room_generation=generation)
                        )
                    except BaseException as exc:
                        errors.append(exc)

                workers = [threading.Thread(target=reset_once) for _ in range(10)]
                for worker in workers:
                    worker.start()
                for worker in workers:
                    worker.join(timeout=5.0)

                self.assertEqual(len(successes), 1)
                self.assertEqual(len(errors), 9)
                self.assertTrue(
                    all(
                        isinstance(error, ValueError)
                        and "stale room_generation" in str(error)
                        for error in errors
                    )
                )
                self.assertIsNone(session.game)
                self.assertEqual(session.room_generation, generation + 1)
                self.assertEqual(len(session._room_event_queue), 0)
                self.assertTrue(session._room_worker.is_alive())
            finally:
                session.close()


if __name__ == "__main__":
    unittest.main()

