from __future__ import annotations

import gzip
import json
import os
import threading
import time
import uuid
from collections import Counter
from pathlib import Path
from typing import Any


BUG_REPORT_SCHEMA_VERSION = 1


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Counter):
        return {str(key): int(count) for key, count in value.items()}
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(json_safe(item) for item in value)
    return repr(value)


class BugReportStore:
    def __init__(
        self,
        root: str | Path,
        persist_interval_sec: float = 5.0,
        export_root: str | Path | None = None,
    ):
        self.root = Path(root)
        self.latest_path = self.root / "latest_round.json.gz"
        self.export_root = Path(export_root) if export_root else None
        self.export_latest_path = self.export_root / "latest_round.json.gz" if self.export_root else None
        self._lock = threading.RLock()
        self._write_lock = threading.Lock()
        self._latest_json: str | None = None
        self._latest_summary: dict[str, Any] = {}
        self._last_report: dict[str, Any] | None = None
        self._persist_interval_sec = max(0.0, float(persist_interval_sec))
        self._last_persisted_at = 0.0
        self._load_latest()

    def update(self, snapshot: dict[str, Any], *, force_persist: bool = False) -> None:
        clean = json_safe(snapshot)
        encoded = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        summary = {
            "available": True,
            "captured_at": clean.get("captured_at"),
            "round_no": (clean.get("game") or {}).get("round_no"),
            "room_generation": (clean.get("room") or {}).get("room_generation"),
            "room_revision": (clean.get("room") or {}).get("room_revision"),
        }
        with self._lock:
            self._latest_json = encoded
            self._latest_summary = summary
            now = time.monotonic()
            should_persist = (
                force_persist
                or not self.latest_path.exists()
                or now - self._last_persisted_at >= self._persist_interval_sec
            )
        if should_persist:
            self._write_gzip_text(self.latest_path, encoded)
            if self.export_latest_path is not None:
                self._write_gzip_text(self.export_latest_path, encoded)
            with self._lock:
                self._last_persisted_at = time.monotonic()

    def create_report(
        self,
        *,
        reporter_account: str,
        note: str = "",
        client_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            latest_json = self._latest_json
        if not latest_json:
            raise ValueError("no battle round is available to report")

        reported_at = time.time()
        report_id = f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(reported_at))}-{uuid.uuid4().hex[:8]}"
        payload = {
            "schema_version": BUG_REPORT_SCHEMA_VERSION,
            "report_id": report_id,
            "reported_at": reported_at,
            "reporter_account": str(reporter_account or "").strip(),
            "note": str(note or "")[:2000],
            "client_context": self._bounded_client_context(client_context or {}),
            "cached_round": json.loads(latest_json),
        }
        file_name = f"bug-{report_id}.json.gz"
        path = self.root / file_name
        self._write_gzip_json(path, payload)
        export_path: Path | None = None
        if self.export_root is not None:
            export_path = self.export_root / file_name
            self._write_gzip_json(export_path, payload)
        result = {
            "ok": True,
            "report_id": report_id,
            "file_name": file_name,
            "file_path": str(path),
            "export_path": str(export_path) if export_path is not None else None,
            "reported_at": reported_at,
            "round_no": payload["cached_round"].get("game", {}).get("round_no"),
            "captured_at": payload["cached_round"].get("captured_at"),
        }
        with self._lock:
            self._last_report = dict(result)
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                **({"available": False} if not self._latest_json else dict(self._latest_summary)),
                "last_report": dict(self._last_report) if self._last_report else None,
                "latest_path": str(self.latest_path),
                "export_latest_path": str(self.export_latest_path) if self.export_latest_path else None,
            }

    def flush(self) -> None:
        with self._lock:
            encoded = self._latest_json
        if encoded:
            self._write_gzip_text(self.latest_path, encoded)

    def close(self) -> None:
        self.flush()

    def _load_latest(self) -> None:
        if not self.latest_path.exists():
            return
        try:
            with gzip.open(self.latest_path, "rt", encoding="utf-8") as handle:
                payload = json.load(handle)
            self._latest_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._latest_summary = {
                "available": True,
                "captured_at": payload.get("captured_at"),
                "round_no": (payload.get("game") or {}).get("round_no"),
                "room_generation": (payload.get("room") or {}).get("room_generation"),
                "room_revision": (payload.get("room") or {}).get("room_revision"),
            }
            self._last_persisted_at = time.monotonic()
        except (OSError, ValueError, TypeError):
            self._latest_json = None
            self._latest_summary = {}

    @staticmethod
    def _bounded_client_context(value: dict[str, Any], max_bytes: int = 64 * 1024) -> dict[str, Any]:
        clean = json_safe(value)
        encoded = json.dumps(clean, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) <= max_bytes:
            return clean
        prefix = encoded.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
        return {
            "truncated": True,
            "original_bytes": len(encoded.encode("utf-8")),
            "json_prefix": prefix,
        }

    def _write_gzip_json(self, path: Path, payload: dict[str, Any]) -> None:
        encoded = json.dumps(json_safe(payload), ensure_ascii=False, separators=(",", ":"))
        self._write_gzip_text(path, encoded)

    def _write_gzip_text(self, path: Path, encoded: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(
            f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        with self._write_lock:
            try:
                with gzip.open(temp_path, "wt", encoding="utf-8") as handle:
                    handle.write(encoded)
                os.replace(temp_path, path)
            finally:
                if temp_path.exists():
                    temp_path.unlink()

