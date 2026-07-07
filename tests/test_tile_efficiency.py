from __future__ import annotations

import unittest
import tempfile
import time
import random
from collections import Counter
from unittest.mock import patch

from wenling_core.game import WenlingMahjongGame
from wenling_core.rules import _rounded_score_total, can_ming_gang, can_peng, can_win, score_player
from wenling_core.tile_efficiency import (
    TileEfficiencyPolicyModel,
    _shanten_reference,
    effective_tiles,
    hand_metric,
    shanten,
)
from wenling_core.tiles import FLOWERS, TILE_ORDER, build_wall


class PassPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return next((action for action in legal_actions if action.get("type") == "pass"), legal_actions[0])


class ClaimPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return next((action for action in legal_actions if action.get("type") in {"peng", "ming_gang", "hu"}), legal_actions[0])


class StaleIllegalDiscardPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return {"type": "discard", "tile": "bai"}


class NoShuffleRandom:
    def shuffle(self, values: list[str]) -> None:
        return None


def observation(
    hand: Counter[str],
    *,
    seat: int = 0,
    melds: list[dict] | None = None,
    flowers: list[str] | None = None,
    discards: list[list[str]] | None = None,
    de_indicator: str = "bai",
    de_set: set[str] | None = None,
    flower_set: set[str] | None = None,
) -> dict:
    players = []
    discards = discards or [[], [], [], []]
    for idx in range(4):
        players.append(
            {
                "seat": idx,
                "melds": list(melds or []) if idx == seat else [],
                "discards": list(discards[idx]),
                "flowers": list(flowers or []) if idx == seat else [],
                "flower_count": len(flowers or []) if idx == seat else 0,
                "hand_count": sum(hand.values()) if idx == seat else 16,
                "chips": 1000,
            }
        )
    return {
        "seat": seat,
        "hand": dict(hand),
        "flowers": list(flowers or []),
        "de_count": sum(hand.get(code, 0) for code in (de_set or {de_indicator})),
        "public": {
            "round_no": 1,
            "dealer": 0,
            "current_player": seat,
            "wall_remaining": 80,
            "de_indicator": de_indicator,
            "de_set": sorted(de_set or {de_indicator}),
            "flower_set": sorted(flower_set or {"rh1", "rh2", "rh3", "rh4", "bh1", "bh2", "bh3", "bh4"}),
            "players": players,
            "history": [],
        },
    }


class TileEfficiencyTests(unittest.TestCase):
    def test_compact_shanten_matches_legacy_reference_on_random_physical_hands(self) -> None:
        rng = random.Random(20260627)
        wall = build_wall()
        for _ in range(400):
            de_set = {rng.choice(TILE_ORDER)}
            pool = [tile for tile in wall if tile not in FLOWERS or tile in de_set]
            hand_size = rng.randint(1, min(18, len(pool)))
            hand = Counter(rng.sample(pool, hand_size))
            self.assertEqual(
                shanten(hand, de_set),
                _shanten_reference(hand, de_set),
                msg=f"hand={dict(hand)} de_set={sorted(de_set)}",
            )

    def test_white_dragon_is_not_double_counted_as_a_bamboo_tile(self) -> None:
        hand = Counter(
            {
                "t1": 2,
                "t4": 1,
                "t5": 1,
                "t6": 1,
                "b2": 1,
                "b4": 1,
                "b5": 1,
                "b6": 1,
                "b7": 1,
                "bai": 2,
                "east": 1,
                "south": 1,
                "north": 1,
                "m2": 1,
                "m8": 2,
            }
        )

        self.assertEqual(shanten(hand, {"m7"}), 4)

    def test_peng_and_ming_gang_require_real_matching_tiles(self) -> None:
        hand = Counter({"east": 1, "bai": 3})
        self.assertFalse(can_peng(hand, "east", {"bai"}))
        self.assertFalse(can_peng(hand, "bai", {"bai"}))
        self.assertFalse(can_ming_gang(hand, "east", {"bai"}))
        self.assertFalse(can_ming_gang(hand, "bai", {"bai"}))
        hand["east"] = 2
        self.assertTrue(can_peng(hand, "east", {"bai"}))
        self.assertFalse(can_ming_gang(hand, "east", {"bai"}))

    def test_score_total_adds_twenty_base_only_for_winner(self) -> None:
        self.assertEqual(_rounded_score_total(15, 4), 240)
        self.assertEqual(_rounded_score_total(15 + 20, 4), 500)
        self.assertEqual(_rounded_score_total(16 + 20, 4), 500)

    def test_score_player_adds_winning_base_item_only_for_winner(self) -> None:
        hand = Counter({"m1": 1, "m2": 1, "m3": 1, "m4": 1, "m5": 1, "m6": 1, "m7": 1, "m8": 1, "m9": 1, "t1": 1, "t2": 1, "t3": 1, "east": 2})
        winner_score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")
        other_score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=False)
        self.assertTrue(any(item.get("label") == "胡牌底" and item.get("points") == 20 for item in winner_score["base_items"]))
        self.assertFalse(any(item.get("label") == "胡牌底" for item in other_score["base_items"]))
        self.assertEqual(winner_score["base"], other_score["base"] + 20)

    def test_non_winning_concealed_triplet_can_use_de_for_current_points(self) -> None:
        hand = Counter({"east": 2, "bai": 1, "m1": 1, "m4": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=False)

        self.assertTrue(any(item.get("points") == 8 for item in score["base_items"]))
        self.assertTrue(any(item.get("fan") == 1 for item in score["fan_items"]))

    def test_four_winds_huiqi_requires_wind_groups_not_singletons(self) -> None:
        hand = Counter({"east": 1, "south": 1, "west": 1, "north": 1, "m1": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=False)

        self.assertFalse(any(item.get("label") == "四风会齐" for item in score["fan_items"]))

    def test_four_winds_huiqi_requires_self_wind_triplet(self) -> None:
        hand = Counter({"east": 2, "south": 3, "west": 3, "north": 3, "m1": 1, "m2": 1, "m3": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")

        self.assertFalse(any(item.get("label") == "四风会齐" for item in score["fan_items"]))

    def test_four_winds_huiqi_accepts_three_triplets_plus_fourth_pair(self) -> None:
        hand = Counter({"east": 3, "south": 3, "west": 3, "north": 2, "m1": 1, "m2": 1, "m3": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")

        self.assertTrue(any(item.get("label") == "四风会齐" and item.get("fan") == 13 for item in score["fan_items"]))

    def test_four_winds_huiqi_counts_exposed_wind_triplets(self) -> None:
        hand = Counter({"east": 3, "south": 3, "north": 2, "m1": 1})
        melds = [{"type": "peng", "tile": "west", "tiles": ["west", "west", "west"], "from": 1}]
        score = score_player(hand, [], melds, 0, {"bai"}, "bai", winner=False)

        self.assertTrue(any(item.get("label") == "四风会齐" and item.get("fan") == 13 for item in score["fan_items"]))

    def test_tianhu_adds_five_fan(self) -> None:
        hand = Counter({
            "m1": 1,
            "m2": 1,
            "m3": 1,
            "m4": 1,
            "m5": 1,
            "m6": 1,
            "t1": 1,
            "t2": 1,
            "t3": 1,
            "b1": 1,
            "b2": 1,
            "b3": 1,
            "east": 3,
            "fa": 2,
        })
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="天胡")

        self.assertTrue(any(item.get("label") == "天胡" and item.get("fan") == 5 for item in score["fan_items"]))

    def test_pure_de_pair_is_leizi_not_normal_scoring_restoration(self) -> None:
        from wenling_core.rules import leizi_win_reason

        hand = Counter({"bai": 2})
        melds = [
            {"type": "chi", "tile": "m1", "tiles": ["m1", "m2", "m3"]},
            {"type": "chi", "tile": "m4", "tiles": ["m4", "m5", "m6"]},
            {"type": "chi", "tile": "t1", "tiles": ["t1", "t2", "t3"]},
            {"type": "chi", "tile": "b1", "tiles": ["b1", "b2", "b3"]},
        ]
        self.assertIsNotNone(leizi_win_reason(hand, [], "bai", {"bai"}, 0))
        self.assertFalse(can_win(hand, {"bai"}, melds))
        self.assertEqual(shanten(hand, {"bai"}), 0)

    def test_open_hand_real_plus_de_pair_is_normal_complete_pair(self) -> None:
        melds = [
            {"type": "chi", "tile": "m1", "tiles": ["m1", "m2", "m3"]},
            {"type": "chi", "tile": "m4", "tiles": ["m4", "m5", "m6"]},
            {"type": "chi", "tile": "t1", "tiles": ["t1", "t2", "t3"]},
            {"type": "chi", "tile": "b1", "tiles": ["b1", "b2", "b3"]},
        ]
        hand = Counter({"east": 1, "bai": 1})

        self.assertTrue(can_win(hand, {"bai"}, melds))
        self.assertEqual(shanten(hand, {"bai"}), -1)

    def test_two_de_can_attach_separately_to_pair_and_triplet_for_normal_hu(self) -> None:
        hand = Counter({"east": 1, "fa": 2, "bai": 2, "m1": 1, "m2": 1, "m3": 1, "t1": 1, "t2": 1, "t3": 1, "b1": 1, "b2": 1, "b3": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")

        self.assertTrue(can_win(hand, {"bai"}))
        self.assertEqual(shanten(hand, {"bai"}), -1)
        self.assertTrue(any(item.get("points") == 2 for item in score["base_items"]))
        self.assertTrue(any(item.get("points") == 8 for item in score["base_items"]))
        self.assertTrue(any(item.get("fan") == 1 for item in score["fan_items"]))

    def test_two_de_can_attach_together_to_one_real_tile_as_triplet(self) -> None:
        hand = Counter({"east": 2, "fa": 1, "bai": 2, "m1": 1, "m2": 1, "m3": 1, "t1": 1, "t2": 1, "t3": 1, "b1": 1, "b2": 1, "b3": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")

        self.assertTrue(can_win(hand, {"bai"}))
        self.assertEqual(shanten(hand, {"bai"}), -1)
        self.assertTrue(any(item.get("points") == 8 for item in score["base_items"]))
        self.assertTrue(any(item.get("fan") == 1 for item in score["fan_items"]))

    def test_pure_de_triplet_is_leizi_fixed_score(self) -> None:
        from wenling_core.rules import leizi_win_reason

        hand = Counter({"bai": 3, "m1": 1, "m2": 1, "m3": 1, "t1": 1, "t2": 1, "t3": 1, "b1": 1, "b2": 1, "b3": 1, "fa": 2})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="劣子和")

        self.assertIsNotNone(leizi_win_reason(hand, [], "bai", {"bai"}, 0))
        self.assertEqual(score["total"], 500)

    def test_four_flowered_zhong_counts_as_leizi_but_self_wind_must_be_in_hand(self) -> None:
        from wenling_core.rules import leizi_win_reason

        self.assertIsNotNone(leizi_win_reason(Counter(), ["zhong"] * 4, "south", {"south"}, 0))
        self.assertIsNotNone(leizi_win_reason(Counter({"east": 4}), [], "bai", {"bai"}, 0))
        self.assertIsNone(leizi_win_reason(Counter({"east": 3}), ["east"], "bai", {"bai"}, 0))

    def test_leizi_four_tile_sources_follow_de_flower_and_concealed_rules(self) -> None:
        from wenling_core.rules import leizi_win_reason

        self.assertIsNotNone(leizi_win_reason(Counter(), ["bai"] * 4, "m1", {"m1"}, 0))
        self.assertIsNone(leizi_win_reason(Counter({"bai": 4}), [], "m1", {"m1"}, 0))
        self.assertIsNotNone(leizi_win_reason(Counter({"bai": 3}), [], "bai", {"bai"}, 0))

        self.assertIsNotNone(leizi_win_reason(Counter(), ["fa"] * 4, "zhong", {"zhong"}, 0))
        self.assertIsNone(leizi_win_reason(Counter({"fa": 4}), [], "zhong", {"zhong"}, 0))
        self.assertIsNotNone(leizi_win_reason(Counter({"zhong": 3}), [], "zhong", {"zhong"}, 0))

        self.assertIsNotNone(leizi_win_reason(Counter({"zhong": 4}), [], "m1", {"m1"}, 0))
        self.assertIsNone(leizi_win_reason(Counter({"zhong": 3, "m1": 1}), [], "m1", {"m1"}, 0))
        self.assertIsNotNone(leizi_win_reason(Counter({"east": 4}), [], "m1", {"m1"}, 0))
        self.assertIsNone(leizi_win_reason(Counter({"east": 3, "m1": 1}), [], "m1", {"m1"}, 0))

    def test_extracted_four_zhong_flowers_finish_leizi(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(PassPolicy(), temp_dir, human_seat=None)
            game.de_indicator = "south"
            game.de_set = {"south"}
            game.flower_set = {"zhong"}
            game.players[0].hand = Counter({"zhong": 4})

            self.assertEqual(game._extract_current_flowers(0), ["zhong"] * 4)
            self.assertTrue(game._finish_leizi_if_present(0))
            self.assertEqual(game.phase, "round_over")
            self.assertEqual(game.winner, 0)
            self.assertEqual(game.win_type, "劣子和")

    def test_winning_concealed_triplet_can_use_de_for_points_and_fan(self) -> None:
        hand = Counter({"fa": 2, "bai": 1, "east": 2, "m1": 1, "m2": 1, "m3": 1, "m4": 1, "m5": 1, "m6": 1, "t1": 1, "t2": 1, "t3": 1})
        score = score_player(hand, [], [], 0, {"bai"}, "bai", winner=True, win_type="普通和牌")

        self.assertTrue(any(item.get("points") == 8 for item in score["base_items"]))
        self.assertTrue(any(item.get("fan") == 1 for item in score["fan_items"]))

    def test_de_wildcard_complete_matches_can_win(self) -> None:
        hand = Counter(
            {
                "m1": 1,
                "m2": 1,
                "bai": 1,
                "m4": 1,
                "m5": 1,
                "m6": 1,
                "t1": 1,
                "t2": 1,
                "t3": 1,
                "b1": 1,
                "b2": 1,
                "b3": 1,
                "east": 3,
                "fa": 2,
            }
        )
        self.assertTrue(can_win(hand, {"bai"}))
        self.assertEqual(shanten(hand, {"bai"}), -1)

    def test_shanten_handles_multiple_legal_meld_shapes(self) -> None:
        no_meld_waiting = Counter(
            {
                "m1": 1,
                "m2": 1,
                "m3": 1,
                "m4": 1,
                "m5": 1,
                "m6": 1,
                "t1": 1,
                "t2": 1,
                "t3": 1,
                "b1": 1,
                "b2": 1,
                "b3": 1,
                "east": 3,
                "fa": 1,
            }
        )
        one_meld_waiting = Counter({"t1": 1, "t2": 1, "b1": 1, "b2": 1, "b3": 1, "b4": 1, "b5": 1, "b6": 1, "east": 3, "fa": 2})
        two_meld_waiting = Counter({"t1": 1, "t2": 1, "b1": 1, "b2": 1, "b3": 1, "east": 3, "fa": 2})
        self.assertEqual(shanten(no_meld_waiting, {"bai"}), 0)
        self.assertEqual(shanten(one_meld_waiting, {"bai"}), 0)
        self.assertEqual(shanten(two_meld_waiting, {"bai"}), 0)

    def test_effective_tiles_subtract_visible_information_and_de_indicator(self) -> None:
        hand = Counter(
            {
                "m1": 1,
                "m2": 1,
                "m3": 1,
                "m4": 1,
                "m5": 1,
                "m6": 1,
                "t1": 1,
                "t2": 1,
                "t3": 1,
                "b1": 1,
                "b2": 1,
                "b3": 1,
                "east": 3,
                "fa": 1,
            }
        )
        obs = observation(hand, discards=[["fa", "fa"], [], [], []], de_indicator="bai", de_set={"bai"})
        waits = effective_tiles(obs, hand)
        self.assertEqual(waits.get("fa"), 1)
        self.assertEqual(waits.get("bai"), 3)

    def test_policy_prefers_lower_shanten_discard(self) -> None:
        hand = Counter(
            {
                "m1": 1,
                "m2": 1,
                "m3": 1,
                "m4": 1,
                "m5": 1,
                "m6": 1,
                "t1": 1,
                "t2": 1,
                "t3": 1,
                "b1": 1,
                "b2": 1,
                "b3": 1,
                "east": 3,
                "fa": 1,
                "zhong": 1,
            }
        )
        obs = observation(hand, de_indicator="bai", de_set={"bai"})
        policy = TileEfficiencyPolicyModel()
        self.assertGreater(
            policy.action_rank_key(obs, {"type": "discard", "tile": "zhong"}),
            policy.action_rank_key(obs, {"type": "discard", "tile": "m1"}),
        )

    def test_claim_evaluation_uses_actual_meld_state_and_forced_discard(self) -> None:
        melds = [
            {"type": "chi", "tile": "m3", "tiles": ["m1", "m2", "m3"], "from": 3},
            {"type": "peng", "tile": "south", "tiles": ["south", "south", "south"], "from": 2},
        ]
        hand = Counter({"east": 2, "m4": 1, "m5": 1, "m6": 1, "b1": 1, "b2": 1, "b3": 1, "fa": 2, "t1": 1, "t2": 1, "zhong": 1})
        obs = observation(hand, melds=melds, discards=[[], ["east"], [], []], de_indicator="bai", de_set={"bai"})
        metric = TileEfficiencyPolicyModel().action_metric(obs, {"type": "peng", "tile": "east"})
        self.assertEqual(sum(metric["hand"].values()), 10)
        self.assertEqual(len(metric["melds"]), 3)
        self.assertIn("forced_discard", metric)

    def test_peng_response_loses_to_pass_when_concealed_scoring_ties(self) -> None:
        hand = Counter({"east": 3, "m1": 1, "m2": 1, "m3": 1, "m4": 1, "m5": 1, "b1": 1, "b2": 1, "b3": 1, "fa": 2})
        obs = observation(hand, discards=[[], ["east"], [], []], de_indicator="bai", de_set={"bai"})
        policy = TileEfficiencyPolicyModel()
        scored = policy.score_actions(obs, [{"type": "peng", "tile": "east"}, {"type": "pass"}])

        self.assertEqual(scored[0]["rank_key"], scored[1]["rank_key"])
        self.assertEqual(policy.choose_action(obs, [{"type": "peng", "tile": "east"}, {"type": "pass"}]), {"type": "pass"})

    def test_point_tiebreak_uses_simulated_melds_and_current_flowers(self) -> None:
        melds = [{"type": "peng", "tile": "east", "tiles": ["east", "east", "east"], "from": 1}]
        hand = Counter({"m1": 1, "m2": 1, "m3": 1, "m4": 1, "m5": 1, "m6": 1, "t1": 1, "t2": 1, "t3": 1, "fa": 2, "zhong": 1, "west": 1})
        flowers = ["rh1", "rh2"]
        obs = observation(hand, melds=melds, flowers=flowers, de_indicator="bai", de_set={"bai"})
        metric = hand_metric(obs, hand, melds)
        expected = score_player(hand, flowers, melds, 0, {"bai"}, "bai", winner=False)["total"]
        self.assertEqual(metric["points"], expected)

    def test_claim_meld_records_claimed_discard_index(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.players[0].discards = ["b2"]
            game.players[1].hand = Counter({"b1": 1, "b3": 1})

            game._execute_claim(1, 0, "b2", "chi", ["b1", "b3"])

            self.assertEqual(game.players[1].melds[-1]["discard_index"], 0)

    def test_claim_meld_uses_latest_duplicate_discard_index(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.players[0].discards = ["b2", "t9", "b2"]
            game.players[1].hand = Counter({"b1": 1, "b3": 1})

            game._execute_claim(1, 0, "b2", "chi", ["b1", "b3"])

            self.assertEqual(game.players[1].melds[-1]["discard_index"], 2)

    def test_claim_and_win_reject_fifth_physical_tile(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=None,
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.players[1].hand = Counter({"north": 4})

            self.assertEqual(game._claim_actions_for_seat(1, "north"), [])
            self.assertFalse(game._can_execute_claim(1, "north", "peng"))
            self.assertFalse(game._can_execute_claim(1, "north", "ming_gang"))
            self.assertFalse(game._can_player_win_with_tile(1, "north"))

    def test_claimed_tile_can_be_discarded_if_still_physically_in_hand(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=1,
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.phase = "turn"
            game.players[1].hand = Counter({"east": 3, "m1": 1, "m2": 1})
            game._execute_claim(1, 0, "east", "peng")

            legal_discards = [action["tile"] for action in game.legal_turn_actions(1) if action["type"] == "discard"]
            self.assertIn("east", legal_discards)
            game._discard(1, "east")
            self.assertIn("east", game.players[1].discards)

    def test_ai_stale_illegal_de_discard_is_replaced(self) -> None:
        stale_policy = StaleIllegalDiscardPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                stale_policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                human_seats={0},
                seat_models=[PassPolicy(), stale_policy, PassPolicy(), PassPolicy()],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.phase = "turn"
            game.current_player = 1
            game.players[1].hand = Counter({"east": 1, "m1": 1, "bai": 1})

            self.assertNotIn("bai", [action["tile"] for action in game.legal_turn_actions(1) if action["type"] == "discard"])
            self.assertTrue(game.prepare_deferred_ai_turn())
            game.pending["deadline"] = 0
            game.resolve_deferred_pending(force=True)

            self.assertIn("m1", game.players[1].discards)
            self.assertNotIn("bai", game.players[1].discards)

    def test_stale_ai_turn_result_is_ignored(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                human_seats={0},
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.phase = "turn"
            game.current_player = 1
            game.players[1].hand = Counter({"m1": 1, "m2": 1})
            legal = game.legal_turn_actions(1)
            game.pending = {
                "kind": "ai_turn",
                "from": 1,
                "tile": "",
                "human_actions": [],
                "ai_candidates": [1],
                "deferred": True,
                "deadline": 0.0,
                "ai_thinking": True,
                "ai_think_token": 2,
                "ai_precomputed_action": None,
                "ai_precomputed_observation": game.observation(1),
                "ai_precomputed_legal_actions": legal,
            }

            game._queue_ai_result({"kind": "ai_turn", "seat": 1, "token": 1, "action": {"type": "discard", "tile": "m1"}})
            game._resolve_ai_turn_step(force=False)

            self.assertIsNotNone(game.pending)
            self.assertTrue(game.pending["ai_thinking"])
            self.assertEqual(game.players[1].discards, [])

            game._queue_ai_result({
                "kind": "ai_turn",
                "seat": 1,
                "token": 2,
                "action": {"type": "discard", "tile": "m1"},
                "observation": game.observation(1),
                "legal_actions": legal,
            })
            game._resolve_ai_turn_step(force=False)

            self.assertIn("m1", game.players[1].discards)

    def test_stale_response_ai_result_is_ignored(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                human_seats={0},
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.phase = "turn"
            game.current_player = 0
            game.players[0].discards = ["m2"]
            game.players[1].hand = Counter({"m2": 2})
            legal = [{"type": "pass"}]
            game.pending = {
                "kind": "response_poll",
                "from": 0,
                "tile": "m2",
                "response_kind": "discard",
                "human_actions": [],
                "ai_candidates": [1],
                "human_responders": [],
                "responders": [1],
                "legal_by_seat": {1: legal},
                "decisions_by_seat": {},
                "responses": [],
                "order_index_by_seat": {1: 0},
                "deferred": True,
                "deadline": 0.0,
                "current_responder": None,
                "ai_thinking_by_seat": {1: True},
                "ai_think_tokens_by_seat": {1: 2},
                "ai_precomputed_actions": {},
                "ai_precomputed_observations": {},
                "ai_precomputed_legal_actions": {},
            }

            game._queue_ai_result({"kind": "response_poll", "seat": 1, "token": 1, "action": {"type": "pass"}})
            game._resolve_response_poll_step(force=False)

            self.assertIsNotNone(game.pending)
            self.assertEqual(game.pending["decisions_by_seat"], {})
            self.assertTrue(game.pending["ai_thinking_by_seat"][1])

            game._queue_ai_result({
                "kind": "response_poll",
                "seat": 1,
                "token": 2,
                "action": {"type": "pass"},
                "observation": game.observation(1),
                "legal_actions": legal,
            })
            game._resolve_response_poll_step(force=False)

            self.assertIsNone(game.pending)
            self.assertEqual(game.current_player, 1)

    def test_tile_efficiency_prefers_pass_on_exact_response_tie(self) -> None:
        policy = TileEfficiencyPolicyModel()
        policy.score_actions = lambda observation, legal_actions: [  # type: ignore[method-assign]
            {"action": {"type": "peng", "tile": "east"}, "rank_key": (0, 10, 0, 8)},
            {"action": {"type": "pass"}, "rank_key": (0, 10, 0, 8)},
        ]

        chosen = policy.choose_action({}, [{"type": "peng", "tile": "east"}, {"type": "pass"}])

        self.assertEqual(chosen, {"type": "pass"})

    def test_tile_efficiency_penalizes_fresh_discard_in_bao_phase_without_forbidding_it(self) -> None:
        obs = observation(Counter({"m1": 1, "t1": 1}), de_indicator="bai", de_set={"bai"})
        obs["public"]["bao_phase"] = True
        obs["public"]["discarded_tile_kinds"] = ["t1"]
        policy = TileEfficiencyPolicyModel()

        fresh = policy.action_metric(obs, {"type": "discard", "tile": "m1"})
        familiar = policy.action_metric(obs, {"type": "discard", "tile": "t1"})

        self.assertGreater(fresh.get("bao_risk_penalty", 0), 0)
        self.assertEqual(familiar.get("bao_risk_penalty", 0), 0)
        self.assertGreater(policy.action_rank_key(obs, {"type": "discard", "tile": "t1"}), policy.action_rank_key(obs, {"type": "discard", "tile": "m1"}))
        self.assertEqual(policy.choose_action(obs, [{"type": "discard", "tile": "m1"}]), {"type": "discard", "tile": "m1"})

    def test_tile_efficiency_penalizes_zhong_fa_discard_when_shanten_above_one(self) -> None:
        obs = observation(Counter({"zhong": 1, "fa": 1, "m1": 1, "t1": 1}), de_indicator="bai", de_set={"bai"})
        policy = TileEfficiencyPolicyModel()

        zhong = policy.action_metric(obs, {"type": "discard", "tile": "zhong"})
        suited = policy.action_metric(obs, {"type": "discard", "tile": "m1"})

        self.assertGreater(zhong.get("bao_risk_penalty", 0), 0)
        self.assertEqual(suited.get("bao_risk_penalty", 0), 0)

    def test_tile_efficiency_penalizes_open_claims_in_bao_phase_without_forbidding_them(self) -> None:
        obs = observation(Counter({"east": 2, "m1": 1, "t1": 1}), discards=[["east"], [], [], []], de_indicator="bai", de_set={"bai"})
        obs["public"]["bao_phase"] = True
        policy = TileEfficiencyPolicyModel()

        metric = policy.action_metric(obs, {"type": "peng", "tile": "east"})

        self.assertGreater(metric.get("bao_risk_penalty", 0), 0)
        self.assertEqual(policy.choose_action(obs, [{"type": "peng", "tile": "east"}]), {"type": "peng", "tile": "east"})

    def test_response_poll_asks_next_seat_before_later_claimer(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.2,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.players[0].hand = Counter({"m1": 1, "m3": 1})
            game.players[1].hand = Counter({"m2": 2})

            game._open_discard_response(3, "m2")
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertEqual(game.pending["responders"], [0, 1])
            self.assertIsNone(game.pending["current_responder"])
            self.assertTrue(any(action.get("type") == "chi" for action in game.pending["human_actions"]))

            game._resolve_pending_with_human({"type": "chi", "tile": "m2", "tiles": ["m1", "m3"]})
            self.assertIsNone(game.pending)
            self.assertEqual(game.players[0].melds[-1]["type"], "chi")

    def test_response_poll_waits_for_each_human_responder(self) -> None:
        policy = ClaimPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                human_seats={0, 1, 2},
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.players[1].hand = Counter({"m2": 2})
            game.players[2].hand = Counter({"m2": 2})

            game._open_discard_response(3, "m2")

            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertIsNone(game.pending["current_responder"])
            self.assertEqual(game.pending["ai_candidates"], [])
            game.human_seat = 1
            self.assertTrue(any(action.get("type") == "peng" for action in game.pending_actions_for_human()))

            game.resolve_deferred_pending(force=True)
            self.assertEqual(game.pending["decisions_by_seat"], {})
            self.assertFalse(game.players[1].melds)

            game._resolve_pending_with_human({"type": "pass"})
            self.assertIn(1, game.pending["decisions_by_seat"])
            self.assertEqual(game.pending["ai_candidates"], [])

            game.resolve_deferred_pending(force=True)
            self.assertIsNotNone(game.pending)
            self.assertFalse(game.players[2].melds)
            game.human_seat = 2
            game._resolve_pending_with_human({"type": "pass"})
            self.assertIsNone(game.pending)

    def test_discard_pause_is_non_blocking_for_human_response(self) -> None:
        policy = PassPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=1,
                human_seats={1},
                seat_models=[policy, policy, policy, policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=2.0,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20

            game._open_discard_response(0, "m2")
            self.assertEqual(game.pending["kind"], "post_action_pause")
            self.assertGreaterEqual(game.pending["deadline"], time.time() + 1.5)

            game.players[1].hand = Counter({"m2": 2})
            game._open_discard_response(0, "m2")
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertIsNone(game.pending["current_responder"])
            self.assertTrue(any(action.get("type") == "peng" for action in game.pending["human_actions"]))

    def test_response_poll_resolves_by_action_priority_then_order(self) -> None:
        pass_policy = PassPolicy()
        claim_policy = ClaimPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                pass_policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[pass_policy, claim_policy, pass_policy, pass_policy],
                persist_logs=False,
                defer_ai_responses=True,
                response_delay_sec=0.2,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.players[0].hand = Counter({"m1": 1, "m3": 1})
            game.players[1].hand = Counter({"m2": 2})

            game._open_discard_response(3, "m2")
            self.assertEqual(game.pending["kind"], "response_poll")
            self.assertEqual(game.pending["responders"], [0, 1])
            self.assertIsNone(game.pending["current_responder"])

            game._resolve_pending_with_human({"type": "chi", "tile": "m2", "tiles": ["m1", "m3"]})
            deadline = time.time() + 2.0
            while game.pending is not None and time.time() < deadline:
                game._resolve_response_poll_step(force=False)
                time.sleep(0.01)
            self.assertIsNone(game.pending)
            self.assertEqual(game.players[1].melds[-1]["type"], "peng")

    def test_response_poll_same_hu_priority_uses_seat_order_not_response_time(self) -> None:
        claim_policy = ClaimPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                claim_policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[claim_policy, claim_policy, claim_policy, claim_policy],
                persist_logs=False,
                defer_ai_responses=True,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            waiting_hand = Counter({
                "m1": 1,
                "m3": 1,
                "m4": 1,
                "m5": 1,
                "m6": 1,
                "t1": 1,
                "t2": 1,
                "t3": 1,
                "b1": 1,
                "b2": 1,
                "b3": 1,
                "east": 2,
            })
            game.players[0].hand = Counter(waiting_hand)
            game.players[1].hand = Counter(waiting_hand)

            game._open_discard_response(2, "m2")
            self.assertEqual(game.pending["responders"], [0, 1])
            self.assertIsNone(game.pending["current_responder"])

            game._resolve_pending_with_human({"type": "hu", "tile": "m2"})
            self.assertEqual(game.winner, 0)

    def test_response_poll_uses_turn_order_for_same_priority(self) -> None:
        claim_policy = ClaimPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                claim_policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=None,
                seat_models=[claim_policy, claim_policy, claim_policy, claim_policy],
                persist_logs=False,
                defer_ai_responses=False,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.players[1].hand = Counter({"m2": 2})
            game.players[2].hand = Counter({"m2": 2})

            game._open_discard_response(0, "m2")
            self.assertIsNone(game.pending)
            self.assertEqual(game.players[1].melds[-1]["type"], "peng")
            self.assertFalse(game.players[2].melds)

    def test_stale_deferred_claim_is_treated_as_pass(self) -> None:
        claim_policy = ClaimPolicy()
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                claim_policy,  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[claim_policy, claim_policy, claim_policy, claim_policy],
                persist_logs=False,
                defer_ai_responses=True,
            )
            game.de_indicator = "bai"
            game.de_set = {"bai"}
            game.flower_set = set()
            game.wall = ["m9"] * 20
            game.phase = "turn"
            game.current_player = 3
            game.players[2].hand = Counter({"m7": 2})
            game.pending = {
                "kind": "ming_gang",
                "from": 3,
                "tile": "m7",
                "human_actions": [],
                "ai_candidates": [2],
                "ai_action": {"type": "ming_gang", "tile": "m7"},
                "deferred": True,
                "deadline": 0,
                "responders": [2],
            }

            game.resolve_deferred_pending(force=True)

            self.assertIsNone(game.pending)
            self.assertEqual(game.current_player, 0)
            self.assertFalse(game.players[2].melds)

    def test_next_round_rotates_dealer_only_after_non_dealer_win(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                human_seats={0},
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
                defer_ai_responses=True,
            )
            game.new_round()
            game.dealer = 0
            game._finish_win(1, "test")

            self.assertEqual(game.dealer, 0)
            self.assertEqual(game.next_dealer, 1)
            game.new_round()
            self.assertEqual(game.dealer, 1)
            serialized = game.serialize()
            self.assertEqual(serialized["players"][1]["wind"], "东")
            self.assertEqual(serialized["players"][0]["wind"], "北")

    def test_dealer_win_and_draw_keep_dealer_next_round(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
            )
            game.new_round()
            game.dealer = 2
            game._finish_win(2, "test")
            game.new_round()
            self.assertEqual(game.dealer, 2)

            game._draw_game("test")
            game.new_round()
            self.assertEqual(game.dealer, 2)

    def test_opening_east_wind_normal_win_is_tianhu(self) -> None:
        dealer_hand = [
            "m1", "m2", "m3",
            "m4", "m5", "m6",
            "t1", "t2", "t3",
            "b1", "b2", "b3",
            "east", "east", "east",
            "fa", "fa",
        ]
        filler = ["m8"] * 16
        wall = ["m9"] + filler + filler + dealer_hand + filler

        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
            )
            game.dealer = 2
            game.random = NoShuffleRandom()  # type: ignore[assignment]
            with patch("wenling_core.game.build_wall", return_value=list(wall)):
                state = game.new_round()

            self.assertEqual(state["phase"], "round_over")
            self.assertEqual(state["winner"], 2)
            self.assertEqual(state["win_type"], "天胡")
            self.assertTrue(
                any(item.get("label") == "天胡" and item.get("fan") == 5 for item in state["settlement"]["scores"][2]["fan_items"])
            )

    def test_opening_leizi_win_takes_priority_over_tianhu(self) -> None:
        dealer_hand = [
            "bai", "bai", "bai",
            "m1", "m2", "m3",
            "m4", "m5", "m6",
            "t1", "t2", "t3",
            "b1", "b2", "b3",
            "fa", "fa",
        ]
        filler = ["m8"] * 16
        wall = ["bai"] + dealer_hand + filler + filler + filler

        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
            )
            game.random = NoShuffleRandom()  # type: ignore[assignment]
            with patch("wenling_core.game.build_wall", return_value=list(wall)):
                state = game.new_round()

            self.assertEqual(state["phase"], "round_over")
            self.assertEqual(state["winner"], 0)
            self.assertEqual(state["win_type"], "劣子和")

    def test_shuffle_seats_keeps_chips_bound_to_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seed=7,
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
            )
            game.players[0].chips = 10
            game.players[1].chips = -20
            game.players[2].chips = 30
            game.players[3].chips = -40
            before = {player.name: player.chips for player in game.players}

            game.shuffle_seats(include_human=False)

            after = {player.name: player.chips for player in game.players}
            self.assertEqual(after, before)
            self.assertEqual(game.players[0].name, "你")


    def test_player_stats_follow_names_across_rounds_and_shuffle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),  # type: ignore[arg-type]
                temp_dir,
                human_seat=0,
                seed=13,
                seat_models=[PassPolicy(), PassPolicy(), PassPolicy(), PassPolicy()],
                persist_logs=False,
            )
            game.new_round()
            first = {row["name"]: row for row in game.player_stat_summary()}
            self.assertEqual({row["rounds"] for row in first.values()}, {1})
            self.assertTrue(all(row["avg_opening_shanten"] is not None for row in first.values()))

            game.shuffle_seats(include_human=False)
            game.new_round()
            second = {row["name"]: row for row in game.player_stat_summary()}

            self.assertEqual(set(second), set(first))
            self.assertEqual({row["rounds"] for row in second.values()}, {2})
            self.assertTrue(all(row["avg_de_draws"] is not None for row in second.values()))
            self.assertTrue(all(row["avg_fan_flower_draws"] is not None for row in second.values()))


if __name__ == "__main__":
    unittest.main()

