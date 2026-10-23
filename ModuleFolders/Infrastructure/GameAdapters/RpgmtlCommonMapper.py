"""Pure mapper for RPGMTL ``CommonEvents.json`` virtual child groups.

The mapper operates only on already parsed data.  It never touches the
filesystem, imports the vendored RPGMTL plugin, calls a model or writer, emits
output, or mutates an input object.
"""

_ERROR_PREFIX = "RPGMTL_COMMON_MAPPING_INVALID"
_CHILDREN_FILE_ID = "::"


def _invalid(detail):
    raise ValueError(f"{_ERROR_PREFIX}: {detail}")


def _known_children(document, relative_path):
    """Validate the CommonEvents array and index its virtual children."""
    if not isinstance(document, list):
        _invalid("document must be an array")

    children = {}
    seen_ids = set()
    seen_markers = set()
    seen_virtual_keys = set()
    for document_index, entry in enumerate(document):
        if entry is None:
            continue
        if not isinstance(entry, dict):
            _invalid(f"document[{document_index}] must be null or an object")
        for field in ("id", "name", "list"):
            if field not in entry:
                _invalid(f"document[{document_index}] is missing '{field}'")

        event_id = entry["id"]
        if type(event_id) is not int or event_id <= 0:
            _invalid(f"document[{document_index}].id must be a positive integer")
        name = entry["name"]
        if not isinstance(name, str):
            _invalid(f"document[{document_index}].name must be a string")
        if not isinstance(entry["list"], list):
            _invalid(f"document[{document_index}].list must be an array")

        if event_id in seen_ids:
            _invalid(f"document[{document_index}].id is duplicated")
        seen_ids.add(event_id)

        suffix = f"{event_id:04d} {name.replace('/', ' ')}"
        marker = _CHILDREN_FILE_ID + suffix
        virtual_key = relative_path + "/" + suffix
        if marker in seen_markers or virtual_key in seen_virtual_keys:
            _invalid(
                f"document[{document_index}] has a duplicate virtual child key"
            )
        seen_markers.add(marker)
        seen_virtual_keys.add(virtual_key)
        children[marker] = (document_index, virtual_key)
    return children


def _validated_changes(changes):
    """Validate translator requests and index them by their exact pointer."""
    if not isinstance(changes, list):
        _invalid("changes must be a list")

    requested = {}
    for change_index, change in enumerate(changes):
        if not isinstance(change, dict):
            _invalid(f"changes[{change_index}] must be an object")
        for field in ("pointer", "source_text", "text"):
            if field not in change:
                _invalid(f"changes[{change_index}] is missing '{field}'")
            if not isinstance(change[field], str):
                _invalid(f"changes[{change_index}].{field} must be a string")

        pointer = change["pointer"]
        if not pointer.startswith("/"):
            _invalid(
                f"changes[{change_index}].pointer must be a non-root JSON pointer"
            )
        if pointer in requested:
            _invalid(f"changes[{change_index}].pointer is duplicated")
        requested[pointer] = {
            "source_text": change["source_text"],
            "text": change["text"],
            "change_index": change_index,
        }
    return requested


def _pointer_segments(pointer, location):
    """Split and strictly unescape a non-root RFC6901 JSON pointer."""
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        _invalid(f"{location} is not a non-root JSON pointer")

    segments = []
    for raw_segment in pointer[1:].split("/"):
        decoded = []
        position = 0
        while position < len(raw_segment):
            character = raw_segment[position]
            if character != "~":
                decoded.append(character)
                position += 1
                continue
            if position + 1 >= len(raw_segment):
                _invalid(f"{location} contains an invalid JSON pointer escape")
            escaped = raw_segment[position + 1]
            if escaped == "0":
                decoded.append("~")
            elif escaped == "1":
                decoded.append("/")
            else:
                _invalid(f"{location} contains an invalid JSON pointer escape")
            position += 2
        segment = "".join(decoded)
        if segment in ('.', '..'):
            _invalid(f"{location} contains a traversal token")
        segments.append(segment)
    return segments


def _array_index(segment, location):
    """Return a canonical array index, rejecting every noncanonical spelling."""
    if segment == "0":
        return 0
    if (
        not segment
        or segment[0] == "0"
        or any(character < "0" or character > "9" for character in segment)
    ):
        _invalid(f"{location} contains a noncanonical array index")
    # No real list can have an index this long; avoiding int() also keeps a
    # pathological pointer from escaping the mapper's error contract.
    if len(segment) > 20:
        _invalid(f"{location} is out of bounds")
    return int(segment)


def _resolve_pointer(document, segments, location):
    """Resolve decoded segments from the document root without shortcuts."""
    node = document
    for segment in segments:
        if isinstance(node, list):
            index = _array_index(segment, location)
            if index >= len(node):
                _invalid(f"{location} is out of bounds")
            node = node[index]
        elif isinstance(node, dict):
            if segment not in node:
                _invalid(f"{location} does not resolve")
            node = node[segment]
        else:
            _invalid(f"{location} does not resolve")
    return node


def _prove_item_pointer(
    document,
    document_index,
    item,
    pointer,
    group_index,
    item_index,
):
    """Prove one item pointer through the child's real list and its text."""
    location = f"group[{group_index}] item[{item_index}] pointer"
    segments = _pointer_segments(pointer, location)
    if (
        len(segments) < 3
        or segments[0] != str(document_index)
        or segments[1] != "list"
    ):
        _invalid(f"{location} is outside the current virtual child")
    resolved = _resolve_pointer(document, segments, location)
    if not isinstance(resolved, str) or resolved != str(item):
        _invalid(f"{location} does not prove the item text")


def map_common_events(groups, relative_path, document, changes):
    """Map RPGMTL CommonEvents groups into the AiNiee project structure."""
    if not isinstance(relative_path, str):
        _invalid("relative_path must be a string")

    known_children = _known_children(document, relative_path)
    requested = _validated_changes(changes)
    if not isinstance(groups, (list, tuple)):
        _invalid("groups must be an array of groups")

    strings = {}
    files = {}
    found = {}
    next_global_id = 0
    current_child = None
    seen_markers = set()

    for group_index, group in enumerate(groups):
        if not isinstance(group, (list, tuple)) or not group:
            _invalid(f"group[{group_index}] must be a nonempty array")

        label = group[0]
        if isinstance(label, str) and label.startswith(_CHILDREN_FILE_ID):
            if len(group) != 1:
                _invalid(
                    f"group[{group_index}] is a multi-item virtual child marker"
                )
            child = known_children.get(label)
            if child is None:
                _invalid(
                    f"group[{group_index}] has an unknown virtual child marker"
                )
            if label in seen_markers:
                _invalid(f"group[{group_index}] repeats a virtual child marker")
            seen_markers.add(label)
            current_child = child
            files.setdefault(child[1], [])
            continue

        if current_child is None:
            _invalid(
                f"group[{group_index}] appears before any virtual child marker"
            )
        if not isinstance(label, str):
            _invalid(f"group[{group_index}] label must be a string")

        child_document_index, virtual_child = current_child
        built_group = [label]
        for item_index in range(1, len(group)):
            item = group[item_index]
            if not isinstance(item, str):
                _invalid(
                    f"group[{group_index}] item[{item_index}] must be a string"
                )

            pointer = getattr(item, "pointer", None)
            local_translation = None
            modified = 0
            if isinstance(pointer, str):
                _prove_item_pointer(
                    document,
                    child_document_index,
                    item,
                    pointer,
                    group_index,
                    item_index,
                )
                change = requested.get(pointer)
                if change is not None:
                    if pointer in found:
                        _invalid(
                            f"group[{group_index}] item[{item_index}] "
                            "repeats a requested pointer"
                        )
                    if str(item) != change["source_text"]:
                        _invalid(
                            f"group[{group_index}] item[{item_index}] "
                            "source text does not match"
                        )
                    local_translation = change["text"]
                    modified = 1
                    found[pointer] = {
                        "pointer": pointer,
                        "group_index": group_index,
                        "item_index": item_index,
                        "global_id": next_global_id,
                        "virtual_child": virtual_child,
                    }

            strings[next_global_id] = [str(item), None, 1, 0]
            built_group.append(
                [next_global_id, local_translation, 1, 0, modified]
            )
            next_global_id += 1

        files[virtual_child].append(built_group)

    for pointer, change in requested.items():
        if pointer not in found:
            _invalid(
                f"changes[{change['change_index']}] "
                "was not proven by the traversal"
            )

    return {
        "project_strings": {"strings": strings, "files": files},
        "project": {
            "files": {
                virtual_child: {"ignored": 0} for virtual_child in files
            }
        },
        "found": found,
    }
