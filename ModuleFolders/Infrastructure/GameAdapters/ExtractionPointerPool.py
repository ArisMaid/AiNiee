"""Lossless transport for repeated backend candidate-pointer arrays.

Packing keeps small arrays inline.  Large arrays are moved to a shared pool so
that repeated references cost one group id instead of a full copy per record.
The pooled representation is intentionally small and schema-versioned; the
legacy inline representation remains the default for small results.
"""

import re


INVALID_BACKEND_LOCATOR = "INVALID_BACKEND_LOCATOR"
BACKEND_POINTER_POOL_INVALID = "BACKEND_POINTER_POOL_INVALID"

_GROUP_ID_RE = re.compile(r"g(?:0|[1-9][0-9]*)\Z")
_MISSING = object()


def _validate_pointer_list(value, error_code):
    """Validate a list of strings without copying it."""
    if not isinstance(value, list):
        raise ValueError(error_code)
    for pointer in value:
        if not isinstance(pointer, str):
            raise ValueError(error_code)


def _snapshot_pointers(pointers):
    """Validate a large list while building its one-time lookup snapshot."""
    values = []
    append = values.append
    for pointer in pointers:
        if not isinstance(pointer, str):
            raise ValueError(INVALID_BACKEND_LOCATOR)
        append(pointer)
    return tuple(values)


def _validate_group_id(group_id):
    return isinstance(group_id, str) and _GROUP_ID_RE.fullmatch(group_id) is not None


def pack_records(records, threshold=32):
    """Return records, pooling large candidate pointer arrays by value.

    Input rows are never mutated.  A shared input list is validated and hashed
    only once; equal arrays held by distinct list objects still resolve to the
    same pool group.
    """
    if type(threshold) is not int or threshold < 2:
        raise ValueError(INVALID_BACKEND_LOCATOR)
    if not isinstance(records, list):
        raise ValueError(INVALID_BACKEND_LOCATOR)

    packed_records = []
    groups = {}
    group_by_pointers = {}
    group_by_identity = {}

    for row in records:
        if not isinstance(row, dict):
            raise ValueError(INVALID_BACKEND_LOCATOR)

        output_row = dict(row)
        if "candidate_pointers" not in row:
            # Missing arrays are semantically empty and keep their missing
            # shape, so no field is added for legacy/small records.
            packed_records.append(output_row)
            continue

        pointers = row["candidate_pointers"]
        if not isinstance(pointers, list):
            raise ValueError(INVALID_BACKEND_LOCATOR)

        if len(pointers) < threshold:
            _validate_pointer_list(pointers, INVALID_BACKEND_LOCATOR)
            packed_records.append(output_row)
            continue

        pointers_id = id(pointers)
        cached = group_by_identity.get(pointers_id)
        if cached is not None and cached[0] is pointers:
            group_id = cached[1]
        else:
            # The first occurrence of this list object performs validation and
            # tuple construction.  Repeated references by identity take the
            # fast path above.
            pointer_tuple = _snapshot_pointers(pointers)
            group_id = group_by_pointers.get(pointer_tuple)
            if group_id is None:
                group_id = "g%d" % len(groups)
                group_by_pointers[pointer_tuple] = group_id
                # The tuple is the validated snapshot; copy it exactly once
                # into the pool.
                groups[group_id] = list(pointer_tuple)
            group_by_identity[pointers_id] = (pointers, group_id)

        del output_row["candidate_pointers"]
        output_row["candidate_pointer_group"] = group_id
        packed_records.append(output_row)

    if not groups:
        return {"records": packed_records}

    return {
        "records": packed_records,
        "pointer_pool_schema": 1,
        "candidate_pointer_groups": groups,
    }


def pointer_lists(result):
    """Resolve a packed or legacy result to pointer lists in record order.

    Shared groups are validated once and their list objects are returned
    directly.  Inline lists are borrowed as well; the input is never mutated.
    """
    if not isinstance(result, dict):
        raise ValueError(INVALID_BACKEND_LOCATOR)
    records = result.get("records", _MISSING)
    if not isinstance(records, list):
        raise ValueError(INVALID_BACKEND_LOCATOR)
    for row in records:
        if not isinstance(row, dict):
            raise ValueError(INVALID_BACKEND_LOCATOR)

    has_schema = "pointer_pool_schema" in result
    has_groups = "candidate_pointer_groups" in result

    if has_schema or has_groups:
        if not (has_schema and has_groups):
            raise ValueError(BACKEND_POINTER_POOL_INVALID)

        version = result["pointer_pool_schema"]
        if type(version) is not int or version != 1:
            raise ValueError(BACKEND_POINTER_POOL_INVALID)

        groups = result["candidate_pointer_groups"]
        if not isinstance(groups, dict):
            raise ValueError(BACKEND_POINTER_POOL_INVALID)

        # Every pool is validated exactly once, including unused groups.
        for group_id, pointers in groups.items():
            if not _validate_group_id(group_id):
                raise ValueError(BACKEND_POINTER_POOL_INVALID)
            _validate_pointer_list(pointers, BACKEND_POINTER_POOL_INVALID)

        resolved = []
        for row in records:
            has_reference = "candidate_pointer_group" in row
            has_inline = "candidate_pointers" in row

            if has_reference and has_inline:
                raise ValueError(BACKEND_POINTER_POOL_INVALID)

            if has_reference:
                group_id = row["candidate_pointer_group"]
                if not _validate_group_id(group_id):
                    raise ValueError(BACKEND_POINTER_POOL_INVALID)
                if group_id not in groups:
                    raise ValueError(BACKEND_POINTER_POOL_INVALID)
                resolved.append(groups[group_id])
            elif has_inline:
                pointers = row["candidate_pointers"]
                _validate_pointer_list(pointers, INVALID_BACKEND_LOCATOR)
                resolved.append(pointers)
            else:
                resolved.append([])

        return resolved

    # Legacy results have no pool.  A group reference in this shape has
    # nowhere to resolve, so it is still a pool error rather than an empty
    # inline record.
    resolved = []
    for row in records:
        if "candidate_pointer_group" in row:
            raise ValueError(BACKEND_POINTER_POOL_INVALID)

        if "candidate_pointers" in row:
            pointers = row["candidate_pointers"]
            _validate_pointer_list(pointers, INVALID_BACKEND_LOCATOR)
            resolved.append(pointers)
        else:
            resolved.append([])

    return resolved
