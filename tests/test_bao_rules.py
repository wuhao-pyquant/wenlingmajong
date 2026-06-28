from __future__ import annotations

import tempfile
import unittest
from collections import Counter

from wenling_core.game import WenlingMahjongGame


class PassPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return next((action for action in legal_actions if action.get("type") == "pass"), legal_actions[0])


def make_game() -> WenlingMahjongGame:
    game = WenlingMahjongGame(
        PassPolicy(),
        tempfile.mkdtemp(),
        human_seat=None,
        persist_logs=False,
        response_delay_sec=0,
    )
    game.de_indicator = "bai"
    game.de_set = {"bai"}
    game.flower_set = set()
    game.phase = "turn"
    game.current_player = 0
    for seat, player in enumerate(game.players):
        player.name = f"P{seat}"
        player.chips = 0
        player.hand.clear()
        player.flowers.clear()
        player.melds.clear()
        player.discards.clear()
    return game


class BaoRulesTests(unittest.TestCase):
    def test_wall_thresholds_follow_supplement_parity(self) -> None:
        game = make_game()
        game.wall = ["m1"] * 40

        game.supplement_count = 0
        game._update_wall_phase()
        self.assertEqual((game.bao_phase_wall_threshold, game.draw_wall_threshold), (32, 16))
        self.assertFalse(game.bao_phase)
        self.assertEqual(game._wall_to_draw_game(), 24)

        game.supplement_count = 1
        game._update_wall_phase()
        self.assertEqual((game.bao_phase_wall_threshold, game.draw_wall_threshold), (33, 17))
        self.assertEqual(game._wall_to_draw_game(), 23)

    def test_de_indicator_is_removed_from_live_tile_inventory(self) -> None:
        game = WenlingMahjongGame(
            PassPolicy(),
            tempfile.mkdtemp(),
            human_seat=None,
            persist_logs=False,
            response_delay_sec=0,
        )
        game.random.seed(7)
        game.new_round()

        live_count = game.wall.count(game.de_indicator)
        for player in game.players:
            live_count += player.hand.get(game.de_indicator, 0)
            live_count += player.flowers.count(game.de_indicator)
            live_count += player.discards.count(game.de_indicator)
            live_count += sum(meld.get("tiles", []).count(game.de_indicator) for meld in player.melds)

        self.assertLessEqual(live_count, 3)

    def test_wall_phase_enters_bao_and_draws_at_dynamic_thresholds(self) -> None:
        game = make_game()
        game.wall = ["m1"] * 32
        game.supplement_count = 0
        game._update_wall_phase()
        self.assertTrue(game.bao_phase)
        self.assertEqual(game.phase, "turn")

        game = make_game()
        game.wall = ["m1"] * 16
        game.supplement_count = 0
        game._update_wall_phase()
        self.assertEqual(game.phase, "round_over")
        self.assertIsNone(game.winner)

        game = make_game()
        game.wall = ["m1"] * 33
        game.supplement_count = 1
        game._update_wall_phase()
        self.assertTrue(game.bao_phase)
        self.assertEqual(game.phase, "turn")

        game = make_game()
        game.wall = ["m1"] * 17
        game.supplement_count = 1
        game._update_wall_phase()
        self.assertEqual(game.phase, "round_over")
        self.assertIsNone(game.winner)

    def test_supplement_draw_counts_and_enters_odd_bao_phase(self) -> None:
        game = make_game()
        game.wall = ["m1"] * 34

        tile = game._draw_supplement_tile(0, "测试补牌")

        self.assertEqual(tile, "m1")
        self.assertEqual(game.supplement_count, 1)
        self.assertEqual((game.bao_phase_wall_threshold, game.draw_wall_threshold), (33, 17))
        self.assertTrue(game.bao_phase)
        self.assertEqual(game._wall_to_draw_game(), 16)

    def test_bao_fields_are_exposed_to_observation_and_serialized_state(self) -> None:
        game = make_game()
        game.wall = ["m1"] * 33
        game.supplement_count = 1
        game._update_wall_phase()
        game._set_temporary_bao_after_open_claim(2, "d1")
        game.discarded_tile_kinds.update({"m2", "m3"})

        public = game.observation(0)["public"]
        state = game.serialize(viewer_seat=0)

        self.assertTrue(public["bao_phase"])
        self.assertEqual(public["wall_to_draw_game"], 16)
        self.assertEqual(public["center_indicator_mode"], "bao")
        self.assertEqual(public["temporary_bao"]["seat"], 2)
        self.assertEqual(state["temporary_bao"]["seat"], 2)
        self.assertEqual(state["center_indicator_mode"], "bao")
        self.assertEqual(state["discarded_tile_kinds"], ["m2", "m3"])

    def test_initial_flower_and_kong_supplements_are_counted(self) -> None:
        game = make_game()
        game.flower_set = {"rh1"}
        game.players[0].hand = Counter({"rh1": 1})
        game.wall = ["m1"] * 40
        game._initial_replenish_flowers()
        self.assertEqual(game.supplement_count, 1)
        self.assertEqual(game.players[0].flowers, ["rh1"])

        game = make_game()
        game.wall = ["m2"] * 40
        game._kong_supplement(0)
        self.assertEqual(game.supplement_count, 1)
        self.assertEqual(game.players[0].hand["m2"], 1)

    def test_discard_events_track_fresh_tile_even_after_claim(self) -> None:
        game = make_game()
        game.players[0].hand = Counter({"m1": 1})

        first = game._create_discard_event(0, "m1")
        game.players[0].discards.append("m1")
        game._mark_discard_claimed(0, "m1", 1, "chi")
        second = game._create_discard_event(0, "m1")

        self.assertTrue(first["is_fresh_tile"])
        self.assertFalse(second["is_fresh_tile"])
        self.assertEqual(first["claimed_by"], 1)

    def test_zhong_fa_ron_with_bad_shanten_triggers_bao(self) -> None:
        game = make_game()
        game.players[0].hand = Counter({"zhong": 1})
        event = game._create_discard_event(0, "zhong")
        event["shanten_before_discard"] = 2
        game.players[0].discards.append("zhong")

        game._finish_win(1, "普通和牌", discarder=0, win_tile="zhong")

        self.assertIsNotNone(game.settlement["bao"])
        self.assertEqual(game.settlement["bao"]["seat"], 0)
        self.assertEqual(game.settlement["scores"][0]["total"], 0)

    def test_zhong_fa_ron_with_shanten_one_does_not_trigger_bao(self) -> None:
        game = make_game()
        game.players[0].hand = Counter({"zhong": 1})
        event = game._create_discard_event(0, "zhong")
        event["shanten_before_discard"] = 1
        game.players[0].discards.append("zhong")

        game._finish_win(1, "普通和牌", discarder=0, win_tile="zhong")

        self.assertIsNone(game.settlement["bao"])

    def test_fa_ron_with_bad_shanten_triggers_bao(self) -> None:
        game = make_game()
        game.players[0].hand = Counter({"fa": 1})
        event = game._create_discard_event(0, "fa")
        event["shanten_before_discard"] = 2
        game.players[0].discards.append("fa")

        game._finish_win(1, "普通和牌", discarder=0, win_tile="fa")

        self.assertEqual(game.settlement["bao"]["seat"], 0)

    def test_bao_phase_fresh_tile_ron_triggers_bao(self) -> None:
        game = make_game()
        game.bao_phase = True
        game.players[2].hand = Counter({"m9": 1})
        game._create_discard_event(2, "m9")
        game.players[2].discards.append("m9")

        game._finish_win(1, "普通和牌", discarder=2, win_tile="m9")

        self.assertEqual(game.settlement["bao"]["seat"], 2)
        self.assertIn("生牌", game.settlement["bao"]["reason"])

    def test_fresh_tile_condition_only_applies_in_bao_phase_and_for_fresh_tiles(self) -> None:
        game = make_game()
        game.players[2].hand = Counter({"m9": 1})
        game._create_discard_event(2, "m9")
        game.players[2].discards.append("m9")
        game._finish_win(1, "普通和牌", discarder=2, win_tile="m9")
        self.assertIsNone(game.settlement["bao"])

        game = make_game()
        game.bao_phase = True
        game.discarded_tile_kinds.add("m9")
        game.players[2].hand = Counter({"m9": 1})
        game._create_discard_event(2, "m9")
        game.players[2].discards.append("m9")
        game._finish_win(1, "普通和牌", discarder=2, win_tile="m9")
        self.assertIsNone(game.settlement["bao"])

    def test_three_consecutive_claims_create_targeted_bao_liability(self) -> None:
        game = make_game()
        for tile in ("m1", "m2", "m3"):
            game.players[0].hand = Counter({tile: 1})
            event = game._create_discard_event(0, tile)
            game.players[0].discards.append(tile)
            game._mark_discard_claimed(0, tile, 1, "peng")
            self.assertEqual(event["claimed_by"], 1)

        self.assertEqual(len(game.bao_liabilities), 1)
        self.assertEqual(game.bao_liabilities[0].liable_seat, 0)
        self.assertEqual(game.bao_liabilities[0].target_winner, 1)

        game._finish_win(1, "自摸")

        self.assertEqual(game.settlement["bao"]["seat"], 0)

    def test_two_consecutive_open_claims_show_public_warning_until_next_discard(self) -> None:
        game = make_game()
        for tile in ("m1", "m2"):
            event = game._create_discard_event(0, tile)
            game.players[0].discards.append(tile)
            game._mark_discard_claimed(0, tile, 1, "peng")
            self.assertEqual(event["claimed_by"], 1)

        self.assertEqual(game.claim_warnings[0]["claimed_by"], 1)
        self.assertEqual(game.observation(2)["public"]["players"][0]["claim_warning"]["claimed_by"], 1)
        self.assertEqual(game.serialize(viewer_seat=2)["players"][0]["claim_warning"]["claimed_by"], 1)

        third = game._create_discard_event(0, "m3")
        self.assertTrue(third["cleared_claim_warning"])
        self.assertNotIn(0, game.claim_warnings)
        game.players[0].discards.append("m3")
        game._mark_discard_claimed(0, "m3", 1, "peng")
        self.assertNotIn(0, game.claim_warnings)
        self.assertEqual(len(game.bao_liabilities), 1)

    def test_two_claim_warning_uses_latest_two_open_claims_after_prior_warning_clears(self) -> None:
        game = make_game()
        for tile in ("m1", "m2"):
            game._create_discard_event(0, tile)
            game.players[0].discards.append(tile)
            game._mark_discard_claimed(0, tile, 1, "peng")
        self.assertIn(0, game.claim_warnings)

        game._create_discard_event(0, "m3")
        game.players[0].discards.append("m3")
        game._mark_discard_claimed(0, "m3", 2, "peng")
        self.assertNotIn(0, game.claim_warnings)

        game._create_discard_event(0, "m4")
        game.players[0].discards.append("m4")
        game._mark_discard_claimed(0, "m4", 2, "chi")
        self.assertEqual(game.claim_warnings[0]["claimed_by"], 2)

    def test_three_consecutive_claim_streak_resets_on_unclaimed_discard(self) -> None:
        game = make_game()
        for tile in ("m1", "m2"):
            event = game._create_discard_event(0, tile)
            game.players[0].discards.append(tile)
            game._mark_discard_claimed(0, tile, 1, "peng")
            self.assertEqual(event["claimed_by"], 1)

        game._create_discard_event(0, "m3")
        game.players[0].discards.append("m3")
        game._mark_latest_discard_unclaimed(0, "m3")

        for tile in ("m4", "m5"):
            game._create_discard_event(0, tile)
            game.players[0].discards.append(tile)
            game._mark_discard_claimed(0, tile, 1, "peng")

        self.assertFalse(game.bao_liabilities)

    def test_temporary_bao_after_open_claim_applies_until_self_draw_or_other_claim(self) -> None:
        game = make_game()
        game.bao_phase = True

        game._set_temporary_bao_after_open_claim(2, "d1")
        game._finish_win(1, "自摸")
        self.assertEqual(game.settlement["bao"]["seat"], 2)

        game = make_game()
        game.bao_phase = True
        game._set_temporary_bao_after_open_claim(2, "d1")
        game._clear_temporary_bao_for_draw(2)
        game._finish_win(1, "自摸")
        self.assertIsNone(game.settlement["bao"])

    def test_temporary_bao_is_replaced_by_later_open_claim(self) -> None:
        game = make_game()
        game.bao_phase = True
        game._set_temporary_bao_after_open_claim(2, "d1")
        game._set_temporary_bao_after_open_claim(3, "d2")
        game._finish_win(1, "自摸")
        self.assertEqual(game.settlement["bao"]["seat"], 3)
        self.assertEqual(game.settlement["bao"]["source_event_id"], "d2")

    def test_earliest_applicable_bao_liability_wins(self) -> None:
        game = make_game()
        game._add_bao_liability(0, 1, "先发生的三连响应包牌", "d1")
        game.bao_phase = True
        game.players[2].hand = Counter({"m9": 1})
        game._create_discard_event(2, "m9")
        game.players[2].discards.append("m9")

        game._finish_win(1, "普通和牌", discarder=2, win_tile="m9")

        self.assertEqual(game.settlement["bao"]["seat"], 0)
        self.assertEqual(game.settlement["bao"]["source_event_id"], "d1")

    def test_bao_redirects_all_base_transactions_to_bao_player(self) -> None:
        game = make_game()
        scores = [
            {"total": 0},
            {"total": 160},
            {"total": 30},
            {"total": 80},
        ]
        bao = game._add_bao_liability(0, 1, "测试包牌", "d1")

        base = game._build_base_transactions(scores, winner=1)
        redirected = game._build_settlement_transactions(scores, winner=1, bao=bao)

        self.assertGreater(len(base), 0)
        self.assertTrue(all(transaction["from"] == 0 for transaction in redirected))
        self.assertTrue(all(transaction["to"] != 0 for transaction in redirected))
        deltas = game._deltas_from_transactions(redirected)
        self.assertLess(deltas[0], 0)
        self.assertTrue(all(delta >= 0 for delta in deltas[1:]))

    def test_base_transactions_use_full_points_without_dividing_by_ten(self) -> None:
        game = make_game()
        scores = [
            {"total": 100},
            {"total": 160},
            {"total": 30},
            {"total": 80},
        ]

        transactions = game._build_base_transactions(scores, winner=1)
        amounts = sorted(transaction["amount"] for transaction in transactions)
        deltas = game._deltas_from_transactions(transactions)

        self.assertIn(160, amounts)
        self.assertIn(70, amounts)
        self.assertEqual(deltas, [-70, 480, -280, -130])

    def test_no_bao_transactions_match_base_transactions(self) -> None:
        game = make_game()
        scores = [
            {"total": 100},
            {"total": 160},
            {"total": 30},
            {"total": 80},
        ]

        self.assertEqual(game._build_settlement_transactions(scores, winner=1), game._build_base_transactions(scores, winner=1))

    def test_leizi_win_can_use_bao_payment_rule(self) -> None:
        game = make_game()
        game._add_bao_liability(0, 1, "测试劣子胡包牌", "d1")

        game._finish_win(1, "劣子和")

        self.assertEqual(game.settlement["bao"]["seat"], 0)
        self.assertEqual(game.settlement["scores"][0]["total"], 0)


if __name__ == "__main__":
    unittest.main()

