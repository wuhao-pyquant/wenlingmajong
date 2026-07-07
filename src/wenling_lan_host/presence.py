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

    def forget_account(self, account: str) -> None:
        value = str(account or "").strip()
        if not value:
            return
        with self._lock:
            stale_visitor_ids = [
                visitor_id
                for visitor_id, row in self._visitors.items()
                if str(row.get("account") or "").strip() == value
            ]
            for visitor_id in stale_visitor_ids:
                self._visitors.pop(visitor_id, None)

    def snapshot(
        self,
        now: float | None = None,
        *,
        active_identities: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        current = time.time() if now is None else float(now)
        with self._lock:
            rows = [
                dict(row)
                for row in self._visitors.values()
                if current - float(row.get("last_seen_at") or 0.0) <= self.online_sec
            ]
        seen_accounts = {str(row.get("account")) for row in rows if row.get("account")}
        for identity in active_identities or []:
            account = str(identity.get("account") or "").strip()
            if not account or account in seen_accounts:
                continue
            rows.append(
                {
                    "visitor_id": f"account:{account}",
                    "account": account,
                    "role": str(identity.get("role") or ""),
                    "page": "",
                    "room_id": None,
                    "seat": None,
                    "ip": "",
                    "user_agent": "",
                    "last_seen_at": current,
                }
            )
            seen_accounts.add(account)
        rows.sort(key=lambda row: float(row["last_seen_at"]), reverse=True)
        return {
            "online_count": len(rows),
            "logged_in_count": sum(1 for row in rows if row.get("account")),
            "visitors": rows,
        }
