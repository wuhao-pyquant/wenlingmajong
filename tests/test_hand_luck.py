from __future__ import annotations

from collections import Counter
import tempfile
import unittest
from pathlib import Path

from wenling_core.game import WenlingMahjongGame
from wenling_core.hand_luck_runtime import default_hand_luck_scorer
from wenling_lan_host.battle_app import BattleSession
from wenling_lan_host.battle_db import BattleDatabase


class PassPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return next((action for action in legal_actions if action.get("type") == "pass"), legal_actions[0])


class HandLuckTests(unittest.TestCase):
    def test_supplied_runtime_model_has_stable_scores(self) -> None:
        scorer = default_hand_luck_scorer()
        lucky = scorer.score(
            seat=0,
            de_draws=1,
            fan_flower_draws=2,
            opening_shanten=3,
            final_shanten=0,
            normal_draw_count=8,
            open_claim_count=0,
            opening_leizi_distance=2,
            final_leizi_distance=1,
            supplement_draw_count=0,
        )
        stalled = scorer.score(
            seat=0,
            de_draws=1,
            fan_flower_draws=2,
            opening_shanten=3,
            final_shanten=3,
            normal_draw_count=8,
            open_claim_count=0,
            opening_leizi_distance=2,
            final_leizi_distance=2,
            supplement_draw_count=0,
        )
        baseline = scorer.score(
            seat=2,
            de_draws=0,
            fan_flower_draws=0,
            opening_shanten=4,
            final_shanten=4,
            normal_draw_count=0,
            open_claim_count=0,
            opening_leizi_distance=2,
            final_leizi_distance=2,
            supplement_draw_count=0,
        )
        self.assertEqual(lucky.luck_percentile, 79.8)
        self.assertEqual(stalled.luck_percentile, 73.3)
        self.assertEqual(baseline.luck_percentile, 34.9)
        self.assertEqual(lucky.categories["progress"], "-0.6~-0.3")
        self.assertEqual(lucky.categories["leizi_progress"], "-0.3~0")
        self.assertEqual(lucky.categories["leizi_win"], "0")
        self.assertEqual(lucky.categories["zimo_de"], "0")
        self.assertEqual(lucky.categories["gang_flower"], "0")
        self.assertEqual(lucky.categories["rob_gang"], "0")

        very_fast = scorer.score(
            seat=2,
            de_draws=0,
            fan_flower_draws=2,
            opening_shanten=6,
            final_shanten=0,
            normal_draw_count=3,
            open_claim_count=0,
            opening_leizi_distance=6,
            final_leizi_distance=0,
            supplement_draw_count=0,
        )
        self.assertEqual(very_fast.categories["progress"], scorer.low_efficiency_category)
        self.assertEqual(very_fast.categories["leizi_progress"], scorer.low_efficiency_category)
        self.assertTrue(0 <= very_fast.luck_percentile <= 100)

    def test_jump_bool_win_type_features_are_explicit(self) -> None:
        scorer = default_hand_luck_scorer()
        base = {
            "seat": 0,
            "de_draws": 1,
            "fan_flower_draws": 2,
            "opening_shanten": 3,
            "final_shanten": 0,
            "normal_draw_count": 8,
            "open_claim_count": 1,
            "opening_leizi_distance": 2,
            "final_leizi_distance": 1,
            "supplement_draw_count": 0,
        }

        ordinary = scorer.score(**base, win_type="普通和牌")
        leizi = scorer.score(**base, win_type="劣子和")
        zimo_de = scorer.score(**base, win_type="自摸得")
        gang_flower = scorer.score(**base, win_type="杠上开花")
        rob_gang = scorer.score(**base, win_type="抢杠和")

        self.assertEqual(ordinary.categories["leizi_win"], "0")
        self.assertEqual(ordinary.categories["zimo_de"], "0")
        self.assertEqual(ordinary.categories["gang_flower"], "0")
        self.assertEqual(ordinary.categories["rob_gang"], "0")
        self.assertEqual(leizi.categories["leizi_win"], "1")
        self.assertEqual(zimo_de.categories["zimo_de"], "1")
        self.assertEqual(gang_flower.categories["gang_flower"], "1")
        self.assertEqual(rob_gang.categories["rob_gang"], "1")
        self.assertGreater(leizi.luck_percentile, ordinary.luck_percentile)
        self.assertGreater(zimo_de.luck_percentile, ordinary.luck_percentile)
        self.assertGreater(gang_flower.luck_percentile, ordinary.luck_percentile)
        self.assertGreater(rob_gang.luck_percentile, ordinary.luck_percentile)

        three_de = scorer.score(**{**base, "de_draws": 3}, win_type="")
        self.assertEqual(three_de.categories["leizi_win"], "1")

    def test_open_claim_count_adjusts_normal_progress_efficiency(self) -> None:
        scorer = default_hand_luck_scorer()
        base = {
            "seat": 0,
            "de_draws": 0,
            "fan_flower_draws": 0,
            "opening_shanten": 3,
            "final_shanten": 0,
            "normal_draw_count": 2,
            "opening_leizi_distance": 2,
            "final_leizi_distance": 2,
            "supplement_draw_count": 0,
        }

        no_claim = scorer.score(**base, open_claim_count=0)
        one_claim = scorer.score(**base, open_claim_count=1)

        self.assertEqual(no_claim.normal_progress_rate, -1.5)
        self.assertEqual(no_claim.categories["progress"], scorer.low_efficiency_category)
        self.assertEqual(one_claim.normal_progress_rate, -1.0)
        self.assertEqual(one_claim.categories["progress"], "-1.5~-1.0")
        self.assertNotEqual(no_claim.model_score, one_claim.model_score)

    def test_successful_chi_peng_and_ming_gang_increment_open_claim_count(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.players[0].discards = ["b2", "east", "m7"]
            game.players[1].hand = Counter({"b1": 1, "b3": 1})
            game.players[2].hand = Counter({"east": 2})
            game.players[3].hand = Counter({"m7": 3})

            game._execute_claim(1, 0, "b2", "chi", ["b1", "b3"])
            game._execute_claim(2, 0, "east", "peng")
            game._execute_claim(3, 0, "m7", "ming_gang")

            self.assertEqual(game.round_stats[1]["open_claim_count"], 1)
            self.assertEqual(game.round_stats[2]["open_claim_count"], 1)
            self.assertEqual(game.round_stats[3]["open_claim_count"], 1)

    def test_win_and_draw_settlements_include_all_player_luck_scores(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            win_game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            win_game.new_round()
            win_game.round_stats[1]["draw_turns"] = 3
            win_game._finish_win(1, "normal")
            win_luck = win_game.settlement["hand_luck"]
            self.assertEqual(len(win_luck), 4)
            self.assertEqual(win_luck[1]["seat"], 1)
            self.assertIn("normal_progress_rate", win_luck[1])
            self.assertIn("leizi_progress_rate", win_luck[1])
            self.assertEqual(
                [row["account"] for row in win_luck],
                [player.name for player in win_game.players],
            )
            self.assertTrue(all(0 <= row["luck_percentile"] <= 100 for row in win_luck))

            draw_game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            draw_game.new_round()
            draw_game._draw_game("test draw")
            draw_luck = draw_game.settlement["hand_luck"]
            self.assertEqual(len(draw_luck), 4)
            self.assertTrue(all(0 <= row["luck_percentile"] <= 100 for row in draw_luck))

    def test_only_winner_receives_jump_bool_win_type(self) -> None:
        class RecordingScorer:
            def __init__(self) -> None:
                self.inner = default_hand_luck_scorer()
                self.calls: list[dict] = []

            def score(self, **kwargs):
                self.calls.append(dict(kwargs))
                return self.inner.score(**kwargs)

        with tempfile.TemporaryDirectory() as temp_dir:
            scorer = RecordingScorer()
            game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
                hand_luck_scorer=scorer,
            )
            game.new_round()
            scorer.calls.clear()
            game._finish_win(1, "劣子和")

            self.assertEqual([call["seat"] for call in scorer.calls], [0, 1, 2, 3])
            self.assertEqual(
                [call["win_type"] for call in scorer.calls],
                ["", "劣子和", "", ""],
            )
            hand_luck = game.settlement["hand_luck"]
            self.assertEqual(hand_luck[1]["categories"]["leizi_win"], "1")

    def test_room_average_resets_with_session_but_historical_average_persists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.ensure_account("alice")
            first = BattleSession(db, temp_dir, lambda _policy: PassPolicy(), PassPolicy)
            try:
                first.seats[0] = "alice"
                first.record_hand_luck("alice", 20.0)
                first.record_hand_luck("alice", 80.0)
                row = first._stats_payload()[0]
                self.assertEqual(row["room"], {"luck_score": 50.0, "luck_hands": 2})
                self.assertNotIn("luck_score", row["all"])
                self.assertEqual(db.stats_for_accounts(["alice"])[0]["all"]["luck_score"], 50.0)
                rotated = first._rotate_payload_for_viewer(
                    {
                        "players": [
                            {"seat": seat, "name": name, "melds": []}
                            for seat, name in enumerate(("alice", "bob", "carol", "dave"))
                        ],
                        "settlement": {
                            "winner": 2,
                            "hand_luck": [
                                {
                                    "seat": seat,
                                    "account": name,
                                    "luck_percentile": float(10 + seat),
                                }
                                for seat, name in enumerate(("alice", "bob", "carol", "dave"))
                            ],
                        },
                    },
                    2,
                )
                self.assertEqual(
                    [item["absolute_seat"] for item in rotated["settlement"]["hand_luck"]],
                    [2, 3, 0, 1],
                )
                self.assertEqual(
                    [item["seat"] for item in rotated["settlement"]["hand_luck"]],
                    [0, 1, 2, 3],
                )
                self.assertEqual(
                    [
                        (player["name"], luck["luck_percentile"])
                        for player, luck in zip(
                            rotated["players"],
                            rotated["settlement"]["hand_luck"],
                            strict=True,
                        )
                    ],
                    [
                        ("carol", 12.0),
                        ("dave", 13.0),
                        ("alice", 10.0),
                        ("bob", 11.0),
                    ],
                )
            finally:
                first.close()

            second = BattleSession(db, temp_dir, lambda _policy: PassPolicy(), PassPolicy)
            try:
                second.seats[0] = "alice"
                row = second._stats_payload()[0]
                self.assertEqual(row["room"], {"luck_score": None, "luck_hands": 0})
                self.assertEqual(db.stats_for_accounts(["alice"])[0]["all"]["luck_score"], 50.0)
            finally:
                second.close()


if __name__ == "__main__":
    unittest.main()
