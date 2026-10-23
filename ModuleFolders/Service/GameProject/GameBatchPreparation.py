"""One bounded, detached canonical snapshot used by many game batch requests.

A preparation reads the canonical unit graph and the project metadata under the
OS project lock, validates write ownership exactly once and builds private
ordered runs for every primary source file.  Nothing is cached globally and
nothing is persisted: every runner receives detached copies of the units it
selected, so a caller mutating one batch can never affect another batch or the
canonical snapshot.

Reference context is derived only from the canonical graph.  AiNiee cache text,
context and scene extras are never authoritative here.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from pathlib import Path

from ModuleFolders.Domain.GameProject.Models import TranslationUnit

__all__ = [
    'GameBatchPreparation',
    'SIGNATURE_FIELDS',
    'resolved_project_root',
    'resolved_project_root_key',
]

#: Metadata fields that identify the profile/policy snapshot.
SIGNATURE_FIELDS = (
    'project_id',
    'source_root',
    'engine',
    'schema_version',
    'required_features',
    'profile_features',
    'dataset_revision',
    'source_manifest_hash',
    'profile_hash',
    'token_commands',
    'token_literals',
    'token_policy_id',
    'target_language',
    'adapter_id',
    'adapter_version',
)

#: Combined read-only reference text budget in characters.
_REFERENCE_LIMIT = 6000
#: Per-record read-only reference text budget in characters.
_REFERENCE_RECORD_LIMIT = 2000
#: Maximum number of resolved choice question units in one batch.
_QUESTION_LIMIT = 8
#: Primary file key used by units without a captured occurrence.
_UNLOCATED = 'unlocated'


def _canonical_json(value) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
        allow_nan=False,
    )


def _json_copy(value):
    return json.loads(_canonical_json(value))


def resolved_project_root(root) -> Path:
    """Return the absolute project root without requiring it to exist."""

    if isinstance(root, (bytes, bytearray)):
        raise ValueError('PROJECT_ROOT_INVALID: project root must be a string path')
    try:
        text = os.fspath(root)
    except TypeError as error:
        raise ValueError(
            'PROJECT_ROOT_INVALID: project root must be a path-like value'
        ) from error
    if isinstance(text, bytes) or not text:
        raise ValueError('PROJECT_ROOT_INVALID: project root must be a non empty string path')
    if '\x00' in text:
        raise ValueError('PROJECT_ROOT_INVALID: project root must not contain NUL')
    return Path(os.path.abspath(text))


def resolved_project_root_key(root) -> str:
    """Return a case-normalized identity for a resolved project root."""

    return os.path.normcase(str(resolved_project_root(root)))


def _signature(metadata) -> dict:
    if not isinstance(metadata, dict):
        raise ValueError('PREPARATION_REVISION_CONFLICT: project metadata is unavailable')
    return {field: metadata.get(field) for field in SIGNATURE_FIELDS}


def _primary_file(unit: TranslationUnit) -> str:
    return unit.occurrences[0].relative_path if unit.occurrences else _UNLOCATED


def _valid_pointer(value) -> bool:
    """Return whether ``value`` is a non-root RFC6901 JSON pointer."""

    if not isinstance(value, str) or not value.startswith('/'):
        return False
    index = 0
    while index < len(value):
        if value[index] == '~':
            if index + 1 >= len(value) or value[index + 1] not in '01':
                return False
            index += 2
        else:
            index += 1
    return True


def _is_source_code_401(value) -> bool:
    return (type(value) is int and value == 401) or (
        isinstance(value, str) and value == '401'
    )


def _speaker(unit: TranslationUnit) -> str:
    context = unit.context if isinstance(unit.context, dict) else {}
    value = context.get('speaker')
    return value if isinstance(value, str) else ''


def _record(unit: TranslationUnit, text: str, source_length: int) -> dict:
    record = {
        'unit_id': unit.unit_id,
        'source_text': text,
        'kind': unit.kind,
        'speaker': _speaker(unit),
    }
    if len(text) < source_length:
        # Truncation information is added only when a read-only reference
        # string was actually shortened by the total/per-record bound.
        record['truncated'] = True
        record['source_length'] = source_length
    return record


def _bounded_reference(previous, following, questions) -> dict:
    """Return reference records whose canonical SOURCE text is bounded.

    Requested unit text is never handled here.  Every collection preserves
    canonical source order; when the combined text budget is exceeded the
    nearest records are retained and the farthest read-only records omitted.
    """

    collections = (previous, following, questions)
    texts = tuple(tuple(unit.source_text for unit in units) for units in collections)
    per_record_ok = all(
        len(text) <= _REFERENCE_RECORD_LIMIT for values in texts for text in values
    )
    total = sum(len(text) for values in texts for text in values)
    if per_record_ok and total <= _REFERENCE_LIMIT:
        return {
            'previous': [
                _record(unit, unit.source_text, len(unit.source_text)) for unit in previous
            ],
            'following': [
                _record(unit, unit.source_text, len(unit.source_text)) for unit in following
            ],
            'choice_questions': [
                _record(unit, unit.source_text, len(unit.source_text)) for unit in questions
            ],
        }

    allowed = [
        [min(len(text), _REFERENCE_RECORD_LIMIT) for text in values] for values in texts
    ]
    included = set()
    remaining = _REFERENCE_LIMIT
    order = []
    maximum = max((len(values) for values in texts), default=0)
    for index in range(maximum):
        # Interleave nearest previous/following/question records so no one
        # collection consumes the entire budget before the others.
        if index < len(previous):
            order.append((0, len(previous) - 1 - index))
        if index < len(following):
            order.append((1, index))
        if index < len(questions):
            order.append((2, len(questions) - 1 - index))
    for collection, index in order:
        text = texts[collection][index]
        take = min(allowed[collection][index], remaining)
        if take > 0 or len(text) == 0:
            allowed[collection][index] = take
            included.add((collection, index))
            remaining -= take

    def records(collection, units):
        result = []
        for index, unit in enumerate(units):
            if (collection, index) not in included:
                continue
            original = texts[collection][index]
            result.append(
                _record(unit, original[: allowed[collection][index]], len(original))
            )
        return result

    return {
        'previous': records(0, previous),
        'following': records(1, following),
        'choice_questions': records(2, questions),
    }


class GameBatchPreparation:
    """Private canonical graph plus metadata for a scoped batch family."""

    def __init__(self, root):
        self._request_lock=threading.Lock()
        self.root = resolved_project_root(root)
        self.root_key = os.path.normcase(str(self.root))
        from .ProjectLock import ProjectLock
        from .ProjectStore import ProjectStore

        with ProjectLock(self.root), ProjectStore(self.root) as store:
            # Store-level writers do not acquire ProjectLock. Pin both reads to
            # one WAL snapshot so metadata cannot describe a different graph.
            store._connection.execute('BEGIN')
            try:
                metadata = store.metadata()
                units = store.units()
            finally:
                store._connection.rollback()
            from ModuleFolders.Domain.GameProject.WriteOwnership import ownership_issues

            ownership = ownership_issues(units)
            if ownership:
                raise ValueError(ownership[0].code + ': inspect project validation')

        self._metadata = _json_copy(metadata)
        self._signature = _signature(self._metadata)
        self._signature_key = _canonical_json(self._signature)
        self.dataset_revision = self._signature.get('dataset_revision')

        self._units = tuple(units)
        self._by_id = {unit.unit_id: unit for unit in self._units}
        self._primary_file = {
            unit.unit_id: _primary_file(unit) for unit in self._units
        }
        self._run_id = {}
        self._position = {}
        self._runs = []
        self._build_runs()
        self._primary_pointer = {}
        for unit in self._units:
            if not unit.occurrences:
                continue
            pointer = unit.occurrences[0].locator.get('pointer')
            if isinstance(pointer, str):
                key = (self._primary_file[unit.unit_id], pointer)
                self._primary_pointer.setdefault(key, unit)

    @contextmanager
    def request_section(self):
        """Serialize only this family's short OS project-lock sections.

        Model requests remain concurrent. A separate project operation still
        meets the existing nonblocking OS lock and cannot borrow this lock.
        """
        from ModuleFolders.Base.Base import Base
        while not self._request_lock.acquire(timeout=.05):
            if Base.work_status==Base.STATUS.STOPING:raise ValueError('GAME_REQUEST_CANCELLED')
        try:yield
        finally:self._request_lock.release()

    # ------------------------------------------------------------------
    # metadata snapshot validation
    # ------------------------------------------------------------------

    @property
    def signature(self) -> dict:
        return _json_copy(self._signature)

    def validate_metadata(self, metadata) -> None:
        """Raise when fresh project metadata no longer matches this snapshot."""

        fresh = _signature(metadata)
        if fresh.get('dataset_revision') != self._signature.get('dataset_revision'):
            raise ValueError(
                'DATASET_REVISION_CONFLICT: project dataset changed after preparation'
            )
        if _canonical_json(fresh) != self._signature_key:
            raise ValueError(
                'PREPARATION_REVISION_CONFLICT: project profile or policy changed '
                'after preparation'
            )

    # ------------------------------------------------------------------
    # canonical graph access
    # ------------------------------------------------------------------

    def _build_runs(self) -> None:
        # Existing seq values survive replace_units; additions to an old file
        # may append after other files. CacheBridge groups by primary file, so
        # derive continuity from that same per-file order, never global seq.
        files = {}
        for unit in self._units:
            file_key = self._primary_file[unit.unit_id]
            files.setdefault(file_key, []).append(unit)
        for file_key, units in files.items():
            current = []
            current_scene = None
            for unit in units:
                scene = unit.scene_id if isinstance(unit.scene_id, str) else ''
                if current and scene != current_scene:
                    self._register_run(current, file_key, current_scene)
                    current = []
                current_scene = scene
                current.append(unit)
            if current:
                self._register_run(current, file_key, current_scene)

    def _register_run(self, units, file_key, scene) -> None:
        run_id = len(self._runs)
        self._runs.append({'file': file_key, 'scene': scene, 'units': tuple(units)})
        for position, unit in enumerate(units):
            self._run_id[unit.unit_id] = run_id
            self._position[unit.unit_id] = position

    def _unit(self, unit_id):
        return self._by_id.get(unit_id) if isinstance(unit_id, str) else None

    def unit(self, unit_id):
        return self.detached_unit(unit_id)

    def detached_unit(self, unit_id):
        unit = self._unit(unit_id)
        if unit is None:
            return None
        return TranslationUnit.from_dict(unit.to_dict())

    def run_id(self, unit_id):
        return self._run_id.get(unit_id)

    def run_position(self, unit_id):
        return self._position.get(unit_id)

    def primary_file(self, unit_id):
        return self._primary_file.get(unit_id)

    # ------------------------------------------------------------------
    # preceding cache projection validation
    # ------------------------------------------------------------------

    def validate_previous_items(self, previous_items, *, run_id, first_position) -> None:
        """Validate caller-provided preceding cache items against the graph.

        Cache text/context/scene extras are ignored; only the project root,
        unit identity and source hash are read from the caller projection, and
        even those must agree with the canonical same-run source order.
        """

        try:
            sequence = list(previous_items)
        except TypeError as error:
            raise ValueError(
                'INVALID_GAME_CONTEXT: previous_items must be iterable cache items'
            ) from error
        for item in sequence:
            get_extra = getattr(item, 'get_extra', None)
            if not callable(get_extra):
                raise ValueError(
                    'INVALID_GAME_CONTEXT: previous item is not a cache item'
                )
            unit_id = get_extra('unit_id')
            item_hash = get_extra('source_hash')
            item_root = get_extra('game_project_root')
            try:
                same_root = resolved_project_root_key(item_root) == self.root_key
            except ValueError:
                same_root = False
            if not same_root:
                raise ValueError(
                    'MIXED_GAME_PROJECT_BATCH: previous item belongs to another '
                    'project root'
                )
            unit = self._unit(unit_id)
            if unit is None:
                raise ValueError(
                    'INVALID_GAME_CONTEXT: previous item is not a current canonical unit'
                )
            if item_hash != unit.source_hash:
                raise ValueError(
                    'STALE_CACHE_PROJECTION: previous item source hash is not canonical'
                )
            if self.run_id(unit_id) != run_id:
                raise ValueError(
                    'INVALID_GAME_CONTEXT: previous item is not in the requested run'
                )
            position = self.run_position(unit_id)
            if position is None or position >= first_position:
                raise ValueError(
                    'INVALID_GAME_CONTEXT: previous item is not before the first '
                    'requested item'
                )

    # ------------------------------------------------------------------
    # bounded read-only reference context
    # ------------------------------------------------------------------

    def reference_context(self, *, requested_ids, eligible_positions,
                          previous_count, following_count) -> dict:
        """Build the bounded SOURCE-order reference context for one batch."""

        empty = {'previous': [], 'following': [], 'choice_questions': []}
        if not eligible_positions:
            return empty
        ordered = sorted(eligible_positions.items(), key=lambda item: item[1])
        run_ids = {self.run_id(unit_id) for unit_id, _ in ordered}
        if len(run_ids) != 1 or None in run_ids:
            raise ValueError(
                'MIXED_GAME_SCENE_BATCH: requested units span separate canonical runs'
            )
        run_id = next(iter(run_ids))
        run_units = self._runs[run_id]['units']
        minimum = ordered[0][1]
        maximum = ordered[-1][1]
        excluded = set(requested_ids)

        previous = []
        if previous_count > 0:
            position = minimum - 1
            while position >= 0 and len(previous) < previous_count:
                unit = run_units[position]
                if unit.unit_id not in excluded:
                    previous.append(unit)
                position -= 1
            previous.reverse()

        following = []
        if following_count > 0:
            position = maximum + 1
            while position < len(run_units) and len(following) < following_count:
                unit = run_units[position]
                if unit.unit_id not in excluded:
                    following.append(unit)
                position += 1

        questions = []
        seen = set()
        for unit_id, position in ordered:
            unit = self._unit(unit_id)
            if unit is None or unit.kind != 'choice':
                continue
            for candidate in self._choice_questions(unit, run_id, position, excluded):
                if candidate.unit_id in seen:
                    continue
                seen.add(candidate.unit_id)
                questions.append(candidate)
        questions.sort(key=lambda unit: self.run_position(unit.unit_id) or 0)
        questions = questions[:_QUESTION_LIMIT]
        return _bounded_reference(previous, following, questions)

    def _choice_questions(self, unit, run_id, position, excluded):
        """Resolve structurally proven choice question pointers for one unit."""

        context = unit.context if isinstance(unit.context, dict) else {}
        pointers = context.get('choice_question_pointers')
        if not isinstance(pointers, (list, tuple)):
            return ()
        target_file = self.primary_file(unit.unit_id)
        found = []
        seen = set()
        for pointer in pointers:
            if not _valid_pointer(pointer):
                continue
            candidate = self._primary_pointer.get((target_file, pointer))
            if candidate is None or candidate.unit_id in seen:
                continue
            if candidate.unit_id in excluded:
                continue
            if self.run_id(candidate.unit_id) != run_id:
                continue
            candidate_position = self.run_position(candidate.unit_id)
            if candidate_position is None or candidate_position >= position:
                continue
            candidate_context = (
                candidate.context if isinstance(candidate.context, dict) else {}
            )
            if not _is_source_code_401(candidate_context.get('code')):
                continue
            seen.add(candidate.unit_id)
            found.append(candidate)
        return tuple(found)
