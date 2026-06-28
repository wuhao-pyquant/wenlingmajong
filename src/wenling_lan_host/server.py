from __future__ import annotations

import argparse
import ipaddress
import json
import mimetypes
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from wenling_core import protocol_info
from wenling_core.tile_efficiency import TileEfficiencyPolicyModel
from wenling_core.tiles import TILE_BY_CODE, tile_name

from .battle_app import BattleSession
from .battle_db import BattleDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PUBLIC_GET_PATHS = {
    "/",
    "/battle-login",
    "/battle",
    "/api/tiles",
    "/api/battle/state",
    "/api/battle/wait",
}
PUBLIC_POST_PATHS = {
    "/api/battle/register",
    "/api/battle/login",
    "/api/battle/heartbeat",
    "/api/battle/sit",
    "/api/battle/leave",
    "/api/battle/kick",
    "/api/battle/ready",
    "/api/battle/reset",
    "/api/battle/action",
    "/api/battle/report-bug",
}
PUBLIC_STATIC_PATHS = {
    "/styles.css",
    "/battle_layout.css",
    "/battle_app.js",
    "/battle_lobby.js",
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
    ):
        self.data_dir = data_dir.resolve()
        self.static_dir = static_dir.resolve()
        self.service_name = service_name
        self.bind_host = bind_host
        self.bind_port = bind_port
        self.expose_host_info = expose_host_info
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database = BattleDatabase(self.data_dir / "battle.sqlite3")
        self.session = BattleSession(
            self.database,
            str(self.data_dir / "logs"),
            model_factory=lambda _policy: TileEfficiencyPolicyModel(),
            analysis_model_factory=TileEfficiencyPolicyModel,
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
            },
        }

    def close(self) -> None:
        self.session.close()


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def make_handler(application: BattleApplication) -> type[BaseHTTPRequestHandler]:
    class BattleHandler(BaseHTTPRequestHandler):
        server_version = "WenlingBattle/1.0"

        def _is_local_request(self) -> bool:
            forwarded = []
            for header in ("CF-Connecting-IP", "X-Real-IP", "X-Forwarded-For"):
                value = self.headers.get(header)
                if value:
                    forwarded.extend(part.strip() for part in value.split(",") if part.strip())
            hosts = forwarded or [self.client_address[0] if self.client_address else ""]
            for host in hosts:
                try:
                    if not ipaddress.ip_address(host).is_loopback:
                        return False
                except ValueError:
                    if host not in {"", "localhost"}:
                        return False
            return True

        def _require_local(self) -> bool:
            if self._is_local_request():
                return True
            self._json({"error": "admin endpoint is local-only"}, status=403)
            return False

        def do_GET(self) -> None:
            try:
                parsed = urlparse(self.path)
                path = parsed.path
                public = (
                    path in PUBLIC_GET_PATHS
                    or path in PUBLIC_STATIC_PATHS
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
                if path == "/battle":
                    self._file(application.static_dir / "battle.html")
                    return
                if path == "/battle/accounts":
                    if not self._require_local():
                        return
                    self._file(application.static_dir / "battle_accounts.html")
                    return
                if path == "/api/tiles":
                    self._json({code: tile_name(code) for code in TILE_BY_CODE})
                    return
                if path == "/api/battle/state":
                    query = parse_qs(parsed.query)
                    account = (query.get("account") or [None])[0]
                    self._json(application.session.state(account))
                    return
                if path == "/api/battle/wait":
                    query = parse_qs(parsed.query)
                    account = (query.get("account") or [None])[0]
                    since_raw = (query.get("since") or [None])[0]
                    timeout_raw = (query.get("timeout") or [None])[0]
                    since = int(since_raw) if since_raw not in {None, ""} else None
                    timeout = float(timeout_raw) if timeout_raw not in {None, ""} else 15.0
                    self._json(application.session.wait_state(account, since=since, timeout=timeout))
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
            except Exception as exc:  # pragma: no cover
                self._error(exc)

        def do_POST(self) -> None:
            try:
                path = urlparse(self.path).path
                if not self._is_local_request() and path not in PUBLIC_POST_PATHS:
                    self.send_error(404, "Not found")
                    return
                body = self._read_json()
                if path == "/api/battle/register":
                    self._json(application.session.register(str(body.get("account") or body.get("account_name") or "")))
                    return
                if path == "/api/battle/login":
                    self._json(application.session.login(str(body.get("account") or body.get("account_name") or "")))
                    return
                if path == "/api/battle/heartbeat":
                    self._json(application.session.heartbeat(self._account(body), self._generation(body)))
                    return
                if path == "/api/battle/sit":
                    self._json(application.session.sit(self._account(body), int(body.get("seat", 0)), self._generation(body)))
                    return
                if path == "/api/battle/leave":
                    self._json(application.session.leave(self._account(body), self._generation(body)))
                    return
                if path == "/api/battle/kick":
                    self._json(
                        application.session.kick(
                            self._account(body),
                            str(body.get("target") or ""),
                            self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/ready":
                    self._json(
                        application.session.ready_account(
                            self._account(body),
                            str(body.get("ai_policy") or ""),
                            self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/reset":
                    self._json(application.session.reset_match(self._account(body), self._generation(body)))
                    return
                if path == "/api/battle/report-bug":
                    self._json(
                        application.session.report_bug(
                            self._account(body),
                            note=str(body.get("note") or ""),
                            client_context=body.get("client_context")
                            if isinstance(body.get("client_context"), dict)
                            else {},
                            room_generation=self._generation(body),
                        )
                    )
                    return
                if path == "/api/battle/action":
                    self._json(
                        application.session.action(
                            self._account(body),
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
            except Exception as exc:  # pragma: no cover
                self._error(exc)

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
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
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
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(raw)

        def _error(self, exc: Exception) -> None:
            traceback.print_exc()
            self._json({"error": str(exc)}, status=500)

        def log_message(self, format: str, *args: Any) -> None:
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
) -> None:
    application = BattleApplication(
        data_dir,
        static_dir,
        service_name=service_name,
        bind_host=host,
        bind_port=port,
        expose_host_info=expose_host_info,
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
    parser = argparse.ArgumentParser(description="Run the independent Wenling LAN host service.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("WENLING_LAN_DATA_DIR", PROJECT_ROOT / "data")),
    )
    parser.add_argument(
        "--static-dir",
        type=Path,
        default=Path(os.environ.get("WENLING_LAN_STATIC_DIR", PROJECT_ROOT / "static")),
    )
    args = parser.parse_args(argv)
    run(
        args.host,
        args.port,
        args.data_dir,
        args.static_dir,
        service_name="wenling-lan-mobile-foundation",
        expose_host_info=True,
    )
