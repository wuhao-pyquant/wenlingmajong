from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INVITE_CODE_RE = re.compile(r"^[A-Z0-9]{4,6}$")
DEFAULT_INVITE_CODE = "WL1234"


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
        invite_codes: list[str] = [DEFAULT_INVITE_CODE]
        for raw_item in str(env.get("WENLING_INVITE_CODES", "")).split(","):
            code = raw_item.strip().upper()
            if not code:
                continue
            if not INVITE_CODE_RE.fullmatch(code):
                raise ValueError("WENLING_INVITE_CODES entries must be 4-6 uppercase letters or digits")
            if code not in invite_codes:
                invite_codes.append(code)
        max_rooms = int(env.get("WENLING_MAX_ROOMS", "3") or "3")
        if max_rooms < 1 or max_rooms > 3:
            raise ValueError("WENLING_MAX_ROOMS must be between 1 and 3")
        return cls(
            host=str(env.get("WENLING_HOST", "0.0.0.0")),
            port=int(env.get("PORT") or env.get("WENLING_PORT") or "8765"),
            data_dir=Path(env.get("WENLING_DATA_DIR") or env.get("WENLING_LAN_DATA_DIR") or PROJECT_ROOT / "data"),
            static_dir=Path(env.get("WENLING_STATIC_DIR") or env.get("WENLING_LAN_STATIC_DIR") or PROJECT_ROOT / "static"),
            public_base_url=str(env.get("WENLING_PUBLIC_BASE_URL", "")).strip(),
            admin_username=str(env.get("WENLING_ADMIN_USERNAME", "")).strip(),
            admin_password=str(env.get("WENLING_ADMIN_PASSWORD", "")).strip(),
            initial_invite_codes=invite_codes,
            max_rooms=max_rooms,
            default_ai_policy=str(env.get("WENLING_DEFAULT_AI_POLICY", "low")).strip().lower() or "low",
            allow_public_register=False,
        )
