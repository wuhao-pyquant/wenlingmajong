from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .battle_db import BattleDatabase
from .server import BattleApplication, ReusableThreadingHTTPServer, make_handler


class AndroidHostBridge:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._application: BattleApplication | None = None
        self._server: ReusableThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._data_dir: Path | None = None
        self._static_dir: Path | None = None
        self._bug_report_export_dir: Path | None = None
        self._runtime_context: dict[str, Any] = {}
        self._port = 8765

    def configure(
        self,
        data_dir: str,
        static_dir: str,
        port: int = 8765,
        bug_report_export_dir: str = "",
        runtime_context_json: str = "{}",
    ) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                raise ValueError("房间运行中不能更改目录或端口")
            self._data_dir = Path(data_dir).resolve()
            self._static_dir = Path(static_dir).resolve()
            self._bug_report_export_dir = (
                Path(bug_report_export_dir).resolve()
                if str(bug_report_export_dir or "").strip()
                else None
            )
            try:
                context = json.loads(runtime_context_json or "{}")
            except ValueError:
                context = {}
            self._runtime_context = context if isinstance(context, dict) else {}
            self._port = int(port)
            if not 1 <= self._port <= 65535:
                raise ValueError("端口必须在 1-65535 之间")
            self._data_dir.mkdir(parents=True, exist_ok=True)
            if self._bug_report_export_dir is not None:
                self._bug_report_export_dir.mkdir(parents=True, exist_ok=True)
        return self.status()

    def start(self) -> dict[str, Any]:
        with self._lock:
            if self._server is not None:
                return self.status()
            data_dir, static_dir = self._configured_paths()
            if not static_dir.is_dir():
                raise ValueError(f"静态资源目录不存在：{static_dir}")
            application = BattleApplication(
                data_dir,
                static_dir,
                service_name="wenling-android-host",
                bind_host="0.0.0.0",
                bind_port=self._port,
                expose_host_info=True,
                compress_json=False,
                quiet_http_logs=True,
                runtime_context=self._runtime_context,
                bug_report_export_dir=self._bug_report_export_dir,
                auto_bug_snapshots=False,
                low_latency_ai=False,
                ticker_interval_sec=0.12,
            )
            try:
                server = ReusableThreadingHTTPServer(
                    ("0.0.0.0", self._port),
                    make_handler(application),
                )
            except Exception:
                application.close()
                raise
            thread = threading.Thread(
                target=server.serve_forever,
                daemon=True,
                name="wenling-android-http",
            )
            self._application = application
            self._server = server
            self._thread = thread
            thread.start()
            return self.status()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            server = self._server
            application = self._application
            thread = self._thread
            self._server = None
            self._application = None
            self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if application is not None:
            application.close()
        if thread is not None and thread.is_alive():
            thread.join(timeout=2.0)
        return self.status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            application = self._application
            running = self._server is not None
            port = self._port
            export_dir = self._bug_report_export_dir
        payload: dict[str, Any] = {
            "ok": True,
            "running": running,
            "port": port,
            "bug_report_export_dir": str(export_dir) if export_dir is not None else None,
        }
        if application is not None:
            state = application.session.host_status()
            payload.update(
                {
                    "room_generation": state.get("room_generation"),
                    "room_revision": state.get("room_revision"),
                    "phase": state.get("phase"),
                    "game_started": state.get("game_started"),
                    "seats": state.get("seats", []),
                    "ready_accounts": state.get("ready_accounts", []),
                    "available_accounts": application.database.active_human_accounts(),
                }
            )
        return payload

    def room_command(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        with self._lock:
            application = self._application
        if application is None:
            raise ValueError("房间尚未启动")
        generation = body.get("room_generation")
        if generation is None:
            generation = application.session.room_generation
        if command == "set_seat":
            return application.session.admin_set_seat(
                str(body.get("account") or ""),
                int(body.get("seat", -1)),
                generation,
            )
        if command in {"clear_seat", "kick"}:
            seat = int(body.get("seat", -1))
            target = None
            if 0 <= seat < len(application.session.seats):
                target = application.session.seats[seat]
            result = application.session.admin_clear_seat(seat, generation)
            if target:
                application.player_sessions.revoke_account(target)
            return result
        if command == "reset_room":
            return application.session.reset_match(None, generation)
        raise ValueError(f"未知房间命令：{command}")

    def accounts(self) -> dict[str, Any]:
        database = self._offline_database()
        return {"ok": True, "accounts": database.accounts(), "db": database.info()}

    def account_command(self, command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        body = payload or {}
        database = self._offline_database()
        backups = database.path.parent / "backups"
        if command == "create":
            row = database.ensure_account(str(body.get("account") or ""), is_ai=False)
            return {"ok": True, "account": row}
        if command == "disable":
            return {"ok": True, "account": database.set_account_enabled(str(body.get("account") or ""), False)}
        if command == "enable":
            return {"ok": True, "account": database.set_account_enabled(str(body.get("account") or ""), True)}
        if command == "clear_stats":
            backup = database.create_backup(backups)
            return {**database.clear_account_stats(str(body.get("account") or "")), "backup": str(backup)}
        if command == "delete":
            backup = database.create_backup(backups)
            return {**database.delete_account(str(body.get("account") or "")), "backup": str(backup)}
        if command == "merge":
            backup = database.create_backup(backups)
            sources = body.get("sources")
            if not isinstance(sources, list):
                raise ValueError("sources 必须是账号数组")
            return {
                **database.merge_accounts(
                    [str(item) for item in sources],
                    str(body.get("target") or ""),
                ),
                "backup": str(backup),
            }
        raise ValueError(f"未知账号命令：{command}")

    def _configured_paths(self) -> tuple[Path, Path]:
        if self._data_dir is None or self._static_dir is None:
            raise ValueError("安卓宿主尚未配置数据目录和静态资源目录")
        return self._data_dir, self._static_dir

    def _offline_database(self) -> BattleDatabase:
        with self._lock:
            if self._server is not None:
                raise ValueError("房间运行中不能管理账号或历史数据")
            data_dir, _ = self._configured_paths()
        return BattleDatabase(data_dir / "battle.sqlite3")


_BRIDGE = AndroidHostBridge()


def _json_call(callback: Any, *args: Any) -> str:
    try:
        return json.dumps(callback(*args), ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)


def configure(
    data_dir: str,
    static_dir: str,
    port: int = 8765,
    bug_report_export_dir: str = "",
    runtime_context_json: str = "{}",
) -> str:
    return _json_call(
        _BRIDGE.configure,
        data_dir,
        static_dir,
        port,
        bug_report_export_dir,
        runtime_context_json,
    )


def start() -> str:
    return _json_call(_BRIDGE.start)


def stop() -> str:
    return _json_call(_BRIDGE.stop)


def status() -> str:
    return _json_call(_BRIDGE.status)


def room_command(command: str, payload_json: str = "{}") -> str:
    payload = json.loads(payload_json or "{}")
    return _json_call(_BRIDGE.room_command, command, payload)


def accounts() -> str:
    return _json_call(_BRIDGE.accounts)


def account_command(command: str, payload_json: str = "{}") -> str:
    payload = json.loads(payload_json or "{}")
    return _json_call(_BRIDGE.account_command, command, payload)
