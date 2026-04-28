from __future__ import annotations

import re
from functools import cmp_to_key


QUALIFIER_RANK = {
    "snapshot": -5,
    "alpha": -4,
    "a": -4,
    "beta": -3,
    "b": -3,
    "milestone": -2,
    "m": -2,
    "rc": -1,
    "cr": -1,
    "": 0,
    "final": 0,
    "ga": 0,
    "release": 0,
    "sp": 1,
}


def split_version(version: str) -> list[int | str]:
    parts: list[int | str] = []
    for token in re.split(r"[.\-_/]+", version.lower()):
        if not token:
            continue
        for piece in re.findall(r"\d+|[a-zA-Z]+", token):
            parts.append(int(piece) if piece.isdigit() else piece.lower())
    return parts


def compare_versions(left: str, right: str) -> int:
    left_parts = split_version(left)
    right_parts = split_version(right)
    max_len = max(len(left_parts), len(right_parts))
    for index in range(max_len):
        left_item = left_parts[index] if index < len(left_parts) else 0
        right_item = right_parts[index] if index < len(right_parts) else 0
        result = compare_part(left_item, right_item)
        if result:
            return result
    return 0


def compare_part(left: int | str, right: int | str) -> int:
    if isinstance(left, int) and isinstance(right, int):
        return (left > right) - (left < right)
    if isinstance(left, int):
        if left == 0 and isinstance(right, str):
            return compare_part("", right)
        return 1
    if isinstance(right, int):
        if right == 0 and isinstance(left, str):
            return compare_part(left, "")
        return -1

    left_rank = QUALIFIER_RANK.get(left, 10)
    right_rank = QUALIFIER_RANK.get(right, 10)
    if left_rank != right_rank:
        return (left_rank > right_rank) - (left_rank < right_rank)
    return (left > right) - (left < right)


def latest_version(versions: list[str]) -> str | None:
    if not versions:
        return None
    return sorted(versions, key=cmp_to_key(compare_versions))[-1]


def sort_versions(versions: list[str]) -> list[str]:
    return sorted(versions, key=cmp_to_key(compare_versions))

