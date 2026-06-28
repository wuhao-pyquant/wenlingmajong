from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from wenling_lan_host.battle_db import BattleDatabase
from wenling_core.game import WenlingMahjongGame


class PassPolicy:
    def choose_action(self, observation: dict, legal_actions: list[dict], explore: float = 0.0) -> dict:
        return next((action for action in legal_actions if action.get("type") == "pass"), legal_actions[0])


class BattleStatsTests(unittest.TestCase):
    def test_database_records_win_rate_turn_and_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.record_opening("alice", opening_shanten=2, de_draws=1, fan_flower_draws=0)
            db.record_opening("alice", opening_shanten=4, de_draws=3, fan_flower_draws=2)
            db.record_win("alice", "普通和牌", win_turn=3, win_points=160)
            db.record_win("alice", "劣子和", win_turn=5, win_points=300)

            stats = db.stats_for_accounts(["alice"])[0]
            for period in ("all", "today"):
                row = stats[period]
                self.assertEqual(row["rounds"], 2)
                self.assertEqual(row["wins"], 2)
                self.assertEqual(row["normal_wins"], 1)
                self.assertEqual(row["leizi_wins"], 1)
                self.assertEqual(row["win_rate"], 1.0)
                self.assertEqual(row["normal_win_rate"], 0.5)
                self.assertEqual(row["leizi_win_rate"], 0.5)
                self.assertEqual(row["avg_win_turn"], 4.0)
                self.assertEqual(row["avg_win_points"], 230.0)

    def test_database_migrates_existing_stats_table(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "battle.sqlite3"
            with closing(sqlite3.connect(path)) as con, con:
                con.executescript(
                    """
                    CREATE TABLE accounts (
                        account_name TEXT PRIMARY KEY,
                        is_ai INTEGER NOT NULL DEFAULT 0,
                        created_at REAL NOT NULL
                    );
                    CREATE TABLE battle_stats (
                        account_name TEXT NOT NULL,
                        period TEXT NOT NULL,
                        rounds INTEGER NOT NULL DEFAULT 0,
                        opening_shanten_total REAL NOT NULL DEFAULT 0,
                        de_draw_total INTEGER NOT NULL DEFAULT 0,
                        fan_flower_draw_total INTEGER NOT NULL DEFAULT 0,
                        normal_wins INTEGER NOT NULL DEFAULT 0,
                        leizi_wins INTEGER NOT NULL DEFAULT 0,
                        updated_at REAL NOT NULL,
                        PRIMARY KEY (account_name, period)
                    );
                    """
                )

            db = BattleDatabase(path)
            db.record_opening("bob", opening_shanten=1, de_draws=0, fan_flower_draws=0)
            db.record_win("bob", "普通和牌", win_turn=2, win_points=120)
            row = db.stats_for_accounts(["bob"])[0]["all"]
            self.assertEqual(row["win_rate"], 1.0)
            self.assertEqual(row["avg_win_turn"], 2.0)
            self.assertEqual(row["avg_win_points"], 120.0)

    def test_game_settlement_records_winner_turn_and_points(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            game.new_round()
            game.round_stats[1]["draw_turns"] = 3
            before = {row["name"]: row for row in game.player_stat_summary()}[game.players[1].name]
            before_wins = int(before["wins"])

            game._finish_win(1, "普通和牌")

            settlement = game.settlement or {}
            self.assertEqual(settlement["win_turn"], 3)
            self.assertEqual(settlement["win_points"], settlement["scores"][1]["total"])
            rows = {row["name"]: row for row in game.player_stat_summary()}
            winner = rows[game.players[1].name]
            self.assertEqual(winner["wins"], before_wins + 1)
            self.assertGreaterEqual(winner["win_rate"], 1.0)
            self.assertIsNotNone(winner["avg_win_turn"])
            self.assertIsNotNone(winner["avg_win_points"])

    def test_opening_win_turn_is_one_for_dealer_and_zero_for_others(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            dealer_game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            dealer_game.dealer = 2
            dealer_game.round_stats = [dealer_game._empty_round_stats() for _ in range(4)]
            dealer_game._initialize_opening_turn_counts()
            dealer_game._finish_win(2, "普通和牌")
            self.assertEqual(dealer_game.settlement["win_turn"], 1)

        with tempfile.TemporaryDirectory() as temp_dir:
            non_dealer_game = WenlingMahjongGame(
                PassPolicy(),
                temp_dir,
                human_seat=None,
                persist_logs=False,
                response_delay_sec=0,
            )
            non_dealer_game.dealer = 2
            non_dealer_game.round_stats = [non_dealer_game._empty_round_stats() for _ in range(4)]
            non_dealer_game._initialize_opening_turn_counts()
            non_dealer_game._finish_win(1, "劣子和")
            self.assertEqual(non_dealer_game.settlement["win_turn"], 0)


if __name__ == "__main__":
    unittest.main()

