from __future__ import annotations

from .game import WenlingMahjongGame
from .tiles import FLOWERS, TILE_BY_CODE


def _claimed_discard_indices(game: WenlingMahjongGame) -> dict[int, set[int]]:
    claimed: dict[int, set[int]] = {}
    for event in getattr(game, "discard_events", []):
        if event.get("claimed_by") is None:
            continue
        seat = event.get("seat")
        index = event.get("discard_index")
        if isinstance(seat, int) and isinstance(index, int):
            claimed.setdefault(seat, set()).add(index)
    return claimed


def _live_tile_count(game: WenlingMahjongGame, code: str) -> int:
    return sum(count for _, count in _live_tile_locations(game, code))


def _live_tile_locations(game: WenlingMahjongGame, code: str) -> list[tuple[str, int]]:
    locations: list[tuple[str, int]] = []
    count = game.wall.count(code)
    if count:
        locations.append(("wall", count))
    claimed = _claimed_discard_indices(game)
    for seat, player in enumerate(game.players):
        hand_count = player.hand.get(code, 0)
        if hand_count:
            locations.append((f"seat {seat} hand", hand_count))
        flower_count = player.flowers.count(code)
        if flower_count:
            locations.append((f"seat {seat} flowers", flower_count))
        discard_count = 0
        for index, tile in enumerate(player.discards):
            if index not in claimed.get(seat, set()) and tile == code:
                discard_count += 1
        if discard_count:
            locations.append((f"seat {seat} unclaimed discards", discard_count))
        for meld in player.melds:
            meld_count = meld.get("tiles", []).count(code)
            if meld_count:
                locations.append((f"seat {seat} {meld.get('type', 'meld')}", meld_count))
    return locations


def validate_game_state(game: WenlingMahjongGame) -> list[str]:
    issues: list[str] = []
    for seat, player in enumerate(game.players):
        for tile in player.discards:
            if tile in game.de_set:
                issues.append(f"seat {seat} discarded de tile {tile}")
        for tile in player.hand:
            if tile in game.flower_set:
                issues.append(f"seat {seat} still has flower tile {tile} in hand")
        for flower in player.flowers:
            if flower not in game.flower_set:
                issues.append(f"seat {seat} exposed non-flower supplement tile {flower}")
        for meld in player.melds:
            if meld["type"] in {"an_gang", "ming_gang", "bu_gang"}:
                tiles = meld.get("tiles", [])
                if len(tiles) != 4 or len(set(tiles)) != 1:
                    issues.append(f"seat {seat} has malformed kong {meld}")
                if meld.get("tile") in game.de_set:
                    issues.append(f"seat {seat} used de tile in kong {meld}")
            if meld["type"] == "chi" and any(tile in game.de_set for tile in meld.get("tiles", [])):
                issues.append(f"seat {seat} used de tile in chi {meld}")
    serialized = game.serialize()
    for player in serialized["players"]:
        if any(tile == "*" for tile in player.get("flowers", [])):
            issues.append(f"seat {player['seat']} has hidden flower placeholder in public state")
    if game.de_indicator not in game.de_set and game.de_indicator not in FLOWERS:
        issues.append("de indicator is not represented in de set")
    for code in TILE_BY_CODE:
        original_count = 1 if code in FLOWERS else 4
        max_live_count = original_count - (1 if code == game.de_indicator else 0)
        live_count = _live_tile_count(game, code)
        if live_count > max_live_count:
            locations = ", ".join(f"{where}:{count}" for where, count in _live_tile_locations(game, code))
            issues.append(
                f"tile {code} appears {live_count} times in live tiles; "
                f"expected at most {max_live_count}; locations: {locations}"
            )
    return issues
