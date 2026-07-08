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
FIXED_ONLINE_PASSWORD = "1234"


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
    if len(value) < 4:
        raise ValueError("password must be at least 4 characters")
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


def require_fixed_online_password(password: str) -> None:
    if str(password or "") != FIXED_ONLINE_PASSWORD:
        raise ValueError("online account password must be 1234")


class PlayerSessionStore:
    def __init__(self, database: BattleDatabase):
        self.database = database
        self._lock = threading.RLock()
        self._token_to_identity: dict[str, AuthIdentity] = {}
        self._account_to_token: dict[str, str] = {}

    def register_player(self, account_name: str, password: str, invite_code: str) -> dict[str, Any]:
        require_fixed_online_password(password)
        row = self.database.create_player_account(account_name, hash_password(password), invite_code)
        return self._issue(row)

    def login_password(self, account_name: str, password: str) -> dict[str, Any]:
        try:
            require_fixed_online_password(password)
        except ValueError as exc:
            raise PermissionError(str(exc)) from exc
        row = self.database.require_active_human_account(account_name)
        if not verify_password(password, str(row.get("password_hash") or "")):
            raise PermissionError("account or password incorrect")
        self.database.mark_login(str(row["account_name"]))
        return self._issue(row)

    def login(self, account_name: str) -> dict[str, Any]:
        raise PermissionError("online mode requires password login")

    def resolve_identity(self, token: str | None) -> AuthIdentity:
        value = str(token or "").strip()
        if not value:
            raise PermissionError("login required")
        with self._lock:
            identity = self._token_to_identity.get(value)
        if identity is None:
            raise PermissionError("session expired, please log in again")
        try:
            row = self.database.require_active_human_account(identity.account)
        except ValueError as exc:
            self.revoke_account(identity.account)
            raise PermissionError(str(exc)) from exc
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

    def active_identities(self) -> list[dict[str, Any]]:
        with self._lock:
            identities = list(self._token_to_identity.values())
        active: list[dict[str, Any]] = []
        for identity in identities:
            try:
                row = self.database.require_active_human_account(identity.account)
            except ValueError:
                self.revoke_account(identity.account)
                continue
            active.append({"account": str(row["account_name"]), "role": str(row["role"])})
        active.sort(key=lambda row: str(row["account"]).lower())
        return active

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
