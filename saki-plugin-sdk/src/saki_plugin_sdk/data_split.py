from __future__ import annotations

import random


def resolve_train_val_split(
    *,
    sample_ids: list[str],
    split_seed: int,
    val_ratio: float,
) -> tuple[set[str], set[str], bool]:
    filtered = [item for item in sample_ids if item]
    if len(filtered) < 5:
        return set(filtered), set(), True

    shuffled = list(filtered)
    random.Random(split_seed).shuffle(shuffled)
    val_count = max(1, int(round(len(shuffled) * val_ratio)))
    if len(shuffled) - val_count < 1:
        val_count = max(1, len(shuffled) - 1)
    if val_count <= 0:
        return set(filtered), set(), True

    val_ids = set(shuffled[:val_count])
    train_ids = set(shuffled[val_count:])
    if not train_ids or not val_ids:
        return set(filtered), set(), True
    return train_ids, val_ids, False
