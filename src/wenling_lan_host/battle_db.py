from __future__ import annotations

import re
import sqlite3
import time
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any


AI_ACCOUNTS = ("AI1", "AI2", "AI3")
ACCOUNT_NAME_MAX_LENGTH = 24
PUBLIC_ACCOUNT_NAME_MAX_LENGTH = 12
INVITE_CODE_RE = re.compile(r"^[A-Z0-9]{4,6}$")


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
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        return con

    def _init_schema(self) -> None:
        with closing(self.connect()) as con, con:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    account_name TEXT PRIMARY KEY,
                    is_ai INTEGER NOT NULL DEFAULT 0,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    role TEXT NOT NULL DEFAULT 'player',
                    password_hash TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    last_login_at REAL
                );
                CREATE TABLE IF NOT EXISTS invite_codes (
                    code TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    max_uses INTEGER,
                    used_count INTEGER NOT NULL DEFAULT 0,
                    created_by TEXT,
                    created_at REAL NOT NULL,
                    disabled_at REAL
                );
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    actor TEXT,
                    target TEXT,
                    details_json TEXT NOT NULL DEFAULT '{}',
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
                    luck_score_total REAL NOT NULL DEFAULT 0,
                    luck_score_count INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (account_name, period),
                    FOREIGN KEY (account_name) REFERENCES accounts(account_name)
                );
                """
            )
            self._migrate_schema(con)
            self._ensure_stat_columns(con)

    @staticmethod
    def _migrate_schema(con: sqlite3.Connection) -> None:
        table_migrations = {
            "accounts": {
                "enabled": "ALTER TABLE accounts ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
                "role": "ALTER TABLE accounts ADD COLUMN role TEXT NOT NULL DEFAULT 'player'",
                "password_hash": "ALTER TABLE accounts ADD COLUMN password_hash TEXT NOT NULL DEFAULT ''",
                "last_login_at": "ALTER TABLE accounts ADD COLUMN last_login_at REAL",
            },
            "invite_codes": {
                "enabled": "ALTER TABLE invite_codes ADD COLUMN enabled INTEGER NOT NULL DEFAULT 1",
                "max_uses": "ALTER TABLE invite_codes ADD COLUMN max_uses INTEGER",
                "used_count": "ALTER TABLE invite_codes ADD COLUMN used_count INTEGER NOT NULL DEFAULT 0",
                "created_by": "ALTER TABLE invite_codes ADD COLUMN created_by TEXT",
                "created_at": "ALTER TABLE invite_codes ADD COLUMN created_at REAL NOT NULL DEFAULT 0",
                "disabled_at": "ALTER TABLE invite_codes ADD COLUMN disabled_at REAL",
            },
            "audit_events": {
                "actor": "ALTER TABLE audit_events ADD COLUMN actor TEXT",
                "target": "ALTER TABLE audit_events ADD COLUMN target TEXT",
                "details_json": "ALTER TABLE audit_events ADD COLUMN details_json TEXT NOT NULL DEFAULT '{}'",
                "created_at": "ALTER TABLE audit_events ADD COLUMN created_at REAL NOT NULL DEFAULT 0",
            },
        }
        for table_name, migrations in table_migrations.items():
            existing = {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()}
            for column, sql in migrations.items():
                if column not in existing:
                    con.execute(sql)

    @staticmethod
    def _ensure_stat_columns(con: sqlite3.Connection) -> None:
        existing = {str(row["name"]) for row in con.execute("PRAGMA table_info(battle_stats)").fetchall()}
        migrations = {
            "win_turn_total": "ALTER TABLE battle_stats ADD COLUMN win_turn_total REAL NOT NULL DEFAULT 0",
            "win_point_total": "ALTER TABLE battle_stats ADD COLUMN win_point_total REAL NOT NULL DEFAULT 0",
            "luck_score_total": "ALTER TABLE battle_stats ADD COLUMN luck_score_total REAL NOT NULL DEFAULT 0",
            "luck_score_count": "ALTER TABLE battle_stats ADD COLUMN luck_score_count INTEGER NOT NULL DEFAULT 0",
        }
        for column, sql in migrations.items():
            if column not in existing:
                con.execute(sql)

    @staticmethod
    def today() -> str:
        return time.strftime("%Y-%m-%d", time.localtime())

    @staticmethod
    def normalize_account(account_name: str) -> str:
        name = unicodedata.normalize("NFC", str(account_name or "")).strip()
        if not name:
            raise ValueError("用户名不能为空")
        if len(name) > ACCOUNT_NAME_MAX_LENGTH:
            raise ValueError(f"用户名最长 {ACCOUNT_NAME_MAX_LENGTH} 个字符")
        if any(ch.isspace() for ch in name):
            raise ValueError("用户名不能包含空白字符")
        if any(unicodedata.category(ch).startswith("C") for ch in name):
            raise ValueError("用户名不能包含控制字符")
        return name

    @staticmethod
    def normalize_invite_code(invite_code: str) -> str:
        code = str(invite_code or "").strip().upper()
        if not code:
            raise ValueError("invite code required")
        if not INVITE_CODE_RE.fullmatch(code):
            raise ValueError("invite code must be 4-6 uppercase letters or digits")
        return code

    def _consume_invite_code(self, con: sqlite3.Connection, invite_code: str) -> str:
        code = self.normalize_invite_code(invite_code)
        row = con.execute(
            "SELECT code, enabled, max_uses, used_count FROM invite_codes WHERE code = ?",
            (code,),
        ).fetchone()
        if row is None:
            raise ValueError("invite code invalid")
        if not bool(row["enabled"]):
            raise ValueError("invite code disabled")
        max_uses = row["max_uses"]
        used_count = int(row["used_count"] or 0)
        if max_uses is not None and used_count >= int(max_uses):
            raise ValueError("invite code exhausted")
        used_count += 1
        disabled_at = None
        enabled = 1
        if max_uses is not None and used_count >= int(max_uses):
            enabled = 0
            disabled_at = time.time()
        con.execute(
            """
            UPDATE invite_codes
            SET enabled = ?, used_count = ?, disabled_at = ?
            WHERE code = ?
            """,
            (enabled, used_count, disabled_at, code),
        )
        return code

    def create_invite_code(self, code: str, created_by: str, max_uses: int | None = None) -> dict[str, Any]:
        normalized = self.normalize_invite_code(code)
        if max_uses is not None and int(max_uses) < 1:
            raise ValueError("invite code max_uses must be greater than 0")
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO invite_codes(code, enabled, max_uses, used_count, created_by, created_at, disabled_at)
                VALUES(?, 1, ?, 0, ?, ?, NULL)
                ON CONFLICT(code) DO UPDATE SET
                    enabled = 1,
                    max_uses = excluded.max_uses,
                    used_count = 0,
                    created_by = excluded.created_by,
                    created_at = excluded.created_at,
                    disabled_at = NULL
                """,
                (normalized, int(max_uses) if max_uses is not None else None, str(created_by or ""), time.time()),
            )
        return self.invite_code(normalized)

    def consume_invite_code(self, code: str) -> dict[str, Any]:
        normalized = self.normalize_invite_code(code)
        with closing(self.connect()) as con, con:
            self._consume_invite_code(con, normalized)
        return self.invite_code(normalized)

    def invite_code(self, code: str) -> dict[str, Any]:
        normalized = self.normalize_invite_code(code)
        with closing(self.connect()) as con:
            row = con.execute("SELECT * FROM invite_codes WHERE code = ?", (normalized,)).fetchone()
        if row is None:
            raise ValueError("invite code not found")
        return {
            "code": row["code"],
            "enabled": bool(row["enabled"]),
            "max_uses": row["max_uses"],
            "used_count": int(row["used_count"] or 0),
            "created_by": row["created_by"],
            "created_at": row["created_at"],
            "disabled_at": row["disabled_at"],
        }

    def invite_codes(self) -> list[dict[str, Any]]:
        with closing(self.connect()) as con:
            rows = con.execute("SELECT code FROM invite_codes ORDER BY created_at DESC, code").fetchall()
        return [self.invite_code(str(row["code"])) for row in rows]

    def disable_invite_code(self, code: str) -> dict[str, Any]:
        normalized = self.normalize_invite_code(code)
        with closing(self.connect()) as con, con:
            updated = con.execute(
                "UPDATE invite_codes SET enabled = 0, disabled_at = ? WHERE code = ?",
                (time.time(), normalized),
            ).rowcount
        if not updated:
            raise ValueError("invite code not found")
        return self.invite_code(normalized)

    def ensure_account(self, account_name: str, is_ai: bool = False) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        now = time.time()
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO accounts(account_name, is_ai, enabled, role, password_hash, created_at, last_login_at)
                VALUES(?, ?, 1, ?, '', ?, NULL)
                ON CONFLICT(account_name) DO UPDATE SET
                    is_ai = MAX(accounts.is_ai, excluded.is_ai),
                    role = CASE
                        WHEN excluded.is_ai = 1 THEN 'ai'
                        WHEN accounts.role IN ('admin', 'ai', 'player') THEN accounts.role
                        ELSE 'player'
                    END,
                    enabled = COALESCE(accounts.enabled, 1)
                """,
                (name, 1 if is_ai else 0, "ai" if is_ai else "player", now),
            )
        return self.account(name)

    def create_human_account(self, account_name: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        if len(name) > PUBLIC_ACCOUNT_NAME_MAX_LENGTH:
            raise ValueError(f"用户名最长 {PUBLIC_ACCOUNT_NAME_MAX_LENGTH} 个字符")
        if name in AI_ACCOUNTS:
            raise ValueError("该用户名为系统 AI 保留")
        return self.ensure_account(name, is_ai=False)

    def create_player_account(self, account_name: str, password_hash: str, invite_code: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        if len(name) > PUBLIC_ACCOUNT_NAME_MAX_LENGTH:
            raise ValueError(f"用户名最长 {PUBLIC_ACCOUNT_NAME_MAX_LENGTH} 个字符")
        if name in AI_ACCOUNTS:
            raise ValueError("该用户名为系统 AI 保留")
        if not str(password_hash or "").strip():
            raise ValueError("password hash required")
        with closing(self.connect()) as con, con:
            code = self._consume_invite_code(con, invite_code)
            try:
                con.execute(
                    """
                    INSERT INTO accounts(account_name, is_ai, enabled, role, password_hash, created_at, last_login_at)
                    VALUES(?, 0, 1, 'player', ?, ?, NULL)
                    """,
                    (name, str(password_hash), time.time()),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("account already exists") from exc
            con.execute(
                """
                INSERT INTO audit_events(event_type, actor, target, details_json, created_at)
                VALUES('player_account_created', ?, ?, ?, ?)
                """,
                (name, name, f'{{"invite_code":"{code}"}}', time.time()),
            )
        return self.account(name)

    def bootstrap_admin(self, username: str, password_hash: str) -> dict[str, Any]:
        name = self.normalize_account(username)
        if name in AI_ACCOUNTS:
            raise ValueError("管理员账号不能使用固定 AI 名称")
        if not str(password_hash or "").strip():
            raise ValueError("password hash required")
        now = time.time()
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO accounts(account_name, is_ai, enabled, role, password_hash, created_at, last_login_at)
                VALUES(?, 0, 1, 'admin', ?, ?, NULL)
                ON CONFLICT(account_name) DO UPDATE SET
                    is_ai = 0,
                    enabled = 1,
                    role = 'admin',
                    password_hash = excluded.password_hash
                """,
                (name, str(password_hash), now),
            )
        return self.account(name)

    def mark_login(self, account_name: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        with closing(self.connect()) as con, con:
            con.execute("UPDATE accounts SET last_login_at = ? WHERE account_name = ?", (time.time(), name))
        return self.account(name)

    def account(self, account_name: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        with closing(self.connect()) as con:
            row = con.execute(
                """
                SELECT account_name, is_ai, enabled, role, password_hash, created_at, last_login_at
                FROM accounts
                WHERE account_name = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            raise ValueError("账号不存在")
        return dict(row)

    def active_human_accounts(self) -> list[str]:
        with closing(self.connect()) as con:
            rows = con.execute(
                """
                SELECT account_name
                FROM accounts
                WHERE is_ai = 0 AND enabled = 1
                ORDER BY account_name COLLATE NOCASE
                """
            ).fetchall()
        return [str(row["account_name"]) for row in rows]

    def require_active_human_account(self, account_name: str) -> dict[str, Any]:
        row = self.account(account_name)
        if bool(row["is_ai"]):
            raise ValueError("AI 账号不能用于玩家登录")
        if not bool(row["enabled"]):
            raise ValueError("账号已停用 (disabled)")
        return row

    def set_account_enabled(self, account_name: str, enabled: bool) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        with closing(self.connect()) as con, con:
            row = con.execute(
                "SELECT is_ai FROM accounts WHERE account_name = ?",
                (name,),
            ).fetchone()
            if row is None:
                raise ValueError("账号不存在")
            if bool(row["is_ai"]):
                raise ValueError("固定 AI 账号不能修改")
            con.execute(
                "UPDATE accounts SET enabled = ? WHERE account_name = ?",
                (1 if enabled else 0, name),
            )
        return self.account(name)

    def create_backup(self, backup_dir: str | Path, *, keep: int = 10) -> Path:
        directory = Path(backup_dir)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime())
        destination = directory / f"battle-{stamp}-{time.time_ns() % 1_000_000_000:09d}.sqlite3"
        with closing(self.connect()) as source, closing(sqlite3.connect(destination)) as target:
            with target:
                source.backup(target)
        backups = sorted(directory.glob("battle-*.sqlite3"), key=lambda item: item.stat().st_mtime, reverse=True)
        for stale in backups[max(1, int(keep)):]:
            stale.unlink(missing_ok=True)
        return destination

    def clear_account_stats(self, account_name: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        row = self.account(name)
        if bool(row["is_ai"]):
            raise ValueError("固定 AI 账号不能清零")
        with closing(self.connect()) as con, con:
            deleted = con.execute(
                "DELETE FROM battle_stats WHERE account_name = ?",
                (name,),
            ).rowcount
        return {"ok": True, "account": name, "deleted": int(deleted or 0)}

    def delete_account(self, account_name: str) -> dict[str, Any]:
        name = self.normalize_account(account_name)
        row = self.account(name)
        if bool(row["is_ai"]):
            raise ValueError("固定 AI 账号不能删除")
        with closing(self.connect()) as con, con:
            con.execute("DELETE FROM battle_stats WHERE account_name = ?", (name,))
            deleted = con.execute("DELETE FROM accounts WHERE account_name = ?", (name,)).rowcount
        return {"ok": True, "account": name, "deleted": bool(deleted)}

    def merge_accounts(self, source_accounts: list[str], target_account: str) -> dict[str, Any]:
        target = self.normalize_account(target_account)
        sources: list[str] = []
        for raw_name in source_accounts:
            name = self.normalize_account(raw_name)
            if name != target and name not in sources:
                sources.append(name)
        if not sources:
            raise ValueError("至少选择一个不同于目标账号的来源账号")

        with closing(self.connect()) as con, con:
            placeholders = ",".join("?" for _ in [target, *sources])
            rows = con.execute(
                f"SELECT account_name, is_ai FROM accounts WHERE account_name IN ({placeholders})",
                (target, *sources),
            ).fetchall()
            by_name = {str(row["account_name"]): row for row in rows}
            missing = [name for name in [target, *sources] if name not in by_name]
            if missing:
                raise ValueError(f"账号不存在: {', '.join(missing)}")
            if any(bool(by_name[name]["is_ai"]) for name in [target, *sources]):
                raise ValueError("固定 AI 账号不能参与合并")

            stat_rows = con.execute(
                f"""
                SELECT period,
                       SUM(rounds) AS rounds,
                       SUM(opening_shanten_total) AS opening_shanten_total,
                       SUM(de_draw_total) AS de_draw_total,
                       SUM(fan_flower_draw_total) AS fan_flower_draw_total,
                       SUM(normal_wins) AS normal_wins,
                       SUM(leizi_wins) AS leizi_wins,
                       SUM(win_turn_total) AS win_turn_total,
                       SUM(win_point_total) AS win_point_total,
                       SUM(luck_score_total) AS luck_score_total,
                       SUM(luck_score_count) AS luck_score_count,
                       MAX(updated_at) AS updated_at
                FROM battle_stats
                WHERE account_name IN ({",".join("?" for _ in [target, *sources])})
                GROUP BY period
                """,
                (target, *sources),
            ).fetchall()
            con.execute(
                f"DELETE FROM battle_stats WHERE account_name IN ({','.join('?' for _ in [target, *sources])})",
                (target, *sources),
            )
            for stat in stat_rows:
                con.execute(
                    """
                    INSERT INTO battle_stats(
                        account_name, period, rounds, opening_shanten_total,
                        de_draw_total, fan_flower_draw_total, normal_wins,
                        leizi_wins, win_turn_total, win_point_total, updated_at,
                        luck_score_total, luck_score_count
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        target,
                        stat["period"],
                        stat["rounds"],
                        stat["opening_shanten_total"],
                        stat["de_draw_total"],
                        stat["fan_flower_draw_total"],
                        stat["normal_wins"],
                        stat["leizi_wins"],
                        stat["win_turn_total"],
                        stat["win_point_total"],
                        stat["updated_at"],
                        stat["luck_score_total"],
                        stat["luck_score_count"],
                    ),
                )
            con.execute(
                f"DELETE FROM accounts WHERE account_name IN ({','.join('?' for _ in sources)})",
                tuple(sources),
            )
        return {"ok": True, "target": target, "deleted_sources": sources}

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

    def record_hand_luck(self, account_name: str, luck_score: float) -> None:
        name = self.normalize_account(account_name)
        score = float(luck_score)
        if not 0.0 <= score <= 100.0:
            raise ValueError("运气度必须在 0-100 之间")
        self.ensure_account(name, is_ai=name in AI_ACCOUNTS)
        for period in ("all", self.today()):
            self._upsert_stat_delta(
                name,
                period,
                luck_score_total=score,
                luck_score_count=1,
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
        luck_score_total: float = 0.0,
        luck_score_count: int = 0,
    ) -> None:
        now = time.time()
        with closing(self.connect()) as con, con:
            con.execute(
                """
                INSERT INTO battle_stats(
                    account_name, period, rounds, opening_shanten_total,
                    de_draw_total, fan_flower_draw_total, normal_wins, leizi_wins,
                    win_turn_total, win_point_total, updated_at,
                    luck_score_total, luck_score_count
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_name, period) DO UPDATE SET
                    rounds = rounds + excluded.rounds,
                    opening_shanten_total = opening_shanten_total + excluded.opening_shanten_total,
                    de_draw_total = de_draw_total + excluded.de_draw_total,
                    fan_flower_draw_total = fan_flower_draw_total + excluded.fan_flower_draw_total,
                    normal_wins = normal_wins + excluded.normal_wins,
                    leizi_wins = leizi_wins + excluded.leizi_wins,
                    win_turn_total = win_turn_total + excluded.win_turn_total,
                    win_point_total = win_point_total + excluded.win_point_total,
                    luck_score_total = luck_score_total + excluded.luck_score_total,
                    luck_score_count = luck_score_count + excluded.luck_score_count,
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
                    luck_score_total,
                    luck_score_count,
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
                SELECT account_name, is_ai, enabled, role, created_at
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
                "enabled": bool(row["enabled"]),
                "role": row["role"],
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
                "luck_hands": 0,
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
            "luck_score": round(float(row.get("luck_score_total") or 0) / int(row.get("luck_score_count") or 0), 1)
            if int(row.get("luck_score_count") or 0)
            else None,
            "luck_hands": int(row.get("luck_score_count") or 0),
        }

    def info(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "tables": ["accounts", "invite_codes", "audit_events", "battle_stats"],
            "note": "SQLite database can be inspected directly with sqlite3 or DB Browser for SQLite.",
        }
