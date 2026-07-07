from __future__ import annotations

from functools import lru_cache

from .hand_luck import HandLuckResult, HandLuckScorer, load_hand_luck_scorer


@lru_cache(maxsize=1)
def default_hand_luck_scorer() -> HandLuckScorer:
    return load_hand_luck_scorer()


__all__ = [
    "HandLuckResult",
    "HandLuckScorer",
    "default_hand_luck_scorer",
    "load_hand_luck_scorer",
]
