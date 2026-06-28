from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path
from typing import Any


AI_ACCOUNTS = ("AI1", "AI2", "AI3")


class BattleDatabase:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        for name in AI_ACCOUNTS:
            self.ensure_account(name, is_ai=True)

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        with closing(self.connect()) as con, con:
            con.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS accounts (
                    account_name TEXT PRIMARY KEY,
                    is_ai INTEGER NOT NULL DEFAULT 0,
                    created_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS battle_stats (
                    account_name TEXT NOT NULL,
                    period TEXT NOT NULL,
                    rounds INTEGER NOT NULL DEFAULT 0,
                    opening_shanten_total REAL NOT NULL DEFAULT 0,
                    de_draw_total INTEGER NOT NULL DEFAULT 0,
                    fan_flower_draw_total INTEGER NOT NULL DEFAULT 0,
                    normal_wins INTEGER NOT NULL DEFAULT 0,
                    leizi_wins INTEGER NOT NULL DEFAULT 0,
                    win_turn_total REAL NOT NULL DEFAULT 0,
                    win_point_total REAL NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_name, period),
                    FOREIGN KEY (account_name) REFERENCES accounts(account_name)
                );
                """
            )
            self._ensure_stat_columns(con)

    @staticmethod
    def _ensure_stat_columns(con: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in con.execute("PRAGMA table_info(battle_stats)").fetchall()}
        migrations = {
            "win_turn_total": "ALTER TABLE battle_stats ADD COLUMN win_turn_total REAL NOT NULL DEFAULT 0",
            "win_point_total": "ALTER TABLE battle_stats ADD COLUMN win_point_total REAL NOT NULL DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in existing:
                con.execute(sql)

    @staticmethod
    def today() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    def ensure_account(self, account_name: str, is_ai: bool = False) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        now = time.time()
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO accounts(account_name, is_ai, created_at)
                VALUES(?, ?, ?)
                ON CONFLICT(account_name) DO UPDATE SET is_ai = MAX(is_ai, excluded.is_ai)
                """,
                (name, 1 if is_ai else 0, now),
            )
            row = con.execute("SELECT * FROM accounts WHERE account_name = ?", (name,)).fetchone()
        return dict(row)

    @staticmethod
    def normalize_account(account_name: str) -> str:
        name = str(account_name or "").strip()
        if not name:
            raise ValueError("账号名不能为空")
        if len(name) > 24:
            raise ValueError("账号名最多 24 个字符")
        if any(ch.isspace() for ch in name):
            raise ValueError("账号名不能包含空白字符")
        return name

    def record_opening(
        self,
        account_name: str,
        opening_shanten: int,
        de_draws: int,
        fan_flower_draws: int,
    ) -> None:
        name = self.normalize_account(account_name)
        self.ensure_account(name, is_ai=name in AI_ACCOUNTS)
        for period in ("all", self.today()):
            self._upsert_stat_delta(
                name,
                period,
                rounds=1,
                opening_shanten_total=float(opening_shanten),
                de_draw_total=int(de_draws),
                fan_flower_draw_total=int(fan_flower_draws),
            )

    def record_win(
        self,
        account_name: str,
        win_type: str,
        win_turn: int | None = None,
        win_points: int | None = None,
    ) -> None:
        name = self.normalize_account(account_name)
        self.ensure_account(name, is_ai=name in AI_ACCOUNTS)
        leizi = "劣子" in str(win_type) or "leizi" in str(win_type).lower()
        for period in ("all", self.today()):
            self._upsert_stat_delta(
                name,
                period,
                leizi_wins=1 if leizi else 0,
                normal_wins=0 if leizi else 1,
                win_turn_total=float(win_turn) if win_turn is not None else 0.0,
                win_point_total=float(win_points) if win_points is not None else 0.0,
            )

    def _upsert_stat_delta(
        self,
        account_name: str,
        period: str,
        rounds: int = 0,
        opening_shanten_total: float = 0.0,
        de_draw_total: int = 0,
        fan_flower_draw_total: int = 0,
        normal_wins: int = 0,
        leizi_wins: int = 0,
        win_turn_total: float = 0.0,
        win_point_total: float = 0.0,
    ) -> None:
        now = time.time()
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO battle_stats(
                    account_name, period, rounds, opening_shanten_total,
                    de_draw_total, fan_flower_draw_total, normal_wins, leizi_wins,
                    win_turn_total, win_point_total, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_name, period) DO UPDATE SET
                    rounds = rounds + excluded.rounds,
                    opening_shanten_total = opening_shanten_total + excluded.opening_shanten_total,
                    de_draw_total = de_draw_total + excluded.de_draw_total,
                    fan_flower_draw_total = fan_flower_draw_total + excluded.fan_flower_draw_total,
                    normal_wins = normal_wins + excluded.normal_wins,
                    leizi_wins = leizi_wins + excluded.leizi_wins,
                    win_turn_total = win_turn_total + excluded.win_turn_total,
                    win_point_total = win_point_total + excluded.win_point_total,
                    updated_at = excluded.updated_at
                """,
                (
                    account_name,
                    period,
                    rounds,
                    opening_shanten_total,
                    de_draw_total,
                    fan_flower_draw_total,
                    normal_wins,
                    leizi_wins,
                    win_turn_total,
                    win_point_total,
                    now,
                ),
            )

    def stats_for_accounts(self, account_names: list[str]) -> list[dict[str, Any]]:
        names: list[str] = []
        seen: set[str] = set()
        for raw_name in account_names:
            if not str(raw_name or "").strip():
                continue
            name = self.normalize_account(raw_name)
            if name in seen:
                continue
            seen.add(name)
            names.append(name)
        if not names:
            return []
        with closing(self.connect()) as con, con:
            rows = con.execute(
                f"""
                SELECT * FROM battle_stats
                WHERE account_name IN ({",".join("?" for _ in names)})
                  AND period IN ('all', ?)
                """,
                (*names, self.today()),
            ).fetchall()
        by_key = {(row["account_name"], row["period"]): dict(row) for row in rows}
        return [
            {
                "account": name,
                "all": self._format_stat(by_key.get((name, "all"))),
                "today": self._format_stat(by_key.get((name, self.today()))),
            }
            for name in names
        ]

    def accounts(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as con, con:
            rows = con.execute(
                """
                SELECT account_name, is_ai, created_at
                FROM accounts
                ORDER BY is_ai DESC, account_name COLLATE NOCASE
                """
            ).fetchall()
        names = [str(row["account_name"]) for row in rows]
        stats = {row["account"]: row for row in self.stats_for_accounts(names)}
        return [
            {
                "account": row["account_name"],
                "is_ai": bool(row["is_ai"]),
                "created_at": row["created_at"],
                "stats": stats.get(row["account_name"], {"all": self._format_stat(None), "today": self._format_stat(None)}),
            }
            for row in rows
        ]

    def reset_stats(self) -> dict[str, Any]:
        with closing(self.connect()) as con, con:
            deleted = con.execute("DELETE FROM battle_stats").rowcount
        return {"ok": True, "deleted": int(deleted or 0)}

    @staticmethod
    def _format_stat(row: dict[str, Any] | None) -> dict[str, Any]:
        if not row:
            return {
                "rounds": 0,
                "avg_opening_shanten": None,
                "avg_de_draws": None,
                "avg_fan_flower_draws": None,
                "normal_win_rate": None,
                "leizi_win_rate": None,
                "win_rate": None,
                "avg_win_turn": None,
                "avg_win_points": None,
                "wins": 0,
                "normal_wins": 0,
                "leizi_wins": 0,
                "luck_score": None,
            }
        rounds = int(row.get("rounds") or 0)
        normal_wins = int(row.get("normal_wins") or 0)
        leizi_wins = int(row.get("leizi_wins") or 0)
        wins = normal_wins + leizi_wins
        return {
            "rounds": rounds,
            "avg_opening_shanten": round(float(row["opening_shanten_total"]) / rounds, 3) if rounds else None,
            "avg_de_draws": round(float(row["de_draw_total"]) / rounds, 3) if rounds else None,
            "avg_fan_flower_draws": round(float(row["fan_flower_draw_total"]) / rounds, 3) if rounds else None,
            "normal_win_rate": round(normal_wins / rounds, 4) if rounds else None,
            "leizi_win_rate": round(leizi_wins / rounds, 4) if rounds else None,
            "win_rate": round(wins / rounds, 4) if rounds else None,
            "avg_win_turn": round(float(row.get("win_turn_total") or 0) / wins, 3) if wins else None,
            "avg_win_points": round(float(row.get("win_point_total") or 0) / wins, 3) if wins else None,
            "wins": wins,
            "normal_wins": normal_wins,
            "leizi_wins": leizi_wins,
            "luck_score": None,
        }

    def info(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "tables": ["accounts", "battle_stats"],
            "note": "SQLite 数据库可直接用 sqlite3、DB Browser for SQLite 或脚本打开。",
        }

