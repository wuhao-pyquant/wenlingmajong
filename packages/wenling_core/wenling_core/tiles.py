from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class TileDef:
    code: str
    name: str
    suit: str
    rank: int | None = None


SUITS = ("m", "t", "b")
SUIT_NAMES = {"m": "万", "t": "条", "b": "筒"}
WINDS = ("east", "south", "west", "north")
WIND_NAMES = {"east": "东风", "south": "南风", "west": "西风", "north": "北风"}
DRAGONS = ("zhong", "fa", "bai")
DRAGON_NAMES = {"zhong": "红中", "fa": "发财", "bai": "白板"}
RED_FLOWERS = ("rh1", "rh2", "rh3", "rh4")
BLACK_FLOWERS = ("bh1", "bh2", "bh3", "bh4")
FLOWERS = RED_FLOWERS + BLACK_FLOWERS
WIND_BY_SEAT = {0: "east", 1: "south", 2: "west", 3: "north"}
SEAT_NAME = {0: "东", 1: "南", 2: "西", 3: "北"}


def _make_tiles() -> list[TileDef]:
    tiles: list[TileDef] = []
    cn_nums = "一二三四五六七八九"
    for suit in SUITS:
        for rank in range(1, 10):
            tiles.append(TileDef(f"{suit}{rank}", f"{cn_nums[rank - 1]}{SUIT_NAMES[suit]}", suit, rank))
    for code in WINDS:
        tiles.append(TileDef(code, WIND_NAMES[code], "wind"))
    for code in DRAGONS:
        tiles.append(TileDef(code, DRAGON_NAMES[code], "dragon"))
    for i, code in enumerate(RED_FLOWERS, start=1):
        tiles.append(TileDef(code, f"红花{i}", "flower", i))
    for i, code in enumerate(BLACK_FLOWERS, start=1):
        tiles.append(TileDef(code, f"黑花{i}", "flower", i))
    return tiles


TILES = _make_tiles()
TILE_BY_CODE = {tile.code: tile for tile in TILES}
TILE_ORDER = [tile.code for tile in TILES]
TILE_INDEX = {code: i for i, code in enumerate(TILE_ORDER)}


def tile_name(code: str) -> str:
    return TILE_BY_CODE.get(code, TileDef(code, code, "unknown")).name


def is_suited(code: str) -> bool:
    return TILE_BY_CODE[code].suit in SUITS


def is_wind(code: str) -> bool:
    return TILE_BY_CODE[code].suit == "wind"


def is_dragon(code: str) -> bool:
    return TILE_BY_CODE[code].suit == "dragon"


def is_honor(code: str) -> bool:
    return is_wind(code) or is_dragon(code)


def is_flower_code(code: str) -> bool:
    return code in FLOWERS


def is_terminal(code: str) -> bool:
    tile = TILE_BY_CODE[code]
    return tile.suit in SUITS and tile.rank in (1, 9)


def is_terminal_or_honor(code: str) -> bool:
    return is_terminal(code) or is_honor(code)


def same_family_de_set(indicator: str) -> set[str]:
    if indicator in RED_FLOWERS:
        return set(RED_FLOWERS)
    if indicator in BLACK_FLOWERS:
        return set(BLACK_FLOWERS)
    return {indicator}


def flower_set_for_de(indicator: str) -> set[str]:
    """Return the complete flower range for a round, following the rule document."""
    tile = TILE_BY_CODE[indicator]
    all_flowers = set(FLOWERS)
    if tile.suit in SUITS:
        return {"bai"} | all_flowers
    if tile.suit == "wind":
        return set(DRAGONS) | all_flowers
    if indicator == "zhong":
        return {"fa", "bai"} | all_flowers
    if indicator == "bai":
        return {"fa", "zhong"} | all_flowers
    if indicator == "fa":
        return {"zhong", "bai"} | all_flowers
    if indicator in RED_FLOWERS:
        return set(DRAGONS) | set(BLACK_FLOWERS)
    if indicator in BLACK_FLOWERS:
        return set(DRAGONS) | set(RED_FLOWERS)
    return set()


def build_wall() -> list[str]:
    wall: list[str] = []
    for tile in TILES:
        count = 1 if tile.code in FLOWERS else 4
        wall.extend([tile.code] * count)
    return wall


def sorted_tiles(codes: Iterable[str]) -> list[str]:
    return sorted(codes, key=lambda code: TILE_INDEX[code])


def flower_number(code: str) -> int | None:
    if code in RED_FLOWERS or code in BLACK_FLOWERS:
        return TILE_BY_CODE[code].rank
    return None

