from __future__ import annotations


CORE_VERSION = "1.0.0-split-baseline.20260628"
SERIALIZATION_PROTOCOL_VERSION = 1


def protocol_info() -> dict[str, str | int]:
    return {
        "core_version": CORE_VERSION,
        "serialization_protocol_version": SERIALIZATION_PROTOCOL_VERSION,
    }
