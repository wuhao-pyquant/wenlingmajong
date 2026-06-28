from __future__ import annotations

from collections import Counter
from functools import lru_cache
from math import ceil
from typing import Any

from .tiles import (
    BLACK_FLOWERS,
    DRAGONS,
    FLOWERS,
    RED_FLOWERS,
    SUITS,
    TILE_BY_CODE,
    TILE_ORDER,
    WIND_BY_SEAT,
    flower_number,
    is_dragon,
    is_flower_code,
    is_honor,
    is_suited,
    is_terminal_or_honor,
    is_wind,
    sorted_tiles,
    tile_name,
)


Group = dict[str, Any]


def remove_de_tiles(hand: Counter[str], de_set: set[str]) -> tuple[Counter[str], int]:
    counts = Counter(hand)
    wilds = 0
    for code in list(counts):
        if code in de_set:
            wilds += counts.pop(code)
    return counts, wilds


def _counter_key(counts: Counter[str]) -> tuple[int, ...]:
    return tuple(counts.get(code, 0) for code in TILE_ORDER)


def _counter_from_key(key: tuple[int, ...]) -> Counter[str]:
    return Counter({code: count for code, count in zip(TILE_ORDER, key) if count})


def _group_sort_score(groups: list[Group]) -> int:
    # Prefer natural groups and triplets. This is enough for AI hints and scoring approximation.
    score = 0
    for group in groups:
        score += {"triplet": 9, "sequence": 6, "wild_triplet": 3}.get(group["type"], 0)
        score -= group.get("wilds", 0)
    return score


def _plan_score(plan: dict[str, Any]) -> int:
    return _group_sort_score(plan.get("groups", [])) - plan.get("wilds_used", 0)


def _plan_has_pure_de_shape(plan: dict[str, Any]) -> bool:
    pair = plan.get("pair", {})
    if pair.get("tile") == "de":
        return True
    return any(group.get("tile") == "de" for group in plan.get("groups", []))


def normal_win_plans(hand: Counter[str], de_set: set[str], melds: list[Group] | None = None) -> list[dict[str, Any]]:
    return [plan for plan in win_plans(hand, de_set, melds) if not _plan_has_pure_de_shape(plan)]


def win_plans(hand: Counter[str], de_set: set[str], melds: list[Group] | None = None) -> list[dict[str, Any]]:
    """Return legal pair + groups plans.

    The function is tile-count generic: 14-tile and 17-tile hands both work as long as
    the concealed tile count is 3n+2 after exposed melds have been removed.
    "得" is treated as a wildcard for pair, sequence and triplet only. Exposed kongs
    are supplied through melds and never use wildcards.
    """
    melds = melds or []
    counts, wilds = remove_de_tiles(Counter(hand), de_set)
    concealed_total = sum(counts.values()) + wilds
    if concealed_total % 3 != 2:
        return []

    @lru_cache(maxsize=None)
    def search_groups(key: tuple[int, ...], wild_count: int) -> tuple[tuple[Group, ...], ...]:
        local = _counter_from_key(key)
        if not local:
            if wild_count % 3 == 0:
                return (tuple({"type": "wild_triplet", "tile": "de", "wilds": 3} for _ in range(wild_count // 3)),)
            return tuple()

        first = next(code for code in TILE_ORDER if local.get(code, 0) > 0)
        tile = TILE_BY_CODE[first]
        plans: list[tuple[Group, ...]] = []

        # Triplet using real tiles plus optional "得".
        take = min(3, local[first])
        need = 3 - take
        if need <= wild_count:
            after = Counter(local)
            after[first] -= take
            if after[first] <= 0:
                after.pop(first, None)
            for rest in search_groups(_counter_key(after), wild_count - need):
                plans.append(({"type": "triplet", "tile": first, "wilds": need},) + rest)

        # Sequence in 万/条/筒. The first remaining real tile may be left, middle, or right.
        if tile.suit in SUITS and tile.rank is not None:
            for start in (tile.rank - 2, tile.rank - 1, tile.rank):
                if start < 1 or start > 7:
                    continue
                seq_codes = [f"{tile.suit}{start + offset}" for offset in range(3)]
                after = Counter(local)
                missing = 0
                used: list[str] = []
                for code in seq_codes:
                    if after.get(code, 0) > 0:
                        after[code] -= 1
                        used.append(code)
                        if after[code] <= 0:
                            after.pop(code, None)
                    else:
                        missing += 1
                        used.append("de")
                if missing <= wild_count:
                    for rest in search_groups(_counter_key(after), wild_count - missing):
                        plans.append(({"type": "sequence", "tiles": seq_codes, "shown": used, "wilds": missing},) + rest)

        if not plans:
            return tuple()
        # Keep only the top few plans to avoid combinatorial blowups while preserving alternatives.
        plans.sort(key=lambda p: _group_sort_score(list(p)), reverse=True)
        return tuple(plans[:12])

    pair_candidates: list[tuple[Group, Counter[str], int]] = []
    for code in TILE_ORDER:
        count = counts.get(code, 0)
        if count >= 2:
            after = Counter(counts)
            after[code] -= 2
            if after[code] <= 0:
                after.pop(code, None)
            pair_candidates.append(({"type": "pair", "tile": code, "wilds": 0}, after, wilds))
        if count >= 1 and wilds >= 1:
            after = Counter(counts)
            after[code] -= 1
            if after[code] <= 0:
                after.pop(code, None)
            pair_candidates.append(({"type": "pair", "tile": code, "wilds": 1}, after, wilds - 1))
    if wilds >= 2:
        pair_candidates.append(({"type": "pair", "tile": "de", "wilds": 2}, Counter(counts), wilds - 2))

    plans: list[dict[str, Any]] = []
    for pair, after, remaining_wilds in pair_candidates:
        for groups in search_groups(_counter_key(after), remaining_wilds):
            plan = {
                "pair": pair,
                "groups": list(groups),
                "melds": list(melds),
                "wilds_used": wilds - remaining_wilds + sum(group.get("wilds", 0) for group in groups),
            }
            plans.append(plan)
    plans.sort(key=_plan_score, reverse=True)
    return plans[:64]


def best_win_plan(hand: Counter[str], de_set: set[str], melds: list[Group] | None = None) -> dict[str, Any] | None:
    plans = normal_win_plans(hand, de_set, melds)
    return plans[0] if plans else None


def can_win(hand: Counter[str], de_set: set[str], melds: list[Group] | None = None) -> bool:
    return best_win_plan(hand, de_set, melds) is not None


def legal_discards(hand: Counter[str], de_set: set[str]) -> list[str]:
    return sorted_tiles(code for code, count in hand.items() if count > 0 and code not in de_set)


def concealed_kongs(hand: Counter[str], de_set: set[str]) -> list[str]:
    return sorted_tiles(code for code, count in hand.items() if count >= 4 and code not in de_set and not is_flower_code(code))


def add_kongs(hand: Counter[str], melds: list[Group], de_set: set[str]) -> list[str]:
    pong_tiles = {meld["tile"] for meld in melds if meld["type"] == "peng"}
    return sorted_tiles(code for code in pong_tiles if hand.get(code, 0) >= 1 and code not in de_set)


def can_ming_gang(hand: Counter[str], tile: str, de_set: set[str]) -> bool:
    return tile not in de_set and not is_flower_code(tile) and hand.get(tile, 0) >= 3


def can_peng(hand: Counter[str], tile: str, de_set: set[str]) -> bool:
    return tile not in de_set and not is_flower_code(tile) and hand.get(tile, 0) >= 2


def chi_options(hand: Counter[str], tile: str, de_set: set[str]) -> list[list[str]]:
    if tile in de_set or not is_suited(tile):
        return []
    tile_def = TILE_BY_CODE[tile]
    assert tile_def.rank is not None
    options: list[list[str]] = []
    for start in (tile_def.rank - 2, tile_def.rank - 1, tile_def.rank):
        if start < 1 or start > 7:
            continue
        seq = [f"{tile_def.suit}{start + offset}" for offset in range(3)]
        needed = [code for code in seq if code != tile]
        if all(hand.get(code, 0) > 0 and code not in de_set for code in needed):
            options.append(needed)
    return options


def has_all_flower_numbers(flowers: list[str]) -> bool:
    return {flower_number(code) for code in flowers if flower_number(code)} >= {1, 2, 3, 4}


def leizi_win_reason(hand: Counter[str], flowers: list[str], de_indicator: str, de_set: set[str], seat: int) -> str | None:
    de_count = sum(hand.get(code, 0) for code in de_set)
    if de_count >= 3:
        return "劣子和：手中有 3 张得"
    if de_count == 2 and any(_restored_de_count(plan, de_indicator, include_pure_de=True) >= 2 for plan in win_plans(hand, de_set)):
        return "劣子和：2 张得均还原"
    if has_all_flower_numbers(flowers):
        return "劣子和：红/黑花凑齐 1、2、3、4"

    has_four = lambda code: hand.get(code, 0) >= 4 and code not in de_set
    is_num = TILE_BY_CODE[de_indicator].suit in SUITS
    is_wind_de = is_wind(de_indicator)

    if is_num:
        if has_four("bai"):
            return "劣子和：4 张白板"
        for code in (WIND_BY_SEAT[seat], "fa", "zhong"):
            if has_four(code):
                return f"劣子和：暗杠{TILE_BY_CODE[code].name}"
    elif is_wind_de:
        for code in ("bai", "zhong", "fa"):
            if has_four(code):
                return f"劣子和：4 张{TILE_BY_CODE[code].name}"
        for code in ("east", "south", "west", "north"):
            if code != de_indicator and has_four(code):
                return f"劣子和：暗杠非得门风{TILE_BY_CODE[code].name}"
    elif de_indicator == "zhong":
        for code in ("bai", "fa", WIND_BY_SEAT[seat]):
            if has_four(code):
                return f"劣子和：4 张/暗杠{TILE_BY_CODE[code].name}"
    elif de_indicator == "bai":
        for code in ("zhong", "fa", WIND_BY_SEAT[seat]):
            if has_four(code):
                return f"劣子和：4 张/暗杠{TILE_BY_CODE[code].name}"
    elif de_indicator == "fa":
        for code in ("bai", "zhong", WIND_BY_SEAT[seat]):
            if has_four(code):
                return f"劣子和：4 张/暗杠{TILE_BY_CODE[code].name}"
    elif de_indicator in RED_FLOWERS:
        for code in ("bai", "fa", "zhong", WIND_BY_SEAT[seat]):
            if has_four(code):
                return f"劣子和：4 张/暗杠{TILE_BY_CODE[code].name}"
        if sum(1 for code in flowers if code in BLACK_FLOWERS) >= 4:
            return "劣子和：4 张黑花"
    elif de_indicator in BLACK_FLOWERS:
        for code in ("bai", "fa", "zhong", WIND_BY_SEAT[seat]):
            if has_four(code):
                return f"劣子和：4 张/暗杠{TILE_BY_CODE[code].name}"
        if sum(1 for code in flowers if code in RED_FLOWERS) >= 4:
            return "劣子和：4 张红花"
    return None


def meld_base_points(meld: Group) -> int:
    tile = meld.get("tile")
    if not tile or tile == "de" or tile not in TILE_BY_CODE:
        return 0
    heavy = is_terminal_or_honor(tile)
    if meld["type"] in ("ming_gang", "bu_gang"):
        return 16 if heavy else 8
    if meld["type"] == "an_gang":
        return 32 if heavy else 16
    if meld["type"] == "peng":
        return 4 if heavy else 2
    return 0


def _tile_name(code: str | None) -> str:
    if not code:
        return "得"
    return tile_name(code)


def _meld_type_name(meld_type: str) -> str:
    return {
        "chi": "吃",
        "peng": "碰",
        "ming_gang": "明杠",
        "an_gang": "暗杠",
        "bu_gang": "补杠",
    }.get(meld_type, meld_type)


def _group_type_name(group: Group) -> str:
    group_type = group.get("type", "")
    tile = group.get("tile")
    if group_type == "pair":
        return f"将牌{_tile_name(tile)}"
    if group_type in ("triplet", "wild_triplet"):
        return f"刻子{_tile_name(tile)}"
    if group_type == "sequence":
        return "顺子"
    return group_type


def _group_scoring_tile(group: Group, de_indicator: str | None = None) -> str | None:
    return group.get("tile")


def _group_base_points(group: Group, seat: int, concealed: bool = False, de_indicator: str | None = None) -> int:
    tile = _group_scoring_tile(group, de_indicator)
    if group["type"] == "pair":
        if tile in (WIND_BY_SEAT[seat], *DRAGONS):
            return 2
        return 0
    if group["type"] in ("triplet", "wild_triplet"):
        if not tile or tile == "de":
            return 0
        if concealed:
            return 8 if is_terminal_or_honor(tile) else 4
        return 4 if is_terminal_or_honor(tile) else 2
    return 0


def _is_real_tile(code: str | None) -> bool:
    return bool(code) and code != "de" and code in TILE_BY_CODE


def _is_scoring_honor(tile: str | None, seat: int, de_set: set[str]) -> bool:
    if not _is_real_tile(tile) or tile in de_set:
        return False
    return tile == WIND_BY_SEAT[seat] or is_dragon(tile)


def _current_concealed_score_items(
    hand: Counter[str],
    seat: int,
    de_set: set[str],
    de_indicator: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    counts, wilds = remove_de_tiles(hand, de_set)
    base_items: list[dict[str, Any]] = []
    fan_items: list[dict[str, Any]] = []
    used_triplets: set[str] = set()

    def triplet_points(code: str) -> int:
        return 8 if is_terminal_or_honor(code) else 4

    def add_triplet(code: str, uses_de: int) -> None:
        used_triplets.add(code)
        label_prefix = "含得暗刻" if uses_de else "暗刻"
        base_items.append({"label": f"{label_prefix} {_tile_name(code)}", "points": triplet_points(code)})
        if _is_scoring_honor(code, seat, de_set):
            fan_items.append({"label": f"{label_prefix}{_tile_name(code)}", "fan": 1})

    for code, count in counts.items():
        if count >= 3:
            add_triplet(code, 0)

    candidates: list[tuple[int, int, int, str]] = []
    for code, count in counts.items():
        if code in used_triplets or count <= 0 or count >= 3:
            continue
        need = 3 - count
        if need <= wilds:
            fan_value = 1 if _is_scoring_honor(code, seat, de_set) else 0
            candidates.append((fan_value, triplet_points(code), -need, code))
    candidates.sort(reverse=True)
    remaining_wilds = wilds
    for _fan_value, _points, negative_need, code in candidates:
        need = -negative_need
        if need <= remaining_wilds:
            remaining_wilds -= need
            add_triplet(code, need)

    for code, count in counts.items():
        if code in used_triplets or code not in (WIND_BY_SEAT[seat], *DRAGONS):
            continue
        if count >= 2:
            base_items.append({"label": f"字/门风对子 {_tile_name(code)}", "points": 2})
        elif count == 1 and remaining_wilds >= 1:
            remaining_wilds -= 1
            base_items.append({"label": f"含得字/门风对子 {_tile_name(code)}", "points": 2})

    return base_items, fan_items


def _restored_de_count(plan: dict[str, Any] | None, de_indicator: str, include_pure_de: bool = False) -> int:
    if not plan or not de_indicator or de_indicator not in TILE_BY_CODE or is_flower_code(de_indicator):
        return 0
    restored = 0
    pair = plan.get("pair", {})
    if include_pure_de and pair.get("tile") == "de":
        restored += int(pair.get("wilds", 0) or 0)
    elif pair.get("tile") == de_indicator:
        restored += int(pair.get("wilds", 0) or 0)
    for group in plan.get("groups", []):
        if group.get("type") in ("triplet", "wild_triplet"):
            if group.get("tile") == de_indicator or (include_pure_de and group.get("tile") == "de"):
                restored += int(group.get("wilds", 0) or 0)
            continue
        if group.get("type") != "sequence":
            continue
        for code, shown in zip(group.get("tiles", []), group.get("shown", [])):
            if code == de_indicator and shown == "de":
                restored += 1
    return restored


def _is_double_de_pair(plan: dict[str, Any] | None, hand: Counter[str], de_set: set[str]) -> bool:
    if not plan:
        return False
    pair = plan.get("pair", {})
    if pair.get("tile") != "de" or pair.get("wilds", 0) < 2:
        return False
    de_count = sum(hand.get(code, 0) for code in de_set)
    group_wilds = sum(int(group.get("wilds", 0) or 0) for group in plan.get("groups", []))
    return de_count == 2 and group_wilds == 0


def _is_pang_hu(plan: dict[str, Any] | None, melds: list[Group], seat: int, de_indicator: str) -> bool:
    if not plan:
        return False
    if any(meld.get("type") in {"peng", "ming_gang", "bu_gang", "an_gang"} for meld in melds):
        return False
    pair_tile = plan.get("pair", {}).get("tile")
    if pair_tile == "de":
        return False
    if pair_tile in {*DRAGONS, WIND_BY_SEAT[seat]}:
        return False
    return all(group.get("type") == "sequence" for group in plan.get("groups", []))


def _wait_base_items(
    plan: dict[str, Any] | None,
    win_tile: str | None,
    de_set: set[str] | None = None,
) -> list[dict[str, Any]]:
    if not plan or not win_tile or win_tile not in TILE_BY_CODE or not is_suited(win_tile):
        return []
    items: list[dict[str, Any]] = []
    pair = plan.get("pair", {})
    if pair.get("tile") == win_tile or (pair.get("tile") == "de" and de_set and win_tile in de_set):
        items.append({"label": "单吊", "points": 2})
        return items
    tile = TILE_BY_CODE[win_tile]
    if tile.rank is None:
        return items
    for group in plan.get("groups", []):
        if group.get("type") != "sequence" or win_tile not in group.get("tiles", []):
            continue
        ranks = [TILE_BY_CODE[code].rank for code in group.get("tiles", [])]
        if tile.rank == ranks[1]:
            items.append({"label": "嵌档", "points": 2})
            break
        if (ranks[0] == 1 and tile.rank == 3) or (ranks[0] == 7 and tile.rank == 7):
            items.append({"label": "靠柄", "points": 2})
            break
    return items


def _choose_scoring_plan(
    hand: Counter[str],
    flowers: list[str],
    melds: list[Group],
    seat: int,
    de_set: set[str],
    de_indicator: str,
    winner: bool,
    win_type: str,
    win_tile: str | None,
) -> dict[str, Any] | None:
    candidates = normal_win_plans(hand, de_set, melds)
    if not candidates:
        return None

    def estimate(plan: dict[str, Any]) -> tuple[int, int]:
        base = len(flowers) * 4
        base += sum(meld_base_points(meld) for meld in melds)
        base += _group_base_points(plan["pair"], seat, concealed=True, de_indicator=de_indicator)
        base += sum(_group_base_points(group, seat, concealed=True, de_indicator=de_indicator) for group in plan["groups"])
        if winner:
            if win_type in ("自摸", "自摸得", "杠上开花"):
                base += 2
            base += sum(item["points"] for item in _wait_base_items(plan, win_tile, de_set))

        all_codes = list(hand.elements())
        for meld in melds:
            all_codes.extend(meld.get("tiles", []))
        non_de_non_flower = [
            code for code in all_codes
            if _is_real_tile(code) and code not in de_set and not is_flower_code(code)
        ]

        fan = 0
        fan += sum(1 for code in flowers if code in DRAGONS and code not in de_set)
        fan += sum(1 for code in flowers if code in (f"rh{seat + 1}", f"bh{seat + 1}"))
        for meld in melds:
            if _is_scoring_honor(meld.get("tile"), seat, de_set):
                fan += 1
        for group in plan["groups"]:
            tile = _group_scoring_tile(group, de_indicator)
            if group.get("type") in ("triplet", "wild_triplet") and _is_scoring_honor(tile, seat, de_set):
                fan += 1
        suits = {TILE_BY_CODE[code].suit for code in non_de_non_flower if TILE_BY_CODE[code].suit in SUITS}
        has_honor = any(is_honor(code) for code in non_de_non_flower)
        if len(suits) == 1 and non_de_non_flower:
            fan += 2 if has_honor else 4
        no_sequences = all(group["type"] != "sequence" for group in plan["groups"]) and all(
            meld["type"] != "chi" for meld in melds
        )
        if no_sequences:
            fan += 2
        if winner and _is_pang_hu(plan, melds, seat, de_indicator):
            fan += 1
        if {"east", "south", "west", "north"}.issubset(set(non_de_non_flower)):
            fan += 13
        if winner:
            if win_type in ("杠上开花", "抢杠和", "自摸得"):
                fan += 1
            de_count = sum(hand.get(code, 0) for code in de_set)
            if de_count == 0:
                fan += 1
            if de_count == 2:
                fan += 1
            if _is_double_de_pair(plan, hand, de_set):
                fan += 5
            if _restored_de_count(plan, de_indicator) > 0:
                fan += 1
        scoring_base = base + 20 if winner else base
        return _rounded_score_total(scoring_base, fan), _plan_score(plan)

    return max(candidates, key=estimate)


def score_player(
    hand: Counter[str],
    flowers: list[str],
    melds: list[Group],
    seat: int,
    de_set: set[str],
    de_indicator: str,
    winner: bool = False,
    win_type: str = "",
    win_tile: str | None = None,
) -> dict[str, Any]:
    if winner and win_type == "劣子和":
        return {
            "base": 0,
            "fan": 0,
            "total": 500,
            "raw_total": 500,
            "limit_reason": "劣子和固定按500点结算",
            "plan": [],
            "base_items": [{"label": "劣子和固定点数", "points": 500}],
            "fan_items": [],
            "winning_shape": True,
        }

    plan = _choose_scoring_plan(hand, flowers, melds, seat, de_set, de_indicator, winner, win_type, win_tile)
    base_items: list[dict[str, Any]] = []
    fan_items: list[dict[str, Any]] = []
    base = len(flowers) * 4
    if flowers:
        base_items.append(
            {
                "label": f"花牌 {'、'.join(_tile_name(code) for code in flowers)}",
                "points": len(flowers) * 4,
            }
        )
    for meld in melds:
        points = meld_base_points(meld)
        base += points
        if points:
            base_items.append(
                {
                    "label": f"{_meld_type_name(meld.get('type', ''))} {'、'.join(_tile_name(code) for code in meld.get('tiles', []))}",
                    "points": points,
                }
            )
    fan = 0
    group_desc: list[str] = []

    if plan:
        pair_points = _group_base_points(plan["pair"], seat, concealed=True, de_indicator=de_indicator)
        base += pair_points
        group_desc.append(f"将:{plan['pair'].get('tile', '得')}")
        if pair_points:
            base_items.append({"label": _group_type_name(plan["pair"]), "points": pair_points})
        for group in plan["groups"]:
            points = _group_base_points(group, seat, concealed=True, de_indicator=de_indicator)
            base += points
            group_desc.append(group["type"])
            if points:
                base_items.append({"label": _group_type_name(group), "points": points})
        if winner:
            if win_type in ("自摸", "自摸得", "杠上开花"):
                base += 2
                base_items.append({"label": "自摸", "points": 2})
            for item in _wait_base_items(plan, win_tile, de_set):
                base += item["points"]
                base_items.append(item)
    else:
        # Non-winning hands still receive visible and obvious concealed point credit.
        current_base_items, current_fan_items = _current_concealed_score_items(hand, seat, de_set, de_indicator)
        for item in current_base_items:
            base += int(item.get("points", 0) or 0)
            base_items.append(item)

    all_codes = list(hand.elements())
    for meld in melds:
        all_codes.extend(meld.get("tiles", []))
    non_de_non_flower = [
        code for code in all_codes
        if _is_real_tile(code) and code not in de_set and not is_flower_code(code)
    ]

    for code in flowers:
        if code in DRAGONS and code not in de_set:
            fan += 1
            fan_items.append({"label": f"字牌花 {_tile_name(code)}", "fan": 1})
    for code in flowers:
        if code in (f"rh{seat + 1}", f"bh{seat + 1}"):
            fan += 1
            fan_items.append({"label": f"门风花 {_tile_name(code)}", "fan": 1})
    for meld in melds:
        tile = meld.get("tile")
        if _is_scoring_honor(tile, seat, de_set):
            fan += 1
            fan_items.append({"label": f"{_meld_type_name(meld.get('type', ''))}{_tile_name(tile)}", "fan": 1})
    if plan:
        for group in plan["groups"]:
            tile = _group_scoring_tile(group, de_indicator)
            if group.get("type") in ("triplet", "wild_triplet") and _is_scoring_honor(tile, seat, de_set):
                fan += 1
                fan_items.append({"label": f"刻子{_tile_name(tile)}", "fan": 1})
    else:
        if "current_fan_items" not in locals():
            _current_base_items, current_fan_items = _current_concealed_score_items(hand, seat, de_set, de_indicator)
        for item in current_fan_items:
            fan += int(item.get("fan", 0) or 0)
            fan_items.append(item)

    suits = {TILE_BY_CODE[code].suit for code in non_de_non_flower if TILE_BY_CODE[code].suit in SUITS}
    has_honor = any(is_honor(code) for code in non_de_non_flower)
    if len(suits) == 1 and non_de_non_flower:
        added = 2 if has_honor else 4
        fan += added
        fan_items.append({"label": "混一色" if has_honor else "清一色", "fan": added})

    if plan:
        no_sequences = all(group["type"] != "sequence" for group in plan["groups"]) and all(meld["type"] != "chi" for meld in melds)
        if no_sequences:
            fan += 2
            fan_items.append({"label": "对对和", "fan": 2})
        if winner and _is_pang_hu(plan, melds, seat, de_indicator):
            fan += 1
            fan_items.append({"label": "旁胡", "fan": 1})

    if {"east", "south", "west", "north"}.issubset(set(non_de_non_flower)):
        fan += 13
        fan_items.append({"label": "四风会齐", "fan": 13})

    if winner:
        if win_type in ("杠上开花", "抢杠和", "自摸得"):
            fan += 1
            fan_items.append({"label": win_type, "fan": 1})
        de_count = sum(hand.get(code, 0) for code in de_set)
        if de_count == 0:
            fan += 1
            fan_items.append({"label": "无得", "fan": 1})
        if de_count == 2:
            fan += 1
            fan_items.append({"label": "2张得", "fan": 1})
        if _is_double_de_pair(plan, hand, de_set):
            fan += 5
            fan_items.append({"label": "双得做将", "fan": 5})
        if _restored_de_count(plan, de_indicator) > 0:
            fan += 1
            fan_items.append({"label": "得还原", "fan": 1})

    if winner:
        base += 20
        base_items.append({"label": "胡牌底", "points": 20})

    raw_total = base * (2**fan)
    total = _rounded_score_total(base, fan)
    limit_reason = ""
    if winner and win_type == "劣子和":
        total = 500
        limit_reason = "劣子和固定按500点结算"
    return {
        "base": base,
        "fan": fan,
        "total": total,
        "raw_total": raw_total,
        "limit_reason": limit_reason,
        "plan": group_desc,
        "base_items": base_items,
        "fan_items": fan_items,
        "winning_shape": bool(plan),
    }


def _rounded_score_total(base: int, fan: int) -> int:
    return min(500, int(ceil((base * (2**fan)) / 10.0) * 10))
