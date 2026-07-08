from __future__ import annotations

import argparse
from contextlib import closing
import gzip
import ipaddress
import json
import mimetypes
import secrets
import socket
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from wenling_core import protocol_info
from wenling_core.tile_efficiency import TileEfficiencyPolicyModel
from wenling_core.tiles import TILE_BY_CODE, tile_name

from .auth import FIXED_ONLINE_PASSWORD, AuthIdentity, PlayerSessionStore, hash_password
from .battle_app import BattleSession
from .battle_db import BattleDatabase
from .config import DEFAULT_INVITE_CODE, HostConfig
from .presence import PresenceTracker
from .rooms import RoomManager


PUBLIC_GET_PATHS = {
    "/",
    "/battle-login",
    "/battle-lobby",
    "/battle-admin",
    "/battle/admin",
    "/battle",
    "/api/tiles",
    "/api/battle/available-accounts",
    "/api/battle/state",
    "/api/battle/wait",
}
PUBLIC_POST_PATHS = {
    "/api/battle/register",
    "/api/battle/login",
    "/api/battle/logout",
    "/api/battle/heartbeat",
    "/api/battle/sit",
    "/api/battle/leave",
    "/api/battle/ready",
    "/api/battle/reset",
    "/api/battle/action",
    "/api/battle/report-bug",
}
PUBLIC_STATIC_PATHS = {
    "/styles.css",
    "/battle_layout.css",
    "/battle_geometry_v7.css",
    "/battle_app.js",
    "/battle_table_model.js",
    "/battle_table_renderer.js",
    "/battle_lobby.js",
    "/battle_admin.js",
}


class BattleApplication:
    def __init__(
        self,
        data_dir: Path,
        static_dir: Path,
        *,
        service_name: str = "wenling-lan-mobile-foundation",
        bind_host: str = "0.0.0.0",
        bind_port: int = 8765,
        expose_host_info: bool = False,
        compress_json: bool = True,
        quiet_http_logs: bool = False,
        runtime_context: dict[str, Any] | None = None,
        bug_report_export_dir: Path | None = None,
        auto_bug_snapshots: bool = True,
        low_latency_ai: bool = False,
        ticker_interval_sec: float = 0.05,
        admin_username: str = "admin",
        admin_password_hash: str = "",
        initial_invite_codes: list[str] | None = None,
        max_rooms: int = 3,
        default_ai_policy: str = "low",
    ):
        self.data_dir = data_dir.resolve()
        self.static_dir = static_dir.resolve()
        self.service_name = service_name
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.expose_host_info = expose_host_info
        self.compress_json = bool(compress_json)
        self.quiet_http_logs = bool(quiet_http_logs)
        self.auto_bug_snapshots = bool(auto_bug_snapshots)
        self.low_latency_ai = bool(low_latency_ai)
        self.ticker_interval_sec = max(0.05, float(ticker_interval_sec))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = BattleDatabase(self.data_dir / "battle.sqlite3")
        if admin_password_hash:
            self.database.bootstrap_admin(admin_username, admin_password_hash)
        fixed_password_hash = hash_password(FIXED_ONLINE_PASSWORD)
        self.database.set_all_human_passwords(fixed_password_hash)
        seen_codes: set[str] = set()
        for code in [DEFAULT_INVITE_CODE, *(initial_invite_codes or [])]:
            normalized_code = str(code or "").strip().upper()
            if not normalized_code or normalized_code in seen_codes:
                continue
            seen_codes.add(normalized_code)
            try:
                self.database.create_invite_code(normalized_code, created_by=admin_username)
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
        runtime_context = {
            **(runtime_context or {}),
            "service_name": service_name,
            "bind_host": bind_host,
            "bind_port": bind_port,
            "compress_json": self.compress_json,
            "quiet_http_logs": self.quiet_http_logs,
            "auto_bug_snapshots": self.auto_bug_snapshots,
            "low_latency_ai": self.low_latency_ai,
            "ticker_interval_sec": self.ticker_interval_sec,
        }
        self.session = BattleSession(
            self.database,
            str(self.data_dir / "logs"),
            model_factory=lambda _policy: TileEfficiencyPolicyModel(),
            analysis_model_factory=TileEfficiencyPolicyModel,
            runtime_context=runtime_context,
            bug_report_export_dir=bug_report_export_dir,
            auto_bug_snapshots=self.auto_bug_snapshots,
            low_latency_ai=self.low_latency_ai,
            ticker_interval_sec=self.ticker_interval_sec,
        )

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "service": self.service_name,
            "data_dir": str(self.data_dir),
            **protocol_info(),
        }

    def host_info(self) -> dict[str, Any]:
        return {
            **self.health(),
            "host": self.bind_host,
            "port": self.bind_port,
            "base_url": f"http://{self.bind_host}:{self.bind_port}",
            "capabilities": {
                "authoritative_server": True,
                "private_player_views": True,
                "reconnect": True,
                "cloudflare": False,
                "lan_browser_clients": True,
                "android_webview_ready": True,
                "json_gzip": self.compress_json,
            },
        }

    def close(self) -> None:
        self.player_sessions.clear()
        self.rooms.close()
        self.session.close()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    request_queue_size = 64

    def get_request(self) -> tuple[socket.socket, Any]:
        request, client_address = super().get_request()
        request.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        request.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        return request, client_address


def make_handler(application: BattleApplication) -> type[BaseHTTPRequestHandler]:
    class BattleHandler(BaseHTTPRequestHandler):
        server_version = "WenlingBattle/1.0"
        protocol_version = "HTTP/1.1"

        def _is_local_request(self) -> bool:
            host = self.client_address[0] if self.client_address else ""
            try:
                if not ipaddress.ip_address(host).is_loopback:
                    return False
            except ValueError:
                if host not in {"", "localhost"}:
                    return False
            for header in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
                for forwarded in str(self.headers.get(header) or "").split(","):
                    value = forwarded.strip()
                    if not value:
                        continue
                    try:
                        if not ipaddress.ip_address(value).is_loopback:
                            return False
                    except ValueError:
                        if value != "localhost":
                            return False
            return True

        def _require_local(self) -> bool:
            if self._is_local_request():
                return True
            self._json({"error": "admin endpoint is local-only"}, status=403)
            return False

        def _is_online_api_path(self, path: str) -> bool:
            parts = [part for part in path.split("/") if part]
            if parts[:2] in (["api", "auth"], ["api", "lobby"], ["api", "admin"]):
                return True
            return len(parts) >= 4 and parts[:2] == ["api", "battle"] and parts[2] != "stats"

        def _path_parts(self) -> list[str]:
            return [part for part in urlparse(self.path).path.split("/") if part]

        def _identity(self) -> AuthIdentity:
            return application.player_sessions.resolve_identity(self._bearer_token())

        def _require_admin_identity(self) -> AuthIdentity:
            identity = self._identity()
            if identity.role != "admin":
                raise PermissionError("admin role required")
            return identity

        def _touch_presence(
            self,
            identity: AuthIdentity | None = None,
            *,
            room_id: str | None = None,
            seat: int | None = None,
        ) -> None:
            application.presence.touch(
                self._presence_visitor_id(identity),
                account=identity.account if identity else None,
                role=identity.role if identity else None,
                page=urlparse(self.path).path,
                room_id=room_id,
                seat=seat,
                ip=str(self.client_address[0] if self.client_address else ""),
                user_agent=str(self.headers.get("User-Agent") or ""),
            )

        def _presence_visitor_id(self, identity: AuthIdentity | None = None) -> str:
            explicit = str(self.headers.get("X-Visitor-ID") or "").strip()
            if explicit:
                return explicit
            if identity is not None and identity.account:
                return f"account:{identity.account}"
            return str(self.client_address[0] if self.client_address else "")

        def _permission_status(self, exc: PermissionError) -> int:
            message = str(exc)
            if not self._bearer_token():
                return 401
            if "login required" in message or "session expired" in message:
                return 401
            return 403

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                parts = self._path_parts()
                if not self._bearer_token():
                    self._touch_presence()
                public = (
                    path in PUBLIC_GET_PATHS
                    or path in PUBLIC_STATIC_PATHS
                    or self._is_online_api_path(path)
                    or path.startswith("/assets/")
                    or (
                        application.expose_host_info
                        and path in {"/api/health", "/api/host/info"}
                    )
                )
                if not self._is_local_request() and not public:
                    self.send_error(404, "Not found")
                    return
                if path == "/api/health":
                    if not application.expose_host_info and not self._require_local():
                        return
                    self._json(application.health())
                    return
                if path == "/api/host/info" and application.expose_host_info:
                    self._json(application.host_info())
                    return
                if path == "/":
                    self._file(application.static_dir / "battle_login.html")
                    return
                if path == "/battle-login":
                    self._file(application.static_dir / "battle_login.html")
                    return
                if path == "/battle-lobby":
                    self._file(application.static_dir / "battle_lobby.html")
                    return
                if path in {"/battle-admin", "/battle/admin"}:
                    self._file(application.static_dir / "battle_admin.html")
                    return
                if path == "/battle":
                    self._file(application.static_dir / "battle.html")
                    return
                if path == "/battle/accounts":
                    if not self._require_local():
                        return
                    self._file(application.static_dir / "battle_accounts.html")
                    return
                if path in {"/battle-layout-editor", "/battle_layout_box_editor.html"}:
                    if not self._require_local():
                        return
                    self._file(application.static_dir / "battle_layout_box_editor.html")
                    return
                if path == "/api/tiles":
                    self._json({code: tile_name(code) for code in TILE_BY_CODE})
                    return
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
                if path == "/api/admin/rooms":
                    admin = self._require_admin_identity()
                    self._touch_presence(admin)
                    self._json(application.rooms.list_rooms())
                    return
                if path == "/api/admin/accounts":
                    admin = self._require_admin_identity()
                    self._touch_presence(admin)
                    self._json({"accounts": application.database.accounts()})
                    return
                if path == "/api/admin/invite-codes":
                    admin = self._require_admin_identity()
                    self._touch_presence(admin)
                    self._json({"invite_codes": application.database.invite_codes()})
                    return
                if path == "/api/admin/presence":
                    admin = self._require_admin_identity()
                    self._touch_presence(admin)
                    self._json(
                        application.presence.snapshot(
                            active_identities=application.player_sessions.active_identities()
                        )
                    )
                    return
                if len(parts) >= 4 and parts[:2] == ["api", "battle"]:
                    identity = self._identity()
                    room_id = parts[2]
                    room = application.rooms.get_room(room_id)
                    action = parts[3]
                    self._touch_presence(identity, room_id=room_id)
                    if action == "state":
                        payload = room.session.state(identity.account)
                        payload["room_id"] = room_id
                        payload["room_status"] = room.status
                        self._player_json(payload)
                        return
                    if action == "wait":
                        query = parse_qs(parsed.query)
                        since_raw = (query.get("since") or [None])[0]
                        timeout_raw = (query.get("timeout") or [None])[0]
                        since = int(since_raw) if since_raw not in {None, ""} else None
                        timeout = float(timeout_raw) if timeout_raw not in {None, ""} else 15.0
                        payload = room.session.wait_state(identity.account, since=since, timeout=timeout)
                        payload["room_id"] = room_id
                        payload["room_status"] = room.status
                        self._player_json(payload)
                        return
                if path == "/api/battle/available-accounts":
                    self._json({"accounts": application.database.active_human_accounts()})
                    return
                if path == "/api/battle/state":
                    account = self._authenticated_account()
                    self._player_json(application.session.state(account))
                    return
                if path == "/api/battle/wait":
                    query = parse_qs(parsed.query)
                    account = self._authenticated_account()
                    since_raw = (query.get("since") or [None])[0]
                    timeout_raw = (query.get("timeout") or [None])[0]
                    since = int(since_raw) if since_raw not in {None, ""} else None
                    timeout = float(timeout_raw) if timeout_raw not in {None, ""} else 15.0
                    self._player_json(application.session.wait_state(account, since=since, timeout=timeout))
                    return
                if path == "/api/battle/step":
                    if not self._require_local():
                        return
                    query = parse_qs(parsed.query)
                    self._json(application.session.step((query.get("account") or [None])[0]))
                    return
                if path == "/api/battle/db":
                    if not self._require_local():
                        return
                    self._json(application.session.db_info())
                    return
                if path == "/api/battle/accounts":
                    if not self._require_local():
                        return
                    self._json(application.session.accounts())
                    return
                candidate = (application.static_dir / path.lstrip("/")).resolve()
                if application.static_dir in candidate.parents and candidate.is_file():
                    if (
                        not self._is_local_request()
                        and path not in PUBLIC_STATIC_PATHS
                        and not path.startswith("/assets/")
                    ):
                        self.send_error(404, "Not found")
                        return
                    self._file(candidate)
                    return
                self.send_error(404, "Not found")
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=self._permission_status(exc))
            except Exception as exc:  # pragma: no cover
                self._error(exc)

        def do_POST(self) -> None:
            try:
                path = urlparse(self.path).path
                parts = self._path_parts()
                if not self._is_local_request() and path not in PUBLIC_POST_PATHS and not self._is_online_api_path(path):
                    self.send_error(404, "Not found")
                    return
                if not self._bearer_token():
                    self._touch_presence()
                body = self._read_json()
                if path == "/api/auth/register":
                    payload = application.player_sessions.register_player(
                        str(body.get("account") or body.get("account_name") or ""),
                        str(body.get("password") or ""),
                        str(body.get("invite_code") or body.get("invite") or ""),
                    )
                    self._touch_presence(
                        AuthIdentity(
                            account=str(payload["account"]),
                            role=str(payload["role"]),
                            token=str(payload["session_token"]),
                        )
                    )
                    self._json(payload)
                    return
                if path == "/api/auth/login":
                    payload = application.player_sessions.login_password(
                        str(body.get("account") or body.get("account_name") or ""),
                        str(body.get("password") or ""),
                    )
                    self._touch_presence(
                        AuthIdentity(
                            account=str(payload["account"]),
                            role=str(payload["role"]),
                            token=str(payload["session_token"]),
                        )
                    )
                    self._json(payload)
                    return
                if path == "/api/auth/logout":
                    identity = self._identity()
                    self._touch_presence(identity)
                    application.player_sessions.logout(identity.token)
                    application.presence.forget(self._presence_visitor_id(identity))
                    application.presence.forget_account(identity.account)
                    self._json({"ok": True})
                    return
                if path == "/api/lobby/rooms":
                    identity = self._identity()
                    self._touch_presence(identity)
                    self._json(
                        application.rooms.create_room(
                            identity.account,
                            room_name=str(body.get("room_name") or body.get("name") or ""),
                            ai_policy=str(body.get("ai_policy") or ""),
                        )
                    )
                    return
                if len(parts) == 5 and parts[:3] == ["api", "lobby", "rooms"]:
                    identity = self._identity()
                    room_id = parts[3]
                    action = parts[4]
                    self._touch_presence(identity, room_id=room_id)
                    if action == "settings":
                        self._json(
                            application.rooms.set_room_settings(
                                room_id,
                                identity,
                                room_name=body.get("room_name") or body.get("name"),
                                ai_policy=body.get("ai_policy"),
                            )
                        )
                        return
                    if action == "close":
                        self._json(
                            application.rooms.close_room(
                                room_id,
                                identity,
                                confirm=str(body.get("confirm") or ""),
                            )
                        )
                        return
                    if action == "kick":
                        self._player_json(
                            application.rooms.kick(
                                room_id,
                                identity,
                                str(body.get("target") or ""),
                                body.get("room_generation"),
                            )
                        )
                        return
                if len(parts) == 5 and parts[:3] == ["api", "admin", "rooms"]:
                    admin = self._require_admin_identity()
                    room_id = parts[3]
                    action = parts[4]
                    self._touch_presence(admin, room_id=room_id)
                    if action == "close":
                        self._json(
                            application.rooms.close_room(
                                room_id,
                                admin,
                                confirm=str(body.get("confirm") or ""),
                            )
                        )
                        return
                if len(parts) >= 4 and parts[:2] == ["api", "battle"] and parts[2] != "stats":
                    identity = self._identity()
                    room_id = parts[2]
                    room = application.rooms.get_room(room_id)
                    action = parts[3]
                    seat = int(body["seat"]) if action == "sit" and body.get("seat") is not None else None
                    self._touch_presence(identity, room_id=room_id, seat=seat)
                    if action == "heartbeat":
                        self._player_json(room.session.heartbeat(identity.account, self._generation(body)))
                        return
                    if action == "sit":
                        self._player_json(room.session.sit(identity.account, int(body.get("seat", 0)), self._generation(body)))
                        return
                    if action == "leave":
                        self._player_json(room.session.leave(identity.account, self._generation(body)))
                        return
                    if action == "ready":
                        self._player_json(room.session.ready_account(identity.account, room.ai_policy, self._generation(body)))
                        return
                    if action == "reset":
                        self._player_json(room.session.reset_match(identity.account, self._generation(body)))
                        return
                    if action == "report-bug":
                        self._player_json(
                            room.session.report_bug(
                                identity.account,
                                note=str(body.get("note") or ""),
                                client_context=body.get("client_context")
                                if isinstance(body.get("client_context"), dict)
                                else {},
                                room_generation=self._generation(body),
                            )
                        )
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
                if len(parts) >= 4 and parts[:3] == ["api", "admin", "accounts"]:
                    admin = self._require_admin_identity()
                    account = unquote(parts[3])
                    action = parts[4] if len(parts) > 4 else ""
                    self._touch_presence(admin)
                    if action == "disable":
                        result = application.database.set_account_enabled(account, False)
                        application.player_sessions.revoke_account(str(result["account_name"]))
                        application.presence.forget_account(str(result["account_name"]))
                        self._json(result)
                        return
                    if action == "enable":
                        self._json(application.database.set_account_enabled(account, True))
                        return
                    if action == "reset-password":
                        row = application.database.account(account)
                        if bool(row["is_ai"]):
                            raise ValueError("fixed AI account password cannot be reset")
                        password_hash = hash_password(FIXED_ONLINE_PASSWORD)
                        with closing(application.database.connect()) as con, con:
                            con.execute(
                                "UPDATE accounts SET password_hash = ? WHERE account_name = ?",
                                (password_hash, str(row["account_name"])),
                            )
                        application.player_sessions.revoke_account(str(row["account_name"]))
                        application.presence.forget_account(str(row["account_name"]))
                        updated = application.database.account(str(row["account_name"]))
                        self._json(
                            {
                                "ok": True,
                                "account": updated["account_name"],
                                "role": updated["role"],
                                "enabled": bool(updated["enabled"]),
                            }
                        )
                        return
                if path == "/api/admin/invite-codes":
                    admin = self._require_admin_identity()
                    self._touch_presence(admin)
                    code = str(body.get("code") or secrets.token_hex(3)).upper()[:6]
                    self._json(application.database.create_invite_code(code, admin.account, body.get("max_uses")))
                    return
                if len(parts) == 5 and parts[:3] == ["api", "admin", "invite-codes"]:
                    admin = self._require_admin_identity()
                    code = parts[3]
                    action = parts[4]
                    self._touch_presence(admin)
                    if action == "disable":
                        self._json(application.database.disable_invite_code(code))
                        return
                if path == "/api/battle/register":
                    registered = application.session.register_player(
                        str(body.get("account") or body.get("account_name") or "")
                    )
                    authenticated = application.player_sessions.login(registered["account"])
                    self._json({**registered, **authenticated})
                    return
                if path == "/api/battle/login":
                    self._json(application.player_sessions.login(str(body.get("account") or body.get("account_name") or "")))
                    return
                if path == "/api/battle/logout":
                    token = self._bearer_token()
                    try:
                        identity = self._identity()
                    except PermissionError:
                        identity = None
                    application.player_sessions.logout(token)
                    if identity is not None:
                        application.presence.forget(self._presence_visitor_id(identity))
                        application.presence.forget_account(identity.account)
                    self._json({"ok": True})
                    return
                if path == "/api/battle/heartbeat":
                    self._player_json(application.session.heartbeat(self._authenticated_account(), self._generation(body)))
                    return
                if path == "/api/battle/sit":
                    self._player_json(application.session.sit(self._authenticated_account(), int(body.get("seat", 0)), self._generation(body)))
                    return
                if path == "/api/battle/leave":
                    self._player_json(application.session.leave(self._authenticated_account(), self._generation(body)))
                    return
                if path == "/api/battle/kick":
                    if not self._require_local():
                        return
                    self._json(
                        application.session.kick(
                            self._account(body),
                            str(body.get("target") or ""),
                            self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/ready":
                    self._player_json(
                        application.session.ready_account(
                            self._authenticated_account(),
                            str(body.get("ai_policy") or ""),
                            self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/reset":
                    self._player_json(
                        application.session.reset_match(
                            self._authenticated_account(),
                            self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/report-bug":
                    self._player_json(
                        application.session.report_bug(
                            self._authenticated_account(),
                            note=str(body.get("note") or ""),
                            client_context=body.get("client_context")
                            if isinstance(body.get("client_context"), dict)
                            else {},
                            room_generation=self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/action":
                    self._player_json(
                        application.session.action(
                            self._authenticated_account(),
                            body.get("action", body),
                            body.get("action_token"),
                            body.get("room_generation"),
                            body.get("pending_id"),
                        )
                    )
                    return
                if path == "/api/battle/stats/reset":
                    if not self._require_local():
                        return
                    self._json(application.session.reset_stats())
                    return
                self.send_error(404, "Not found")
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
            except PermissionError as exc:
                self._json({"error": str(exc)}, status=self._permission_status(exc))
            except Exception as exc:  # pragma: no cover
                self._error(exc)

        def _bearer_token(self) -> str | None:
            value = str(self.headers.get("Authorization") or "").strip()
            prefix = "Bearer "
            return value[len(prefix):].strip() if value.startswith(prefix) else None

        def _authenticated_account(self) -> str:
            return application.player_sessions.resolve(self._bearer_token())

        def _player_json(self, payload: Any, status: int = 200) -> None:
            if isinstance(payload, dict):
                payload = dict(payload)
                for key in ("db", "runtime", "rule_issues"):
                    payload.pop(key, None)
            self._json(payload, status=status)

        @staticmethod
        def _account(body: dict[str, Any]) -> str:
            return str(body.get("account") or body.get("account_name") or "")

        @staticmethod
        def _generation(body: dict[str, Any]) -> int:
            if body.get("room_generation") is None:
                raise ValueError("room_generation is required")
            return int(body["room_generation"])

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                return {}
            text = self.rfile.read(length).decode("utf-8").strip()
            if not text:
                return {}
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"value": parsed}

        def _json(self, payload: Any, status: int = 200) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            compressed = (
                application.compress_json
                and
                len(raw) >= 512
                and "gzip" in str(self.headers.get("Accept-Encoding") or "").lower()
            )
            if compressed:
                raw = gzip.compress(raw, compresslevel=1)
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Vary", "Accept-Encoding")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(raw)

        def _file(self, path: Path) -> None:
            if not path.is_file():
                self.send_error(404, "Not found")
                return
            raw = path.read_bytes()
            content_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            if path.suffix.lower() == ".html":
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header("Cache-Control", "public, max-age=3600")
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, exc: Exception) -> None:
            traceback.print_exc()
            self._json({"error": str(exc)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
            if application.quiet_http_logs:
                return
            print(f"[battle] {self.address_string()} - {format % args}")

    return BattleHandler


def run(
    host: str,
    port: int,
    data_dir: Path,
    static_dir: Path,
    *,
    service_name: str = "wenling-lan-mobile-foundation",
    expose_host_info: bool = True,
    admin_username: str = "admin",
    admin_password_hash: str = "",
    initial_invite_codes: list[str] | None = None,
    max_rooms: int = 3,
    default_ai_policy: str = "low",
) -> None:
    application = BattleApplication(
        data_dir,
        static_dir,
        service_name=service_name,
        bind_host=host,
        bind_port=port,
        expose_host_info=expose_host_info,
        admin_username=admin_username,
        admin_password_hash=admin_password_hash,
        initial_invite_codes=initial_invite_codes,
        max_rooms=max_rooms,
        default_ai_policy=default_ai_policy,
    )
    server = ReusableThreadingHTTPServer((host, port), make_handler(application))
    print(f"{service_name}: http://{host}:{port}")
    print(f"Data directory: {application.data_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        application.close()
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    config = HostConfig.from_env()
    parser = argparse.ArgumentParser(description="Run the independent Wenling LAN host service.")
    parser.add_argument("--host", default=config.host)
    parser.add_argument("--port", type=int, default=config.port)
    parser.add_argument("--data-dir", type=Path, default=config.data_dir)
    parser.add_argument("--static-dir", type=Path, default=config.static_dir)
    args = parser.parse_args(argv)
    admin_password_hash = hash_password(config.admin_password) if config.admin_password else ""
    run(
        args.host,
        args.port,
        args.data_dir,
        args.static_dir,
        service_name="wenling-lan-mobile-foundation",
        expose_host_info=True,
        admin_username=config.admin_username,
        admin_password_hash=admin_password_hash,
        initial_invite_codes=config.initial_invite_codes,
        max_rooms=config.max_rooms,
        default_ai_policy=config.default_ai_policy,
    )
