# Zeabur Online Lobby Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Zeabur-ready online lobby: password accounts, simple invite-code registration, admin monitoring, up to 3 concurrent rooms, room-owner controls, and a mature lobby/admin UI.

**Architecture:** Keep the existing Python standard-library HTTP server and static frontend. Add focused services around the current `BattleSession`: auth, invite codes, presence tracking, and an in-memory `RoomManager` that owns up to 3 `BattleRoom` instances. The first release runs as one process with SQLite on a Zeabur persistent volume.

**Tech Stack:** Python 3.12 standard library, SQLite, `unittest`, static HTML/CSS/JavaScript, Zeabur `PORT` and `/data` persistent volume.

## Global Constraints

- Do not migrate or preserve existing user, score, or room data.
- Do not introduce FastAPI, Flask, frontend build tooling, PostgreSQL, Redis, or multi-instance support in this release.
- Registration must require a simple invite code.
- Admin accounts must be initialized only from `WENLING_ADMIN_USERNAME` and `WENLING_ADMIN_PASSWORD`.
- Invite codes are short 4-6 character codes and admins can generate, disable, and inspect usage counts.
- Admins can monitor current logged-in users and unauthenticated visitors.
- Maximum active rooms defaults to 3 via `WENLING_MAX_ROOMS`.
- A player can own at most one active room.
- AI level is unified per room, not per AI seat.
- Room owners can kick and change AI only while waiting or after a round; during play they can only close the whole room with confirmation.
- A room close sends all players back to the lobby and makes the old room unusable.
- First release uses one service instance because SQLite and in-memory room state are not horizontally scalable.

---

## File Structure

- Modify `src/wenling_lan_host/battle_db.py`: replace LAN-only account schema with online account, invite, audit, and stats helpers while preserving BattleSession-facing methods such as `require_active_human_account()`, `stats_for_accounts()`, and stat recording.
- Modify `src/wenling_lan_host/auth.py`: replace account-selection login with password-based auth, role-aware session identities, and password hashing helpers.
- Create `src/wenling_lan_host/config.py`: central environment parsing for Zeabur and local defaults.
- Create `src/wenling_lan_host/presence.py`: in-memory visitor and online user tracker.
- Create `src/wenling_lan_host/rooms.py`: `BattleRoom` and `RoomManager`, wrapping existing `BattleSession` instances.
- Modify `src/wenling_lan_host/server.py`: wire config, auth, presence, rooms, new HTTP routes, static pages, Zeabur `PORT`, and admin authorization.
- Modify `static/battle_login.html`: password login and invite-code registration page.
- Modify `static/battle_lobby.js`: login/register state, room list, create room, enter room, room-owner controls.
- Modify `static/battle_app.js`: carry `room_id`, call `/api/battle/{room_id}/...`, detect closed rooms, return to lobby.
- Create `static/battle_admin.html`: admin dashboard shell.
- Create `static/battle_admin.js`: account, invite, room, and presence admin interactions.
- Modify `static/styles.css`: lobby/admin/game-hall visual refresh and responsive states.
- Create `zbpack.json`: Zeabur start command.
- Modify `README.md` and `docs/OPERATIONS.md`: Zeabur deployment and admin bootstrap instructions.
- Add tests:
  - `tests/test_online_auth.py`
  - `tests/test_invite_codes.py`
  - `tests/test_presence.py`
  - `tests/test_room_manager.py`
  - `tests/test_online_server.py`

## Task 1: Configuration and Online Database Schema

**Files:**
- Create: `src/wenling_lan_host/config.py`
- Modify: `src/wenling_lan_host/battle_db.py`
- Test: `tests/test_online_auth.py`

**Interfaces:**
- Produces: `HostConfig.from_env(environ: Mapping[str, str] | None = None) -> HostConfig`
- Produces: `BattleDatabase.bootstrap_admin(username: str, password_hash: str) -> dict[str, Any]`
- Produces: `BattleDatabase.create_player_account(account_name: str, password_hash: str, invite_code: str) -> dict[str, Any]`
- Produces: `BattleDatabase.account(account_name: str) -> dict[str, Any]` returning `account_name`, `is_ai`, `enabled`, `role`, `password_hash`, `created_at`, `last_login_at`
- Produces: `BattleDatabase.require_active_human_account(account_name: str) -> dict[str, Any]`
- Consumes: existing `AI_ACCOUNTS`, `BattleDatabase.normalize_account()`, and existing stat methods.

- [ ] **Step 1: Write failing config and schema tests**

Add this test file:

```python
# tests/test_online_auth.py
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.battle_db import AI_ACCOUNTS, BattleDatabase
from wenling_lan_host.config import HostConfig


class OnlineDatabaseTests(unittest.TestCase):
    def test_config_reads_zeabur_port_and_online_data_dir(self) -> None:
        config = HostConfig.from_env(
            {
                "PORT": "9001",
                "WENLING_DATA_DIR": "/data",
                "WENLING_ADMIN_USERNAME": "root",
                "WENLING_ADMIN_PASSWORD": "secret",
                "WENLING_INVITE_CODES": "7392,WL8K2",
                "WENLING_MAX_ROOMS": "3",
            }
        )

        self.assertEqual(config.port, 9001)
        self.assertEqual(config.data_dir, Path("/data"))
        self.assertEqual(config.admin_username, "root")
        self.assertEqual(config.admin_password, "secret")
        self.assertEqual(config.initial_invite_codes, ["7392", "WL8K2"])
        self.assertEqual(config.max_rooms, 3)

    def test_new_database_schema_has_roles_passwords_ai_and_invites(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            admin = db.bootstrap_admin("root", "hash-admin")
            player = db.create_player_account("alice", "hash-player", "7392")

            self.assertEqual(admin["role"], "admin")
            self.assertEqual(admin["password_hash"], "hash-admin")
            self.assertTrue(admin["enabled"])
            self.assertEqual(player["role"], "player")
            self.assertEqual(player["password_hash"], "hash-player")

            for ai_name in AI_ACCOUNTS:
                row = db.account(ai_name)
                self.assertTrue(row["is_ai"])
                self.assertEqual(row["role"], "ai")
                with self.assertRaisesRegex(ValueError, "AI"):
                    db.require_active_human_account(ai_name)

    def test_disabled_player_cannot_be_required_for_gameplay(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_player_account("alice", "hash-player", "7392")
            db.set_account_enabled("alice", False)

            with self.assertRaisesRegex(ValueError, "停用|disabled"):
                db.require_active_human_account("alice")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_auth -v`

Expected: FAIL because `wenling_lan_host.config` and new `BattleDatabase` methods do not exist.

- [ ] **Step 3: Add `HostConfig`**

Create `src/wenling_lan_host/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class HostConfig:
    host: str
    port: int
    data_dir: Path
    static_dir: Path
    public_base_url: str
    admin_username: str
    admin_password: str
    initial_invite_codes: list[str]
    max_rooms: int
    default_ai_policy: str
    allow_public_register: bool

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "HostConfig":
        env = dict(os.environ if environ is None else environ)
        invite_codes = [
            item.strip().upper()
            for item in str(env.get("WENLING_INVITE_CODES", "")).split(",")
            if item.strip()
        ]
        max_rooms = int(env.get("WENLING_MAX_ROOMS", "3") or "3")
        if max_rooms < 1 or max_rooms > 3:
            raise ValueError("WENLING_MAX_ROOMS must be between 1 and 3")
        return cls(
            host=str(env.get("WENLING_HOST", "0.0.0.0")),
            port=int(env.get("PORT") or env.get("WENLING_PORT") or "8765"),
            data_dir=Path(env.get("WENLING_DATA_DIR") or env.get("WENLING_LAN_DATA_DIR") or PROJECT_ROOT / "data"),
            static_dir=Path(env.get("WENLING_STATIC_DIR") or env.get("WENLING_LAN_STATIC_DIR") or PROJECT_ROOT / "static"),
            public_base_url=str(env.get("WENLING_PUBLIC_BASE_URL", "")).strip(),
            admin_username=str(env.get("WENLING_ADMIN_USERNAME", "admin")).strip() or "admin",
            admin_password=str(env.get("WENLING_ADMIN_PASSWORD", "")).strip(),
            initial_invite_codes=invite_codes,
            max_rooms=max_rooms,
            default_ai_policy=str(env.get("WENLING_DEFAULT_AI_POLICY", "low")).strip().lower() or "low",
            allow_public_register=str(env.get("WENLING_ALLOW_PUBLIC_REGISTER", "1")).strip().lower()
            not in {"0", "false", "no", "off"},
        )
```

- [ ] **Step 4: Replace account schema helpers**

In `src/wenling_lan_host/battle_db.py`, extend `_init_schema()` so `accounts` includes these columns from first creation:

```sql
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
```

Add or update these methods in `BattleDatabase`:

```python
def bootstrap_admin(self, username: str, password_hash: str) -> dict[str, Any]:
    name = self.normalize_account(username)
    if name in AI_ACCOUNTS:
        raise ValueError("管理员账号不能使用固定 AI 名称")
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
            (name, password_hash, now),
        )
    return self.account(name)

def create_player_account(self, account_name: str, password_hash: str, invite_code: str) -> dict[str, Any]:
    name = self.normalize_account(account_name)
    if len(name) > PUBLIC_ACCOUNT_NAME_MAX_LENGTH:
        raise ValueError(f"用户名最多 {PUBLIC_ACCOUNT_NAME_MAX_LENGTH} 个字符")
    if name in AI_ACCOUNTS:
        raise ValueError("该用户名为系统 AI 保留")
    now = time.time()
    with closing(self.connect()) as con, con:
        con.execute(
            """
            INSERT INTO accounts(account_name, is_ai, enabled, role, password_hash, created_at, last_login_at)
            VALUES(?, 0, 1, 'player', ?, ?, NULL)
            """,
            (name, password_hash, now),
        )
    return self.account(name)

def mark_login(self, account_name: str) -> dict[str, Any]:
    name = self.normalize_account(account_name)
    with closing(self.connect()) as con, con:
        con.execute("UPDATE accounts SET last_login_at = ? WHERE account_name = ?", (time.time(), name))
    return self.account(name)
```

Keep `create_human_account()` as a compatibility wrapper that raises a clear error in online mode or delegates to `create_player_account(account, "", "")` only for tests that still use `BattleSession.register()`.

- [ ] **Step 5: Run the config/schema tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_auth -v`

Expected: PASS.

- [ ] **Step 6: Run existing BattleSession tests that depend on database compatibility**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_battle_multiplayer -v`

Expected: PASS. If `BattleSession.register()` fails because `create_human_account()` changed too aggressively, restore compatibility by keeping `ensure_account(account, is_ai=False)` for internal test/game setup.

- [ ] **Step 7: Commit**

```powershell
git add src\wenling_lan_host\config.py src\wenling_lan_host\battle_db.py tests\test_online_auth.py
git commit -m "Add online config and account schema"
```

## Task 2: Password Auth, Invite Codes, and Role-Aware Sessions

**Files:**
- Modify: `src/wenling_lan_host/auth.py`
- Modify: `src/wenling_lan_host/battle_db.py`
- Test: `tests/test_online_auth.py`
- Test: `tests/test_invite_codes.py`

**Interfaces:**
- Consumes: `BattleDatabase.bootstrap_admin()`, `BattleDatabase.create_player_account()`, `BattleDatabase.account()`
- Produces: `hash_password(password: str) -> str`
- Produces: `verify_password(password: str, encoded_hash: str) -> bool`
- Produces: `AuthIdentity(account: str, role: str, token: str)`
- Produces: `PlayerSessionStore.login_password(account_name: str, password: str) -> dict[str, Any]`
- Produces: `PlayerSessionStore.register_player(account_name: str, password: str, invite_code: str) -> dict[str, Any]`
- Produces: `PlayerSessionStore.resolve_identity(token: str | None) -> AuthIdentity`
- Produces: `BattleDatabase.create_invite_code(code: str, created_by: str, max_uses: int | None = None) -> dict[str, Any]`
- Produces: `BattleDatabase.consume_invite_code(code: str) -> dict[str, Any]`
- Produces: `BattleDatabase.invite_codes() -> list[dict[str, Any]]`
- Produces: `BattleDatabase.disable_invite_code(code: str) -> dict[str, Any]`

- [ ] **Step 1: Write failing invite and password tests**

Add `tests/test_invite_codes.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.auth import PlayerSessionStore, hash_password, verify_password
from wenling_lan_host.battle_db import BattleDatabase


class InviteCodeTests(unittest.TestCase):
    def test_password_hash_round_trip_and_wrong_password_rejected(self) -> None:
        encoded = hash_password("secret123")

        self.assertTrue(verify_password("secret123", encoded))
        self.assertFalse(verify_password("wrong", encoded))
        self.assertNotIn("secret123", encoded)

    def test_register_consumes_invite_and_login_returns_role(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_invite_code("7392", created_by="root", max_uses=1)
            store = PlayerSessionStore(db)

            registered = store.register_player("alice", "secret123", "7392")
            self.assertEqual(registered["account"], "alice")
            self.assertEqual(registered["role"], "player")
            self.assertTrue(registered["session_token"])

            identity = store.resolve_identity(registered["session_token"])
            self.assertEqual(identity.account, "alice")
            self.assertEqual(identity.role, "player")

            with self.assertRaisesRegex(ValueError, "邀请码"):
                store.register_player("bob", "secret123", "7392")

    def test_admin_can_disable_invite_code(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db = BattleDatabase(Path(temp_dir) / "battle.sqlite3")
            db.create_invite_code("WL8K2", created_by="root")
            disabled = db.disable_invite_code("WL8K2")

            self.assertFalse(disabled["enabled"])
            with self.assertRaisesRegex(ValueError, "邀请码"):
                db.consume_invite_code("WL8K2")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run invite tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_invite_codes -v`

Expected: FAIL because password and invite helpers are missing.

- [ ] **Step 3: Implement password helpers and identities**

Replace `PlayerSessionStore` internals in `src/wenling_lan_host/auth.py` with role-aware login while keeping `resolve()` for existing call sites:

```python
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
from dataclasses import dataclass
from typing import Any

from .battle_db import BattleDatabase


PBKDF2_ITERATIONS = 210_000


@dataclass(frozen=True)
class AuthIdentity:
    account: str
    role: str
    token: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"


def hash_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 6:
        raise ValueError("密码至少 6 位")
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", value.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PBKDF2_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, encoded_hash: str) -> bool:
    try:
        scheme, iterations_raw, salt_raw, digest_raw = str(encoded_hash or "").split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("ascii"))
        expected = base64.b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", str(password or "").encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)
```

Update `PlayerSessionStore`:

```python
class PlayerSessionStore:
    def __init__(self, database: BattleDatabase):
        self.database = database
        self._lock = threading.RLock()
        self._token_to_identity: dict[str, AuthIdentity] = {}
        self._account_to_token: dict[str, str] = {}

    def register_player(self, account_name: str, password: str, invite_code: str) -> dict[str, Any]:
        self.database.consume_invite_code(invite_code)
        row = self.database.create_player_account(account_name, hash_password(password), invite_code)
        return self._issue(row)

    def login_password(self, account_name: str, password: str) -> dict[str, Any]:
        row = self.database.require_active_human_account(account_name)
        if not verify_password(password, str(row.get("password_hash") or "")):
            raise PermissionError("账号或密码错误")
        self.database.mark_login(str(row["account_name"]))
        return self._issue(row)

    def login(self, account_name: str) -> dict[str, Any]:
        raise PermissionError("线上模式需要密码登录")

    def resolve_identity(self, token: str | None) -> AuthIdentity:
        value = str(token or "").strip()
        if not value:
            raise PermissionError("需要登录")
        with self._lock:
            identity = self._token_to_identity.get(value)
        if identity is None:
            raise PermissionError("登录已失效，请重新登录")
        row = self.database.require_active_human_account(identity.account)
        return AuthIdentity(str(row["account_name"]), str(row["role"]), value)

    def resolve(self, token: str | None) -> str:
        return self.resolve_identity(token).account

    def logout(self, token: str | None) -> None:
        value = str(token or "").strip()
        if not value:
            return
        with self._lock:
            identity = self._token_to_identity.pop(value, None)
            if identity and self._account_to_token.get(identity.account) == value:
                self._account_to_token.pop(identity.account, None)

    def revoke_account(self, account_name: str) -> None:
        with self._lock:
            token = self._account_to_token.pop(account_name, None)
            if token:
                self._token_to_identity.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._token_to_identity.clear()
            self._account_to_token.clear()

    def _issue(self, row: dict[str, Any]) -> dict[str, Any]:
        account = str(row["account_name"])
        role = str(row.get("role") or "player")
        token = secrets.token_urlsafe(32)
        identity = AuthIdentity(account=account, role=role, token=token)
        with self._lock:
            previous = self._account_to_token.get(account)
            if previous:
                self._token_to_identity.pop(previous, None)
            self._account_to_token[account] = token
            self._token_to_identity[token] = identity
        return {"ok": True, "account": account, "role": role, "session_token": token}
```

- [ ] **Step 4: Implement invite-code database helpers**

Add to `BattleDatabase`:

```python
def create_invite_code(self, code: str, created_by: str, max_uses: int | None = None) -> dict[str, Any]:
    normalized = self.normalize_invite_code(code)
    if max_uses is not None and int(max_uses) < 1:
        raise ValueError("邀请码使用次数必须大于 0")
    with closing(self.connect()) as con, con:
        con.execute(
            """
            INSERT INTO invite_codes(code, enabled, max_uses, used_count, created_by, created_at, disabled_at)
            VALUES(?, 1, ?, 0, ?, ?, NULL)
            ON CONFLICT(code) DO UPDATE SET
                enabled = 1,
                max_uses = excluded.max_uses,
                created_by = excluded.created_by,
                disabled_at = NULL
            """,
            (normalized, int(max_uses) if max_uses is not None else None, created_by, time.time()),
        )
    return self.invite_code(normalized)

def consume_invite_code(self, code: str) -> dict[str, Any]:
    normalized = self.normalize_invite_code(code)
    with closing(self.connect()) as con, con:
        row = con.execute("SELECT * FROM invite_codes WHERE code = ?", (normalized,)).fetchone()
        if row is None or not bool(row["enabled"]):
            raise ValueError("邀请码无效")
        if row["max_uses"] is not None and int(row["used_count"]) >= int(row["max_uses"]):
            raise ValueError("邀请码使用次数已耗尽")
        con.execute("UPDATE invite_codes SET used_count = used_count + 1 WHERE code = ?", (normalized,))
    return self.invite_code(normalized)

def invite_code(self, code: str) -> dict[str, Any]:
    normalized = self.normalize_invite_code(code)
    with closing(self.connect()) as con:
        row = con.execute("SELECT * FROM invite_codes WHERE code = ?", (normalized,)).fetchone()
    if row is None:
        raise ValueError("邀请码不存在")
    return {
        "code": row["code"],
        "enabled": bool(row["enabled"]),
        "max_uses": row["max_uses"],
        "used_count": int(row["used_count"]),
        "created_by": row["created_by"],
        "created_at": row["created_at"],
        "disabled_at": row["disabled_at"],
    }

def invite_codes(self) -> list[dict[str, Any]]:
    with closing(self.connect()) as con:
        rows = con.execute("SELECT * FROM invite_codes ORDER BY created_at DESC, code").fetchall()
    return [self.invite_code(str(row["code"])) for row in rows]

def disable_invite_code(self, code: str) -> dict[str, Any]:
    normalized = self.normalize_invite_code(code)
    with closing(self.connect()) as con, con:
        con.execute("UPDATE invite_codes SET enabled = 0, disabled_at = ? WHERE code = ?", (time.time(), normalized))
    return self.invite_code(normalized)

@staticmethod
def normalize_invite_code(code: str) -> str:
    value = str(code or "").strip().upper()
    if not 4 <= len(value) <= 6:
        raise ValueError("邀请码必须是 4-6 位")
    if not value.isalnum():
        raise ValueError("邀请码只能包含字母和数字")
    return value
```

- [ ] **Step 5: Run auth and invite tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_online_auth tests.test_invite_codes -v
```

Expected: PASS.

- [ ] **Step 6: Run existing server token-spoofing test**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_lan_server.LanServerTests.test_player_login_uses_token_and_body_cannot_spoof_account -v`

Expected: FAIL until Task 5 updates HTTP auth routes. Do not force this to pass in this task; record the failure in the task notes.

- [ ] **Step 7: Commit**

```powershell
git add src\wenling_lan_host\auth.py src\wenling_lan_host\battle_db.py tests\test_online_auth.py tests\test_invite_codes.py
git commit -m "Add password auth and invite codes"
```

## Task 3: Presence Tracking and Admin Visibility

**Files:**
- Create: `src/wenling_lan_host/presence.py`
- Test: `tests/test_presence.py`

**Interfaces:**
- Produces: `PresenceTracker.touch(visitor_id: str, *, account: str | None, role: str | None, page: str, room_id: str | None, seat: int | None, ip: str, user_agent: str) -> dict[str, Any]`
- Produces: `PresenceTracker.snapshot(now: float | None = None) -> dict[str, Any]`
- Produces: `PresenceTracker.forget(visitor_id: str) -> None`

- [ ] **Step 1: Write failing presence tests**

Create `tests/test_presence.py`:

```python
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
```

- [ ] **Step 2: Run presence tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_presence -v`

Expected: FAIL because `PresenceTracker` is missing.

- [ ] **Step 3: Implement `PresenceTracker`**

Create `src/wenling_lan_host/presence.py`:

```python
from __future__ import annotations

import threading
import time
from typing import Any


class PresenceTracker:
    def __init__(self, *, online_sec: float = 45.0):
        self.online_sec = max(5.0, float(online_sec))
        self._lock = threading.RLock()
        self._visitors: dict[str, dict[str, Any]] = {}

    def touch(
        self,
        visitor_id: str,
        *,
        account: str | None,
        role: str | None,
        page: str,
        room_id: str | None,
        seat: int | None,
        ip: str,
        user_agent: str,
    ) -> dict[str, Any]:
        value = str(visitor_id or "").strip()
        if not value:
            value = f"guest-{int(time.time() * 1000)}"
        row = {
            "visitor_id": value,
            "account": account,
            "role": role,
            "page": str(page or ""),
            "room_id": room_id,
            "seat": seat,
            "ip": str(ip or ""),
            "user_agent": str(user_agent or "")[:240],
            "last_seen_at": time.time(),
        }
        with self._lock:
            self._visitors[value] = row
        return dict(row)

    def forget(self, visitor_id: str) -> None:
        with self._lock:
            self._visitors.pop(str(visitor_id or "").strip(), None)

    def snapshot(self, now: float | None = None) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            rows = [
                dict(row)
                for row in self._visitors.values()
                if current - float(row.get("last_seen_at") or 0.0) <= self.online_sec
            ]
        rows.sort(key=lambda row: float(row["last_seen_at"]), reverse=True)
        return {
            "online_count": len(rows),
            "logged_in_count": sum(1 for row in rows if row.get("account")),
            "visitors": rows,
        }
```

- [ ] **Step 4: Run presence tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_presence -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add src\wenling_lan_host\presence.py tests\test_presence.py
git commit -m "Add online presence tracking"
```

## Task 4: RoomManager with Owner/Admin Room Controls

**Files:**
- Create: `src/wenling_lan_host/rooms.py`
- Modify: `src/wenling_lan_host/battle_app.py`
- Test: `tests/test_room_manager.py`

**Interfaces:**
- Consumes: `BattleSession`, `BattleDatabase`, `AuthIdentity`
- Produces: `BattleRoom(room_id: str, room_name: str, owner_account: str, ai_policy: str, session: BattleSession, created_at: float, closed_at: float | None)`
- Produces: `RoomManager.create_room(owner_account: str, room_name: str | None = None, ai_policy: str | None = None) -> dict[str, Any]`
- Produces: `RoomManager.list_rooms(viewer: str | None = None) -> dict[str, Any]`
- Produces: `RoomManager.get_room(room_id: str) -> BattleRoom`
- Produces: `RoomManager.set_room_settings(room_id: str, actor: AuthIdentity, *, room_name: str | None = None, ai_policy: str | None = None) -> dict[str, Any]`
- Produces: `RoomManager.close_room(room_id: str, actor: AuthIdentity, *, confirm: str) -> dict[str, Any]`
- Produces: `RoomManager.kick(room_id: str, actor: AuthIdentity, target: str, room_generation: int | str | None = None) -> dict[str, Any]`

- [ ] **Step 1: Write failing room manager tests**

Create `tests/test_room_manager.py`:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wenling_lan_host.auth import AuthIdentity
from wenling_lan_host.battle_db import BattleDatabase
from wenling_lan_host.rooms import RoomManager


class RoomManagerTests(unittest.TestCase):
    def make_manager(self, max_rooms: int = 3) -> tuple[RoomManager, tempfile.TemporaryDirectory]:
        temp = tempfile.TemporaryDirectory()
        db = BattleDatabase(Path(temp.name) / "battle.sqlite3")
        for account in ("owner", "bob", "admin"):
            db.create_player_account(account, f"hash-{account}", "7392")
        db.bootstrap_admin("admin", "hash-admin")
        return RoomManager(db, Path(temp.name) / "logs", max_rooms=max_rooms, default_ai_policy="low"), temp

    def test_create_room_sets_owner_and_enforces_limits(self) -> None:
        manager, temp = self.make_manager(max_rooms=1)
        with temp:
            room = manager.create_room("owner", "第一桌")
            self.assertEqual(room["owner_account"], "owner")
            self.assertEqual(room["ai_policy"], "low")

            with self.assertRaisesRegex(ValueError, "只能拥有 1 个|already owns"):
                manager.create_room("owner", "第二桌")
            with self.assertRaisesRegex(ValueError, "房间已满|room limit"):
                manager.create_room("bob", "第二桌")

    def test_owner_and_admin_can_close_room_only_with_confirmation(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "第一桌")
            owner = AuthIdentity(account="owner", role="player", token="tok-owner")

            with self.assertRaisesRegex(ValueError, "二次确认|confirmation"):
                manager.close_room(room["room_id"], owner, confirm="")

            closed = manager.close_room(room["room_id"], owner, confirm="CLOSE_ROOM")
            self.assertEqual(closed["status"], "closed")
            self.assertEqual(manager.list_rooms()["rooms"], [])

    def test_non_owner_cannot_change_room_settings(self) -> None:
        manager, temp = self.make_manager()
        with temp:
            room = manager.create_room("owner", "第一桌")
            bob = AuthIdentity(account="bob", role="player", token="tok-bob")

            with self.assertRaises(PermissionError):
                manager.set_room_settings(room["room_id"], bob, ai_policy="high")

            admin = AuthIdentity(account="admin", role="admin", token="tok-admin")
            updated = manager.set_room_settings(room["room_id"], admin, ai_policy="high")
            self.assertEqual(updated["ai_policy"], "high")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run room manager tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_room_manager -v`

Expected: FAIL because `rooms.py` is missing.

- [ ] **Step 3: Add `close_room()` to `BattleSession`**

In `src/wenling_lan_host/battle_app.py`, add a public method near `close()`:

```python
def close_room(self, reason: str = "closed") -> dict[str, Any]:
    with self.condition:
        self._ensure_runtime_fields_locked()
        self._snapshot_game_chips_locked()
        self.game = None
        self.seats = [None, None, None, None]
        self.ready.clear()
        self.account_chips.clear()
        self._new_room_generation_locked(reason)
        self._bump_revision("room_closed", {"reason": reason})
        self.condition.notify_all()
        return self.serialize_for_account(None)
```

This method intentionally does not call `close()` because `close()` stops worker threads. `close_room()` clears playable state while the room object can still return a closed response until removed by `RoomManager`.

- [ ] **Step 4: Implement `RoomManager`**

Create `src/wenling_lan_host/rooms.py`:

```python
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from wenling_core.tile_efficiency import TileEfficiencyPolicyModel

from .auth import AuthIdentity
from .battle_app import AI_POLICY_ALIASES, DEFAULT_AI_POLICY, BattleSession
from .battle_db import BattleDatabase


@dataclass
class BattleRoom:
    room_id: str
    room_name: str
    owner_account: str
    ai_policy: str
    session: BattleSession
    created_at: float
    last_active_at: float
    closed_at: float | None = None

    @property
    def status(self) -> str:
        if self.closed_at is not None:
            return "closed"
        phase = self.session.game.phase if self.session.game is not None else None
        if phase == "round_over":
            return "round_over"
        if self.session.game is not None:
            return "playing"
        return "waiting"


class RoomManager:
    def __init__(
        self,
        database: BattleDatabase,
        log_dir: Path,
        *,
        max_rooms: int = 3,
        default_ai_policy: str = DEFAULT_AI_POLICY,
    ):
        self.database = database
        self.log_dir = Path(log_dir)
        self.max_rooms = max(1, min(3, int(max_rooms)))
        self.default_ai_policy = self._normalize_ai_policy(default_ai_policy)
        self._lock = threading.RLock()
        self._rooms: dict[str, BattleRoom] = {}

    def create_room(self, owner_account: str, room_name: str | None = None, ai_policy: str | None = None) -> dict[str, Any]:
        owner = self.database.require_active_human_account(owner_account)["account_name"]
        policy = self._normalize_ai_policy(ai_policy or self.default_ai_policy)
        with self._lock:
            if any(room.owner_account == owner and room.closed_at is None for room in self._rooms.values()):
                raise ValueError("同一玩家同时只能拥有 1 个活动房间")
            if len([room for room in self._rooms.values() if room.closed_at is None]) >= self.max_rooms:
                raise ValueError("活动房间已满")
            room_id = self._new_room_id_locked()
            session = BattleSession(
                self.database,
                str(self.log_dir / room_id),
                model_factory=lambda _policy=None: TileEfficiencyPolicyModel(),
                analysis_model_factory=TileEfficiencyPolicyModel,
                runtime_context={"room_id": room_id, "owner_account": owner},
            )
            session.set_ai_policy(policy)
            now = time.time()
            room = BattleRoom(
                room_id=room_id,
                room_name=str(room_name or f"{owner}的房间").strip()[:24] or f"{owner}的房间",
                owner_account=owner,
                ai_policy=policy,
                session=session,
                created_at=now,
                last_active_at=now,
            )
            self._rooms[room_id] = room
            return self._summary(room)

    def list_rooms(self, viewer: str | None = None) -> dict[str, Any]:
        with self._lock:
            rooms = [self._summary(room) for room in self._rooms.values() if room.closed_at is None]
        rooms.sort(key=lambda row: row["created_at"])
        return {"rooms": rooms, "max_rooms": self.max_rooms}

    def get_room(self, room_id: str) -> BattleRoom:
        key = str(room_id or "").strip().upper()
        with self._lock:
            room = self._rooms.get(key)
        if room is None or room.closed_at is not None:
            raise ValueError("房间不存在或已关闭")
        return room

    def set_room_settings(
        self,
        room_id: str,
        actor: AuthIdentity,
        *,
        room_name: str | None = None,
        ai_policy: str | None = None,
    ) -> dict[str, Any]:
        room = self.get_room(room_id)
        self._require_owner_or_admin(room, actor)
        if room.status == "playing":
            raise ValueError("对局中不能调整房间设置")
        if room_name is not None:
            room.room_name = str(room_name).strip()[:24] or room.room_name
        if ai_policy is not None:
            room.ai_policy = self._normalize_ai_policy(ai_policy)
            room.session.set_ai_policy(room.ai_policy)
        room.last_active_at = time.time()
        return self._summary(room)

    def close_room(self, room_id: str, actor: AuthIdentity, *, confirm: str) -> dict[str, Any]:
        room = self.get_room(room_id)
        self._require_owner_or_admin(room, actor)
        if confirm != "CLOSE_ROOM":
            raise ValueError("关闭房间需要二次确认")
        room.session.close_room("owner_closed" if actor.account == room.owner_account else "admin_closed")
        room.closed_at = time.time()
        room.last_active_at = room.closed_at
        return self._summary(room)

    def kick(self, room_id: str, actor: AuthIdentity, target: str, room_generation: int | str | None = None) -> dict[str, Any]:
        room = self.get_room(room_id)
        self._require_owner_or_admin(room, actor)
        if room.status == "playing":
            raise ValueError("对局中不能踢人")
        requester = room.owner_account if actor.role != "admin" else actor.account
        return room.session.kick(requester, target, room_generation)

    def close(self) -> None:
        with self._lock:
            rooms = list(self._rooms.values())
            self._rooms.clear()
        for room in rooms:
            room.session.close()

    def _summary(self, room: BattleRoom) -> dict[str, Any]:
        state = room.session.host_status()
        return {
            "room_id": room.room_id,
            "room_name": room.room_name,
            "owner_account": room.owner_account,
            "ai_policy": room.ai_policy,
            "status": room.status,
            "created_at": room.created_at,
            "last_active_at": room.last_active_at,
            "closed_at": room.closed_at,
            "seats": state["seats"],
            "ready_accounts": state["ready_accounts"],
            "game_started": state["game_started"],
            "room_generation": state["room_generation"],
            "room_revision": state["room_revision"],
        }

    def _require_owner_or_admin(self, room: BattleRoom, actor: AuthIdentity) -> None:
        if actor.role == "admin" or actor.account == room.owner_account:
            return
        raise PermissionError("只有房主或管理员可以管理该房间")

    def _new_room_id_locked(self) -> str:
        while True:
            value = secrets.token_hex(2).upper()
            if value not in self._rooms:
                return value

    @staticmethod
    def _normalize_ai_policy(policy: str | None) -> str:
        key = str(policy or "").strip().lower()
        normalized = AI_POLICY_ALIASES.get(key)
        if normalized is None:
            raise ValueError("AI 等级必须是 low 或 high")
        return normalized
```

- [ ] **Step 5: Run room manager and BattleSession tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_room_manager tests.test_battle_multiplayer -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add src\wenling_lan_host\rooms.py src\wenling_lan_host\battle_app.py tests\test_room_manager.py
git commit -m "Add multi-room manager"
```

## Task 5: Online HTTP API Wiring

**Files:**
- Modify: `src/wenling_lan_host/server.py`
- Modify: `src/wenling_lan_host/config.py`
- Test: `tests/test_online_server.py`
- Modify: `tests/test_lan_server.py` only where old passwordless login/register assumptions must change.

**Interfaces:**
- Consumes: `HostConfig`, `PlayerSessionStore`, `PresenceTracker`, `RoomManager`
- Produces HTTP routes:
  - `POST /api/auth/register`
  - `POST /api/auth/login`
  - `POST /api/auth/logout`
  - `GET /api/auth/me`
  - `GET /api/lobby/rooms`
  - `POST /api/lobby/rooms`
  - `POST /api/lobby/rooms/{room_id}/settings`
  - `POST /api/lobby/rooms/{room_id}/close`
  - `POST /api/lobby/rooms/{room_id}/kick`
  - `GET /api/battle/{room_id}/state`
  - `GET /api/battle/{room_id}/wait`
  - `POST /api/battle/{room_id}/heartbeat`
  - `POST /api/battle/{room_id}/sit`
  - `POST /api/battle/{room_id}/leave`
  - `POST /api/battle/{room_id}/ready`
  - `POST /api/battle/{room_id}/reset`
  - `POST /api/battle/{room_id}/action`
  - `POST /api/battle/{room_id}/report-bug`
  - `GET /api/admin/accounts`
  - `POST /api/admin/accounts/{account}/disable`
  - `POST /api/admin/accounts/{account}/enable`
  - `POST /api/admin/accounts/{account}/reset-password`
  - `GET /api/admin/invite-codes`
  - `POST /api/admin/invite-codes`
  - `POST /api/admin/invite-codes/{code}/disable`
  - `GET /api/admin/presence`

- [ ] **Step 1: Write failing online server tests**

Create `tests/test_online_server.py`:

```python
from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from wenling_lan_host.auth import hash_password
from wenling_lan_host.server import BattleApplication, ReusableThreadingHTTPServer, make_handler


ROOT = Path(__file__).resolve().parents[1]


class OnlineServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.application = BattleApplication(
            Path(self.temp.name),
            ROOT / "static",
            service_name="wenling-online-test",
            bind_host="127.0.0.1",
            bind_port=0,
            expose_host_info=True,
            admin_username="root",
            admin_password_hash=hash_password("admin123"),
            initial_invite_codes=["7392"],
            max_rooms=3,
        )
        self.server = ReusableThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.application))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.application.close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request_json(self, path: str, *, method: str = "GET", body: dict | None = None, token: str | None = None) -> dict:
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode("utf-8") if body is not None else None,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_register_login_create_room_and_enter_room_state(self) -> None:
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "alice", "password": "secret123", "invite_code": "7392"},
        )
        self.assertEqual(registered["role"], "player")
        token = registered["session_token"]

        created = self.request_json(
            "/api/lobby/rooms",
            method="POST",
            body={"room_name": "第一桌", "ai_policy": "low"},
            token=token,
        )
        room_id = created["room_id"]
        self.assertEqual(created["owner_account"], "alice")

        state = self.request_json(f"/api/battle/{room_id}/state", token=token)
        self.assertFalse(state["game_started"])
        self.assertEqual(state["room_id"], room_id)

    def test_admin_can_generate_invite_and_monitor_presence(self) -> None:
        login = self.request_json(
            "/api/auth/login",
            method="POST",
            body={"account": "root", "password": "admin123"},
        )
        admin_token = login["session_token"]
        generated = self.request_json(
            "/api/admin/invite-codes",
            method="POST",
            body={"code": "WL8K2", "max_uses": 2},
            token=admin_token,
        )
        self.assertEqual(generated["code"], "WL8K2")

        presence = self.request_json("/api/admin/presence", token=admin_token)
        self.assertIn("visitors", presence)

    def test_player_cannot_access_admin_routes(self) -> None:
        registered = self.request_json(
            "/api/auth/register",
            method="POST",
            body={"account": "alice", "password": "secret123", "invite_code": "7392"},
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.request_json("/api/admin/invite-codes", token=registered["session_token"])
        self.assertEqual(raised.exception.code, 403)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run online server tests and verify failure**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_server -v`

Expected: FAIL because routes and `BattleApplication` constructor arguments are missing.

- [ ] **Step 3: Extend `BattleApplication.__init__`**

In `server.py`, add optional keyword arguments:

```python
admin_username: str = "admin",
admin_password_hash: str = "",
initial_invite_codes: list[str] | None = None,
max_rooms: int = 3,
default_ai_policy: str = "low",
```

Inside the constructor:

```python
self.database = BattleDatabase(self.data_dir / "battle.sqlite3")
if admin_password_hash:
    self.database.bootstrap_admin(admin_username, admin_password_hash)
for code in initial_invite_codes or []:
    try:
        self.database.create_invite_code(code, created_by=admin_username)
    except ValueError:
        pass
self.player_sessions = PlayerSessionStore(self.database)
self.presence = PresenceTracker()
self.rooms = RoomManager(
    self.database,
    self.data_dir / "logs" / "rooms",
    max_rooms=max_rooms,
    default_ai_policy=default_ai_policy,
)
```

Keep `self.session = BattleSession(...)` only if legacy LAN routes must remain. If both exist, new online routes must use `self.rooms`, not `self.session`.

- [ ] **Step 4: Add handler helpers**

Add these helper methods inside `BattleHandler`:

```python
def _identity(self) -> AuthIdentity:
    return application.player_sessions.resolve_identity(self._bearer_token())

def _require_admin_identity(self) -> AuthIdentity:
    identity = self._identity()
    if identity.role != "admin":
        raise PermissionError("需要管理员权限")
    return identity

def _path_parts(self) -> list[str]:
    return [part for part in urlparse(self.path).path.split("/") if part]

def _touch_presence(self, identity: AuthIdentity | None = None, *, room_id: str | None = None, seat: int | None = None) -> None:
    token = self._bearer_token()
    visitor_id = token or str(self.headers.get("X-Visitor-ID") or self.client_address[0])
    account = identity.account if identity else None
    role = identity.role if identity else None
    application.presence.touch(
        visitor_id,
        account=account,
        role=role,
        page=urlparse(self.path).path,
        room_id=room_id,
        seat=seat,
        ip=str(self.client_address[0] if self.client_address else ""),
        user_agent=str(self.headers.get("User-Agent") or ""),
    )
```

Update exception handling so `PermissionError` maps to 403 for authenticated-but-forbidden admin checks and 401 for missing/invalid token. A simple rule is: if `_bearer_token()` exists, return 403; otherwise return 401.

- [ ] **Step 5: Add auth, lobby, battle, and admin routes**

In `do_GET()` and `do_POST()`, branch on `parts = self._path_parts()`.

Route examples:

```python
if path == "/api/auth/me":
    identity = self._identity()
    self._touch_presence(identity)
    self._json({"ok": True, "account": identity.account, "role": identity.role})
    return

if path == "/api/lobby/rooms":
    identity = self._identity()
    self._touch_presence(identity)
    self._json(application.rooms.list_rooms(identity.account))
    return

if len(parts) >= 3 and parts[:2] == ["api", "battle"]:
    identity = self._identity()
    room_id = parts[2]
    room = application.rooms.get_room(room_id)
    action = parts[3] if len(parts) > 3 else ""
    self._touch_presence(identity, room_id=room_id)
    if self.command == "GET" and action == "state":
        payload = room.session.state(identity.account)
        payload["room_id"] = room_id
        payload["room_status"] = room.status
        self._player_json(payload)
        return
```

For write routes, call the matching `room.session` method:

```python
if action == "sit":
    self._player_json(room.session.sit(identity.account, int(body.get("seat", 0)), self._generation(body)))
    return
if action == "ready":
    self._player_json(room.session.ready_account(identity.account, room.ai_policy, self._generation(body)))
    return
if action == "action":
    self._player_json(
        room.session.action(
            identity.account,
            body.get("action", body),
            body.get("action_token"),
            body.get("room_generation"),
            body.get("pending_id"),
        )
    )
    return
```

Admin invite route:

```python
if path == "/api/admin/invite-codes" and self.command == "POST":
    admin = self._require_admin_identity()
    code = str(body.get("code") or secrets.token_hex(3)).upper()[:6]
    self._json(application.database.create_invite_code(code, admin.account, body.get("max_uses")))
    return
```

- [ ] **Step 6: Update `main()` to use `HostConfig` and Zeabur `PORT`**

In `server.py`, parse CLI args as overrides but use `HostConfig.from_env()` defaults:

```python
config = HostConfig.from_env()
parser.add_argument("--host", default=config.host)
parser.add_argument("--port", type=int, default=config.port)
parser.add_argument("--data-dir", type=Path, default=config.data_dir)
parser.add_argument("--static-dir", type=Path, default=config.static_dir)
```

Before creating `BattleApplication`, compute:

```python
admin_password_hash = hash_password(config.admin_password) if config.admin_password else ""
```

Pass `admin_username`, `admin_password_hash`, `initial_invite_codes`, `max_rooms`, and `default_ai_policy`.

- [ ] **Step 7: Run online server tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_server -v`

Expected: PASS.

- [ ] **Step 8: Run existing server tests and update obsolete assertions**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_lan_server -v`

Expected: Some old tests may fail because passwordless `/api/battle/register` and `/api/battle/login` are obsolete. Update old tests to use `/api/auth/register` and `/api/auth/login`, or explicitly assert the old endpoints return 404/401 in online mode. Keep tests for gzip/static caching, token spoofing, and private player views.

- [ ] **Step 9: Commit**

```powershell
git add src\wenling_lan_host\server.py src\wenling_lan_host\config.py tests\test_online_server.py tests\test_lan_server.py
git commit -m "Wire online lobby HTTP API"
```

## Task 6: Lobby and Battle Frontend Conversion

**Files:**
- Modify: `static/battle_login.html`
- Modify: `static/battle_lobby.js`
- Modify: `static/battle_app.js`
- Modify: `static/styles.css`
- Test: `tests/test_online_server.py`

**Interfaces:**
- Consumes HTTP routes from Task 5.
- Produces localStorage keys:
  - `wenling.online.account.v1`
  - `wenling.online.token.v1`
  - `wenling.online.role.v1`
  - `wenling.online.room_id.v1`
- Produces URL pattern: `/battle?room_id=<room_id>`

- [ ] **Step 1: Add frontend smoke assertions**

In `tests/test_online_server.py`, add:

```python
def test_online_pages_load_expected_scripts(self) -> None:
    for path, expected in (
        ("/battle-login", "battle_lobby.js"),
        ("/battle", "battle_app.js"),
    ):
        request = urllib.request.Request(self.base + path)
        with urllib.request.urlopen(request, timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn(expected, html)
```

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_server.OnlineServerTests.test_online_pages_load_expected_scripts -v`

Expected: PASS before UI rewrite; keep it as a guard.

- [ ] **Step 2: Replace login page form**

Update `static/battle_login.html` body to include these controls:

```html
<main class="standalone-shell online-lobby-shell">
  <header class="standalone-head">
    <div>
      <h1>温岭麻将</h1>
      <p>登录账号进入游戏大厅，或使用邀请码注册。</p>
    </div>
  </header>

  <section class="standalone-card auth-card">
    <h2>账号登录</h2>
    <label>用户名 <input id="loginAccountInput" class="wide-input" autocomplete="username" /></label>
    <label>密码 <input id="loginPasswordInput" class="wide-input" type="password" autocomplete="current-password" /></label>
    <button id="loginBtn" class="primary" type="button">登录</button>
  </section>

  <section class="standalone-card auth-card">
    <h2>邀请码注册</h2>
    <label>用户名 <input id="registerAccountInput" class="wide-input" maxlength="12" autocomplete="username" /></label>
    <label>密码 <input id="registerPasswordInput" class="wide-input" type="password" autocomplete="new-password" /></label>
    <label>邀请码 <input id="inviteCodeInput" class="wide-input invite-code-input" maxlength="6" autocomplete="off" /></label>
    <button id="registerBtn" class="gold" type="button">注册并登录</button>
  </section>

  <section class="standalone-card lobby-card">
    <div class="lobby-toolbar">
      <div>
        <strong id="currentAccountLabel">未登录</strong>
        <span id="currentRoleLabel" class="tag"></span>
      </div>
      <button id="logoutBtn" type="button">退出登录</button>
    </div>
    <div class="battle-login-row">
      <input id="roomNameInput" class="wide-input" placeholder="房间名" />
      <select id="roomAiPolicySelect" class="wide-input battle-ai-policy-select">
        <option value="low">低级 AI</option>
        <option value="high">高级 AI</option>
      </select>
      <button id="createRoomBtn" class="primary" type="button">创建房间</button>
    </div>
    <div id="roomList" class="online-room-list"></div>
  </section>

  <div id="lobbyMessage" class="lobby-message"></div>
</main>
```

- [ ] **Step 3: Rewrite lobby JS around auth and room cards**

In `static/battle_lobby.js`, replace old account-selection logic with:

```javascript
const ACCOUNT_KEY = "wenling.online.account.v1";
const TOKEN_KEY = "wenling.online.token.v1";
const ROLE_KEY = "wenling.online.role.v1";
const ROOM_KEY = "wenling.online.room_id.v1";
const $ = (id) => document.getElementById(id);

function tokenValue() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

async function readApiResponse(response) {
  const raw = await response.text();
  const data = raw ? JSON.parse(raw) : {};
  if (!response.ok || data.error) throw new Error(data.error || response.statusText);
  return data;
}

async function api(path, options = {}) {
  const token = tokenValue();
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  return readApiResponse(response);
}

async function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function setSession(payload) {
  localStorage.setItem(ACCOUNT_KEY, payload.account || "");
  localStorage.setItem(ROLE_KEY, payload.role || "player");
  localStorage.setItem(TOKEN_KEY, payload.session_token || "");
}

async function login() {
  const payload = await post("/api/auth/login", {
    account: $("loginAccountInput").value.trim(),
    password: $("loginPasswordInput").value,
  });
  setSession(payload);
  await loadRooms();
}

async function register() {
  const payload = await post("/api/auth/register", {
    account: $("registerAccountInput").value.trim(),
    password: $("registerPasswordInput").value,
    invite_code: $("inviteCodeInput").value.trim(),
  });
  setSession(payload);
  await loadRooms();
}

async function loadRooms() {
  const token = tokenValue();
  $("currentAccountLabel").textContent = localStorage.getItem(ACCOUNT_KEY) || "未登录";
  $("currentRoleLabel").textContent = localStorage.getItem(ROLE_KEY) || "";
  if (!token) {
    $("roomList").innerHTML = "";
    return;
  }
  const payload = await api("/api/lobby/rooms");
  renderRooms(payload.rooms || [], payload.max_rooms || 3);
}

function renderRooms(rooms, maxRooms) {
  $("createRoomBtn").disabled = rooms.length >= maxRooms;
  $("roomList").innerHTML = rooms.map((room) => {
    const seats = (room.seats || []).map((seat) => seat.account || seat.effective_account || "空").join(" / ");
    const mine = room.owner_account === localStorage.getItem(ACCOUNT_KEY);
    return `
      <article class="online-room-card" data-room-id="${room.room_id}">
        <div class="room-card-head">
          <strong>${escapeHtml(room.room_name)}</strong>
          <span class="tag">${escapeHtml(room.status)}</span>
        </div>
        <div>房主：${escapeHtml(room.owner_account)}</div>
        <div>座位：${escapeHtml(seats)}</div>
        <div>AI：${room.ai_policy === "high" ? "高级" : "低级"}</div>
        <button class="primary enter-room-btn" data-room-id="${room.room_id}" type="button">进入房间</button>
        ${mine ? `<button class="close-room-btn" data-room-id="${room.room_id}" type="button">关闭房间</button>` : ""}
      </article>
    `;
  }).join("");
  document.querySelectorAll(".enter-room-btn").forEach((button) => {
    button.addEventListener("click", () => enterRoom(button.dataset.roomId));
  });
  document.querySelectorAll(".close-room-btn").forEach((button) => {
    button.addEventListener("click", () => closeRoom(button.dataset.roomId));
  });
}
```

Add `escapeHtml`, `createRoom`, `enterRoom`, `closeRoom`, `logout`, event binding, and interval refresh:

```javascript
function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function createRoom() {
  const room = await post("/api/lobby/rooms", {
    room_name: $("roomNameInput").value.trim(),
    ai_policy: $("roomAiPolicySelect").value,
  });
  enterRoom(room.room_id);
}

function enterRoom(roomId) {
  localStorage.setItem(ROOM_KEY, roomId);
  window.location.href = `/battle?room_id=${encodeURIComponent(roomId)}`;
}

async function closeRoom(roomId) {
  if (!window.confirm("确认关闭整个房间？")) return;
  if (!window.confirm("关闭后本局作废，所有玩家会回到大厅。继续关闭？")) return;
  await post(`/api/lobby/rooms/${encodeURIComponent(roomId)}/close`, { confirm: "CLOSE_ROOM" });
  await loadRooms();
}

async function logout() {
  if (tokenValue()) await post("/api/auth/logout", {});
  localStorage.removeItem(ACCOUNT_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
  localStorage.removeItem(ROOM_KEY);
  await loadRooms();
}
```

- [ ] **Step 4: Update battle app route helpers**

In `static/battle_app.js`, add:

```javascript
const BATTLE_ROOM_STORAGE_KEY = "wenling.online.room_id.v1";

function battleRoomIdValue() {
  const fromUrl = new URLSearchParams(window.location.search).get("room_id");
  if (fromUrl) {
    localStorage.setItem(BATTLE_ROOM_STORAGE_KEY, fromUrl);
    return fromUrl;
  }
  return localStorage.getItem(BATTLE_ROOM_STORAGE_KEY) || "";
}

function battleApiPath(action) {
  const roomId = battleRoomIdValue();
  if (!roomId) {
    window.location.href = "/battle-login";
    throw new Error("缺少房间 ID");
  }
  return `/api/battle/${encodeURIComponent(roomId)}/${action}`;
}
```

Replace calls:

- `/api/battle/state` -> `battleApiPath("state")`
- `/api/battle/wait` -> `battleApiPath("wait")`
- `/api/battle/heartbeat` -> `battleApiPath("heartbeat")`
- `/api/battle/sit` -> `battleApiPath("sit")`
- `/api/battle/leave` -> `battleApiPath("leave")`
- `/api/battle/ready` -> `battleApiPath("ready")`
- `/api/battle/reset` -> `battleApiPath("reset")`
- `/api/battle/action` -> `battleApiPath("action")`
- `/api/battle/report-bug` -> `battleApiPath("report-bug")`

After every state payload:

```javascript
if (state?.room_status === "closed") {
  alert("房间已关闭，返回大厅。");
  window.location.href = "/battle-login";
}
```

- [ ] **Step 5: Add lobby/admin visual styles**

Append to `static/styles.css`:

```css
.online-lobby-shell {
  max-width: 1180px;
}

.auth-card h2,
.lobby-card h2 {
  margin: 0 0 12px;
  font-size: 20px;
}

.online-room-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 12px;
  margin-top: 14px;
}

.online-room-card {
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-radius: 8px;
  padding: 14px;
  background: rgba(20, 42, 40, 0.88);
  color: #f7f1df;
}

.room-card-head,
.lobby-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.invite-code-input {
  text-transform: uppercase;
  letter-spacing: 0;
}
```

- [ ] **Step 6: Run server tests and a local smoke server**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_online_server -v
$env:WENLING_ADMIN_USERNAME='root'
$env:WENLING_ADMIN_PASSWORD='admin123'
$env:WENLING_INVITE_CODES='7392'
$env:WENLING_DATA_DIR="$pwd\data\online-smoke"
.\.venv\Scripts\python.exe -m wenling_lan_host --host 127.0.0.1 --port 8765
```

Expected: tests PASS; local server starts and `/battle-login` loads.

- [ ] **Step 7: Commit**

```powershell
git add static\battle_login.html static\battle_lobby.js static\battle_app.js static\styles.css tests\test_online_server.py
git commit -m "Convert lobby frontend to online rooms"
```

## Task 7: Admin Dashboard UI and Admin APIs

**Files:**
- Create: `static/battle_admin.html`
- Create: `static/battle_admin.js`
- Modify: `static/styles.css`
- Modify: `src/wenling_lan_host/server.py`
- Test: `tests/test_online_server.py`

**Interfaces:**
- Consumes admin API routes from Task 5.
- Produces `/battle/admin` static page.

- [ ] **Step 1: Add admin page server smoke test**

In `tests/test_online_server.py`, add:

```python
def test_admin_page_loads_for_static_shell(self) -> None:
    with urllib.request.urlopen(self.base + "/battle/admin", timeout=5) as response:
        html = response.read().decode("utf-8")
    self.assertIn("battle_admin.js", html)
    self.assertIn("管理员后台", html)
```

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_server.OnlineServerTests.test_admin_page_loads_for_static_shell -v`

Expected: FAIL until route and files exist.

- [ ] **Step 2: Add admin static page route**

In `server.py` GET routing:

```python
if path == "/battle/admin":
    self._file(application.static_dir / "battle_admin.html")
    return
```

Add `/battle_admin.js` to public static files, but protect admin data through API authorization, not by hiding static JS.

- [ ] **Step 3: Create admin HTML**

Create `static/battle_admin.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>温岭麻将 管理员后台</title>
    <link rel="stylesheet" href="/styles.css?v=online-admin-1" />
  </head>
  <body class="standalone-page">
    <main class="standalone-shell admin-shell">
      <header class="standalone-head">
        <div>
          <h1>管理员后台</h1>
          <p>管理账号、邀请码、房间和在线访问用户。</p>
        </div>
        <a class="button-like" href="/battle-login">返回大厅</a>
      </header>
      <section class="standalone-card">
        <h2>在线访问</h2>
        <div id="presenceRows" class="admin-table"></div>
      </section>
      <section class="standalone-card">
        <h2>邀请码</h2>
        <div class="battle-login-row">
          <input id="newInviteCodeInput" class="wide-input invite-code-input" maxlength="6" placeholder="留空自动生成" />
          <input id="newInviteMaxUsesInput" class="wide-input" type="number" min="1" placeholder="使用次数" />
          <button id="createInviteBtn" class="primary" type="button">生成邀请码</button>
        </div>
        <div id="inviteRows" class="admin-table"></div>
      </section>
      <section class="standalone-card">
        <h2>活动房间</h2>
        <div id="adminRoomRows" class="admin-table"></div>
      </section>
      <section class="standalone-card">
        <h2>账号</h2>
        <div id="accountRows" class="admin-table"></div>
      </section>
      <div id="adminMessage" class="lobby-message"></div>
    </main>
    <script src="/battle_admin.js?v=online-admin-1"></script>
  </body>
</html>
```

- [ ] **Step 4: Create admin JS**

Create `static/battle_admin.js`:

```javascript
const TOKEN_KEY = "wenling.online.token.v1";
const $ = (id) => document.getElementById(id);

function tokenValue() {
  return localStorage.getItem(TOKEN_KEY) || "";
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    cache: "no-store",
    ...options,
    headers: {
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(tokenValue() ? { Authorization: `Bearer ${tokenValue()}` } : {}),
      ...(options.headers || {}),
    },
  });
  const raw = await response.text();
  const data = raw ? JSON.parse(raw) : {};
  if (!response.ok || data.error) throw new Error(data.error || response.statusText);
  return data;
}

async function post(path, body = {}) {
  return api(path, { method: "POST", body: JSON.stringify(body) });
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;",
  }[ch]));
}

async function loadAdmin() {
  const [presence, invites, rooms, accounts] = await Promise.all([
    api("/api/admin/presence"),
    api("/api/admin/invite-codes"),
    api("/api/lobby/rooms"),
    api("/api/admin/accounts"),
  ]);
  $("presenceRows").innerHTML = (presence.visitors || []).map((row) =>
    `<div><b>${escapeHtml(row.account || "访客")}</b><span>${escapeHtml(row.page)}</span><span>${escapeHtml(row.ip)}</span></div>`
  ).join("");
  $("inviteRows").innerHTML = (invites.invite_codes || invites.codes || []).map((row) =>
    `<div><b>${escapeHtml(row.code)}</b><span>${row.enabled ? "可用" : "停用"}</span><span>${row.used_count}/${row.max_uses ?? "不限"}</span><button data-code="${row.code}" class="disable-invite-btn">停用</button></div>`
  ).join("");
  $("adminRoomRows").innerHTML = (rooms.rooms || []).map((room) =>
    `<div><b>${escapeHtml(room.room_name)}</b><span>${escapeHtml(room.owner_account)}</span><span>${escapeHtml(room.status)}</span><button data-room-id="${room.room_id}" class="admin-close-room-btn">关闭</button></div>`
  ).join("");
  $("accountRows").innerHTML = (accounts.accounts || []).map((row) =>
    `<div><b>${escapeHtml(row.account)}</b><span>${escapeHtml(row.role || "")}</span><span>${row.enabled ? "启用" : "停用"}</span></div>`
  ).join("");
  bindAdminButtons();
}

function bindAdminButtons() {
  document.querySelectorAll(".disable-invite-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      await post(`/api/admin/invite-codes/${encodeURIComponent(button.dataset.code)}/disable`, {});
      await loadAdmin();
    });
  });
  document.querySelectorAll(".admin-close-room-btn").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!confirm("确认关闭该房间？")) return;
      if (!confirm("关闭后本局作废，所有玩家回到大厅。继续？")) return;
      await post(`/api/lobby/rooms/${encodeURIComponent(button.dataset.roomId)}/close`, { confirm: "CLOSE_ROOM" });
      await loadAdmin();
    });
  });
}

async function createInvite() {
  const code = $("newInviteCodeInput").value.trim();
  const maxUsesRaw = $("newInviteMaxUsesInput").value.trim();
  await post("/api/admin/invite-codes", {
    ...(code ? { code } : {}),
    ...(maxUsesRaw ? { max_uses: Number(maxUsesRaw) } : {}),
  });
  $("newInviteCodeInput").value = "";
  $("newInviteMaxUsesInput").value = "";
  await loadAdmin();
}

document.addEventListener("DOMContentLoaded", () => {
  $("createInviteBtn").addEventListener("click", () => createInvite().catch((error) => alert(error.message)));
  loadAdmin().catch((error) => {
    $("adminMessage").textContent = error.message || "需要管理员登录";
    $("adminMessage").classList.add("bad");
  });
  setInterval(() => loadAdmin().catch(() => {}), 10000);
});
```

- [ ] **Step 5: Add admin styles**

Append:

```css
.admin-shell {
  max-width: 1180px;
}

.admin-table {
  display: grid;
  gap: 8px;
}

.admin-table > div {
  display: grid;
  grid-template-columns: minmax(120px, 1.2fr) minmax(80px, 1fr) minmax(80px, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.07);
}

.button-like {
  display: inline-flex;
  align-items: center;
  min-height: 40px;
  padding: 0 14px;
  border-radius: 8px;
  text-decoration: none;
  color: #20170b;
  background: #e8c766;
}
```

- [ ] **Step 6: Run admin tests**

Run: `.\.venv\Scripts\python.exe -m unittest tests.test_online_server -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```powershell
git add static\battle_admin.html static\battle_admin.js static\styles.css src\wenling_lan_host\server.py tests\test_online_server.py
git commit -m "Add admin dashboard"
```

## Task 8: Zeabur Deployment, Docs, and Final Verification

**Files:**
- Create: `zbpack.json`
- Modify: `README.md`
- Modify: `docs/OPERATIONS.md`
- Test: full test suite

**Interfaces:**
- Consumes: `HostConfig.from_env()`
- Produces: Zeabur start command using `$PORT` and `WENLING_DATA_DIR`

- [ ] **Step 1: Add Zeabur config file**

Create `zbpack.json`:

```json
{
  "start_command": "python -m wenling_lan_host --host 0.0.0.0 --port ${PORT:-8765} --data-dir ${WENLING_DATA_DIR:-/data}"
}
```

- [ ] **Step 2: Add README deployment section**

Append to `README.md`:

```markdown
## Zeabur Online Deployment

The online lobby runs as a single Python service with SQLite on a persistent
volume. Configure a Zeabur volume at `/data`, then set these environment
variables:

- `WENLING_DATA_DIR=/data`
- `WENLING_ADMIN_USERNAME=<admin name>`
- `WENLING_ADMIN_PASSWORD=<admin password>`
- `WENLING_INVITE_CODES=7392,WL8K2`
- `WENLING_MAX_ROOMS=3`
- `WENLING_DEFAULT_AI_POLICY=low`

Zeabur injects `PORT`; the service reads it automatically. The first startup
creates a fresh online database, initializes fixed AI accounts, creates or
updates the admin account, and imports the initial invite codes.

This release is intentionally single-instance. Do not horizontally scale it:
room state is in memory and SQLite is mounted on one persistent volume.
```

- [ ] **Step 3: Add operations notes**

Append to `docs/OPERATIONS.md`:

```markdown
## Zeabur online lobby operations

Use `/battle-login` for player login and registration. Registration requires
an invite code. Use `/battle/admin` after logging in as the administrator to
generate invite codes, inspect online visitors, and close problem rooms.

If players report stale room state, close the affected room from the admin
dashboard. Closing a room during a hand intentionally cancels that hand and
sends players back to the lobby.

Monitor Zeabur Metrics for CPU, memory, and network. If CPU stays near 80% or
high AI causes visible pauses, keep `WENLING_DEFAULT_AI_POLICY=low`, reduce
active rooms, or increase service resources before considering a dedicated
server.
```

- [ ] **Step 4: Run focused tests**

Run:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_online_auth tests.test_invite_codes tests.test_presence tests.test_room_manager tests.test_online_server -v
```

Expected: PASS.

- [ ] **Step 5: Run full Python test suite**

Run:

```powershell
$env:PYTHONPATH='src;packages/wenling_core'
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: PASS. If repository-boundary tests fail because `CORE_MANIFEST.json` changed from core runtime edits, regenerate the manifest using the repo's existing manifest tool before committing.

- [ ] **Step 6: Run local online smoke test**

Run:

```powershell
$env:WENLING_ADMIN_USERNAME='root'
$env:WENLING_ADMIN_PASSWORD='admin123'
$env:WENLING_INVITE_CODES='7392'
$env:WENLING_DATA_DIR="$pwd\data\online-smoke"
.\.venv\Scripts\python.exe -m wenling_lan_host --host 127.0.0.1 --port 8765
```

Manual expected results:

- `http://127.0.0.1:8765/battle-login` loads.
- Registering `alice` with password `secret123` and invite `7392` succeeds.
- Creating a room shows it in the room list.
- Entering the room opens `/battle?room_id=<id>`.
- Admin login with `root` / `admin123` opens `/battle/admin`.
- Admin can see online visitors and invite codes.

- [ ] **Step 7: Commit**

```powershell
git add zbpack.json README.md docs\OPERATIONS.md
git commit -m "Document Zeabur online deployment"
```

## Self-Review

Spec coverage:

- Password registration and login: Task 1, Task 2, Task 5, Task 6.
- Simple invite codes and admin generation: Task 2, Task 5, Task 7.
- Admin monitoring of visitors: Task 3, Task 5, Task 7.
- Max 3 rooms and owner rules: Task 4, Task 5, Task 6.
- Per-room AI level: Task 4, Task 6.
- During-play close with two confirmations: Task 4, Task 6, Task 7.
- Mature lobby/admin UI: Task 6, Task 7.
- Zeabur `PORT`, `/data`, and single-instance deployment: Task 8.
- No old account/data migration: Task 1 and Task 8.

Placeholder scan:

- No unresolved placeholder markers or copy-forward task shortcuts are intentionally left in this plan.

Type consistency:

- `AuthIdentity.account` and `AuthIdentity.role` are used consistently by `RoomManager` and `server.py`.
- `RoomManager.close_room(..., confirm="CLOSE_ROOM")` matches frontend and admin UI confirmation payloads.
- `room_id` is consistently used in lobby payloads, battle URLs, and `/api/battle/{room_id}/...` routes.
