"""Contiguous game-scene runs shared by cache and game-table batching.

Invariant: runs are non-empty, contiguous, original-order slices with one
normalized ``scene_id`` each. Empty IDs are their own unchanged value, so a
file without scene IDs retains within-file batching. A known scene cannot
absorb unknown-scene items: the canonical request guard checks the same keys.
Repeated scenes separated by a different or empty scene remain separate runs.
"""


def _scene_id(item) -> str:
    """Return the item's scene ID, treating missing/non-text values as empty."""
    value = item.get_extra("scene_id")
    return value if isinstance(value, str) else ""


def contiguous_scene_runs(items) -> list[list]:
    """Split ``items`` at each normalized scene change, preserving order."""
    runs = []
    current_run = []
    current_scene_id = ""

    for item in items:
        scene_id = _scene_id(item)
        if current_run and scene_id != current_scene_id:
            runs.append(current_run)
            current_run = []
        current_run.append(item)
        current_scene_id = scene_id

    if current_run:
        runs.append(current_run)
    return runs
