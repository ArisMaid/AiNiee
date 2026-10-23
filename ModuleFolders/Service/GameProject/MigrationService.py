"""Cross-version translation migration between two project stores.

Contract: ``docs/rpg/MIGRATION_V2_CONTRACT.md``.

A unit is identified by the canonical identity of its occurrences --
``relative_path`` plus backend (adapter) plus JSON pointer or JS object path --
never by a unit ID (IDs legitimately differ between project versions) and never
by fuzzy string similarity.  A JS object path that declares a
``scope_function`` carries that function in its identity, so the same property
name in two functions can never be treated as one location; an unscoped object
path keeps the legacy identity.  An occurrence set that is empty, contains an
occurrence without a stable location or repeats one canonical location is
unidentifiable: the whole unit is never matched instead of being silently
reduced to a partial set.

* :func:`plan_migration` proposes reuse in two phases.  ``exact_location``
  requires exactly one old and one new unit with the complete occurrence set
  (path, backend, role, stable locator), the same source hash, the same scene
  anchor fields and the same remaining context (transient extraction positions
  such as ``command_index`` excluded).  ``unique_scene_anchor`` requires the
  ``(source hash, scene anchor)`` pair to identify exactly one old and one new
  unit in the complete datasets.  The anchor keeps scene id, kind, speaker, the
  sorted occurrence multiset, the JS scope/object binding and the event
  code/variable_id/table/field, so a pointer that moved under a stable
  scene/file/context proof can be reused while a different scene, speaker,
  kind, scope, role, occurrence count or file name can not.
* Safe pairs are reserved globally before the remaining targets are classified.
  Every target ends up exactly once in ``reconciliation`` (``reused``, ``new``,
  ``modified`` or ``conflict``) and every old unit without a unique counterpart
  is ``orphaned`` once.  Missing project identity produces a readable plan with
  no matches and one ``PROJECT_IDENTITY_UNVERIFIED`` conflict per target
  instead of an invented lineage.
* Reuse additionally requires a nonempty, non stale old translation bound to
  the old source hash, an unchanged token interpretation under both stores'
  policies (ordered ``(raw, command)`` signatures for the source and the
  proposed translation, no scanner issues, both policies' ``validate``) and
  passing ``validate_display_value`` for the old and the new context.  Target
  manual locks and existing non stale target translations stay conflicts.
* :func:`apply_migration` re-plans, rejects duplicate or malformed supplied
  pairs before any write, re-verifies every requested pair, source hash,
  translation text and ``expected_revision`` and submits the verified matches
  through :class:`TranslationCommitter` with ``origin='migration'``.  Current
  source hashes, revisions and manual locks are rechecked before every submit;
  no SQL is issued by this module and the old store is never written.

The caller owns the project writer lock (:class:`ProjectLock`); this module
never takes it and never writes to the old store directly.

Reason codes used by ``review`` and ``reconciliation`` rows:
``UNIDENTIFIABLE_LOCATOR``, ``MULTIPLE_OLD_CANDIDATES``,
``AMBIGUOUS_SCENE_ANCHOR``, ``AMBIGUOUS_OWNERSHIP``,
``SOURCE_TEXT_AT_DIFFERENT_LOCATOR``, ``LOCATOR_SET_CHANGED``,
``SOURCE_CHANGED`` (a modified pair), ``TOKEN_POLICY_MISMATCH``,
``DISPLAY_VALUE_CONSTRAINT``, ``OLD_UNTRANSLATED``, ``OLD_TRANSLATION_STALE``,
``TARGET_LOCKED``, ``TARGET_TRANSLATED``, ``PROJECT_IDENTITY_UNVERIFIED``,
``NEW`` and ``ORPHANED``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping

from ModuleFolders.Domain.GameProject.Models import TranslationProposal
from ModuleFolders.Domain.GameProject.TokenPolicy import TokenPolicy
from ModuleFolders.Domain.GameProject.ValueConstraints import validate_display_value

from .TranslationCommitter import TranslationCommitter

__all__ = [
    'MIGRATION_ORIGIN',
    'apply_migration',
    'canonical_occurrence_identities',
    'plan_migration',
]

#: Origin recorded on every proposal created by :func:`apply_migration`.
MIGRATION_ORIGIN = 'migration'

#: Delivery-key namespace.  Re-applying the same match replays the stored
#: result instead of writing a second accepted revision.
_MIGRATION_JOB_ID = 'migration'

#: Identity namespace of scoped JS locators.  It is deliberately distinct from
#: the legacy ``object-path:`` namespace so a property inside one function can
#: never collide with a global property or with the same name in another one.
_SCOPED_LOCATOR_NAMESPACE = 'scoped-object-path'

#: A declared JS scope must be a single non empty ASCII JS identifier.  The
#: bound keeps a runaway/hostile field from being folded into an identity.
_SCOPE_FUNCTION_MAX_LENGTH = 128

#: ``$`` and ``_`` may start an identifier, digits may not.
_JS_IDENTIFIER_RE = re.compile(r'[A-Za-z_$][A-Za-z0-9_$]*')

#: Default target language of a project that does not declare one.
_DEFAULT_TARGET_LANGUAGE = 'zh-CN'

#: Context keys that describe a transient extraction position instead of the
#: logical element.  They are excluded from the exact location comparison; the
#: scene anchor never looks at them either.
_TRANSIENT_CONTEXT_KEYS = frozenset({'command_index'})

#: Event context keys that belong to a stable scene anchor when present.
_ANCHOR_CONTEXT_KEYS = ('code', 'variable_id', 'table', 'field')

#: Human readable detail per reason code (the machine readable code is the key).
_REASON_DETAIL = {
    'UNIDENTIFIABLE_LOCATOR': '单元没有完整且唯一的稳定定位信息',
    'MULTIPLE_OLD_CANDIDATES': '同一位置对应多个旧单元，需要人工确认',
    'AMBIGUOUS_SCENE_ANCHOR': '场景锚在任一侧数据集中不唯一，不能自动复用',
    'AMBIGUOUS_OWNERSHIP': '同一个旧单元被多个目标占用，不能自动复用',
    'SOURCE_TEXT_AT_DIFFERENT_LOCATOR': '相同原文出现在不同定位，需人工确认',
    'LOCATOR_SET_CHANGED': '同一位置的场景/说话人/类型/作用域/上下文已变化，不能自动复用',
    'SOURCE_CHANGED': '同一位置的原文已变化，需要重新翻译，不自动复用旧译文',
    'TOKEN_POLICY_MISMATCH': '两侧策略对实际控制标记的解释不同或未通过令牌校验',
    'DISPLAY_VALUE_CONSTRAINT': '译文没有通过显示值约束校验',
    'OLD_UNTRANSLATED': '旧单元没有已完成的译文',
    'OLD_TRANSLATION_STALE': '旧译文已过期或未绑定当前原文',
    'TARGET_LOCKED': '目标单元已手动锁定',
    'TARGET_TRANSLATED': '目标单元已有未过期的译文',
    'PROJECT_IDENTITY_UNVERIFIED': '缺少可验证的项目身份（engine/game_id），不能自动复用',
    'NEW': '没有对应的旧单元',
    'ORPHANED': '没有唯一对应的目标单元',
}


# ---------------------------------------------------------------------------
# canonical occurrence identity
# ---------------------------------------------------------------------------

def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str)


def _valid_scope(value: object) -> str | None:
    """Return ``value`` when it is a valid JS scope identifier, else ``None``.

    Booleans, arrays, objects, empty strings, embedded whitespace/newlines and
    overlength values are rejected here.  They are never coerced with ``str``
    because that would invent an identity the extraction never declared.
    """

    if not isinstance(value, str) or len(value) > _SCOPE_FUNCTION_MAX_LENGTH:
        return None
    if _JS_IDENTIFIER_RE.fullmatch(value) is None:
        return None
    return value


def _declared_scope(container) -> tuple[bool, str | None]:
    """Return ``(declared, scope)`` for the ``scope_function`` field.

    ``declared`` is ``True`` when the container carries a scope value.  A
    declared but malformed value yields ``(True, None)`` so the caller can
    reject the locator instead of guessing.  Only a missing field means no
    scope was declared; an explicit null is malformed.
    """

    if not isinstance(container, Mapping) or 'scope_function' not in container:
        return False, None
    return True, _valid_scope(container['scope_function'])


def _locator_key(unit, occurrence) -> str | None:
    """Return the stable location part of an occurrence, or ``None``.

    ``None`` means the locator carries no stable address (only transient byte
    offsets or hashes) or declares a scope that cannot be trusted, so the unit
    must be reviewed instead of guessed.

    Unscoped JS object paths keep the legacy ``object-path:`` identity exactly.
    A declared scope adds a distinct namespace plus the function identifier,
    because the same ``object_path``/``property_path`` pair appears in every
    function of a file.  The locator's own scope is preferred; ``unit.context``
    is only consulted when the locator does not declare one, and a scope
    declared on both sides must agree.
    """

    locator = occurrence.locator if isinstance(occurrence.locator, Mapping) else {}
    pointer = locator.get('pointer')
    if isinstance(pointer, str) and pointer != '':
        if locator.get('note_tag'):
            from ModuleFolders.Domain.GameProject.NoteTagText import validate_locator
            try:validate_locator(occurrence.relative_path,locator)
            except (ValueError,TypeError):return None
            return 'note-tag:'+_canonical_json([pointer,locator['note_tag']])
        return 'pointer:' + pointer
    property_path = locator.get('property_path')
    if property_path is not None:
        context = unit.context if isinstance(unit.context, Mapping) else {}
        object_path = locator.get('object_path', context.get('object_path', ''))
        if not isinstance(object_path, str):
            object_path = _canonical_json(object_path)
        locator_scope_declared, locator_scope = _declared_scope(locator)
        context_scope_declared, context_scope = _declared_scope(context)
        if locator_scope_declared and locator_scope is None:
            return None
        if context_scope_declared and context_scope is None:
            return None
        if locator_scope_declared and context_scope_declared and locator_scope != context_scope:
            return None
        scope = locator_scope if locator_scope_declared else context_scope
        location = object_path + ':' + _canonical_json(property_path)
        if scope is None:
            return 'object-path:' + location
        return _SCOPED_LOCATOR_NAMESPACE + ':' + scope + ':' + location
    return None


def _occurrence_binding(unit, occurrence):
    """Return the JS scope/object binding of one occurrence, or ``None``.

    Only a JS style locator (one that declares ``property_path``) carries a
    binding beyond its file.  The pointer/byte location is deliberately not part
    of it: that is the part a version delta is allowed to move.
    """

    locator = occurrence.locator if isinstance(occurrence.locator, Mapping) else {}
    if 'property_path' not in locator:
        return None
    context = unit.context if isinstance(unit.context, Mapping) else {}
    object_path = locator.get('object_path', context.get('object_path', ''))
    declared, scope = _declared_scope(locator)
    if not declared:
        _, scope = _declared_scope(context)
    path = locator.get('property_path')
    # Array insertions move indexes without changing the named display field.
    # Keep property names typed so a literal "*" key cannot impersonate an index.
    semantic_path = [['index'] if type(part) is int else ['key', part] for part in path] if isinstance(path, list) else path
    return [scope, object_path, semantic_path]


def _occurrence_facts(unit):
    """Return ``(identities, locations, anchor_entries)`` or ``None``.

    ``identities`` are the public canonical occurrence identities,
    ``locations`` are the complete descriptors (path, backend, role, locator)
    used by the exact location phase and ``anchor_entries`` are the sorted
    descriptors of the scene anchor (path, backend, role, JS binding), which
    deliberately exclude the pointer so a moved location can still be reused.

    ``None`` means the unit is unidentifiable: it has no occurrence, one of its
    occurrences has no stable location (mixed valid and invalid locators are
    never reduced to a partial set) or two occurrences share one canonical
    location.
    """

    identities: list = []
    locations: list = []
    entries: list = []
    for occurrence in getattr(unit, 'occurrences', ()) or ():
        key = _locator_key(unit, occurrence)
        if key is None:
            return None
        relative_path = str(getattr(occurrence, 'relative_path', '')).replace('\\', '/')
        backend = str(getattr(occurrence, 'adapter_id', '') or '').strip().casefold()
        role = str(getattr(occurrence, 'role', '') or '')
        identities.append(f'{relative_path}|{backend}|{key}')
        locations.append(_canonical_json([relative_path, backend, role, key]))
        entries.append(_canonical_json([relative_path, backend, role, _occurrence_binding(unit, occurrence)]))
    if not identities or len(set(identities)) != len(identities):
        return None
    return frozenset(identities), tuple(sorted(locations)), tuple(sorted(entries))


def canonical_occurrence_identities(unit) -> frozenset:
    """Return the version independent occurrence identities of ``unit``.

    Each identity is ``relative_path|backend|location``.  Transient locator
    fields (byte offsets, source hashes, expected values) are deliberately not
    part of the identity because extraction changes them while the logical
    location stays the same.  An unidentifiable occurrence set (empty, mixed
    valid/invalid or a repeated canonical location) yields an empty set, never a
    partial one.
    """

    facts = _occurrence_facts(unit)
    return facts[0] if facts is not None else frozenset()


# ---------------------------------------------------------------------------
# semantic anchor and unit views
# ---------------------------------------------------------------------------

def _anchor_component(context: Mapping, key: str):
    """Return one anchor field value, normalizing a blank string to missing."""

    if key not in context:
        return None
    value = context[key]
    if isinstance(value, str):
        text = value.strip()
        return text if text else None
    return value


def _semantic_key(unit, anchor_entries) -> str:
    """Return the stable scene/file/context proof of one unit.

    It contains the scene id (possibly empty), kind, speaker, the sorted
    occurrence multiset with the JS scope/object binding, and the event
    ``code``/``variable_id``/``table``/``field`` when the extraction declared
    them.  Byte offsets, ``command_index``, pointer indexes, revisions and
    whole-file hashes are never included.
    """

    context = unit.context if isinstance(unit.context, Mapping) else {}
    return _canonical_json([
        'semantic',
        ['scene', str(getattr(unit, 'scene_id', '') or '').strip()],
        ['kind', str(getattr(unit, 'kind', '') or '')],
        ['speaker', _anchor_component(context, 'speaker')],
        ['context', [[key, _anchor_component(context, key)]
                     for key in _ANCHOR_CONTEXT_KEYS if key in context]],
        ['occurrences', list(anchor_entries)],
    ])


def _context_key(unit) -> str:
    """Return the remaining semantic context, ignoring transient positions."""

    context = unit.context if isinstance(unit.context, Mapping) else {}
    return _canonical_json([
        [str(key), context[key]]
        for key in sorted(context, key=str)
        if key not in _TRANSIENT_CONTEXT_KEYS
    ])


class _UnitView:
    """Read-only locator facts derived once from one stored unit."""

    __slots__ = ('unit', 'unit_id', 'valid', 'identities', 'locations', 'semantic', 'anchor')

    def __init__(self, unit) -> None:
        self.unit = unit
        self.unit_id = str(getattr(unit, 'unit_id', ''))
        facts = _occurrence_facts(unit)
        self.valid = facts is not None
        if facts is None:
            self.identities = frozenset()
            self.locations = ()
            self.semantic = None
            self.anchor = None
            return
        self.identities, self.locations, anchor_entries = facts
        self.semantic = _semantic_key(unit, anchor_entries)
        scene = str(getattr(unit, 'scene_id', '') or '').strip()
        # The scene anchor is only usable when the extraction declared a scene
        # id; an empty scene can never prove a moved location.
        self.anchor = self.semantic if scene else None


# ---------------------------------------------------------------------------
# identity
# ---------------------------------------------------------------------------

def _text_identity(value: object) -> str:
    """Return a nonempty stripped string identity value, else ``''``."""

    if not isinstance(value, str):
        return ''
    return value.strip()


from .Lineage import game_identity as _game_identity, has_confirmation


def _identity_report(old_metadata: Mapping, new_metadata: Mapping) -> dict:
    """Read both project identities once and refuse an impossible migration.

    ``MIGRATION_SAME_PROJECT`` rejects two stores that are actually one project
    and ``MIGRATION_PROJECT_MISMATCH`` rejects explicitly different engines,
    game ids or target languages.  A missing identity is not an error: it yields
    ``verified=False`` so the caller can return a readable, match free plan.
    """

    old_project_id = _text_identity(old_metadata.get('project_id'))
    new_project_id = _text_identity(new_metadata.get('project_id'))
    if old_project_id and new_project_id and old_project_id == new_project_id:
        raise ValueError(
            f'MIGRATION_SAME_PROJECT: both stores belong to project {old_project_id!r}'
        )
    old_engine = _text_identity(old_metadata.get('engine'))
    new_engine = _text_identity(new_metadata.get('engine'))
    if old_engine and new_engine and old_engine != new_engine:
        raise ValueError(
            f'MIGRATION_PROJECT_MISMATCH: engines differ: {old_engine!r} != {new_engine!r}'
        )
    old_game, old_game_reported = _game_identity(old_metadata.get('game_id'))
    new_game, new_game_reported = _game_identity(new_metadata.get('game_id'))
    if old_game and new_game and old_game != new_game:
        raise ValueError(
            f'MIGRATION_PROJECT_MISMATCH: game ids differ: {old_game!r} != {new_game!r}'
        )
    old_language = _text_identity(old_metadata.get('target_language')) or _DEFAULT_TARGET_LANGUAGE
    new_language = _text_identity(new_metadata.get('target_language')) or _DEFAULT_TARGET_LANGUAGE
    if old_language != new_language:
        raise ValueError(
            f'MIGRATION_PROJECT_MISMATCH: target languages differ: '
            f'{old_language!r} != {new_language!r}'
        )
    if new_language != _DEFAULT_TARGET_LANGUAGE:
        raise ValueError('MIGRATION_TARGET_LANGUAGE_UNSUPPORTED: this version supports zh-CN')
    if new_game:
        reported_game = new_game_reported
    elif old_game:
        reported_game = old_game_reported
    else:
        reported_game = ''
    verified = bool(old_project_id and new_project_id and old_engine and new_engine
        and old_engine == new_engine and old_game and new_game and old_game == new_game)
    explicit = not verified and has_confirmation(old_metadata,new_metadata)
    return {
        'verified': verified or explicit,
        **({'verification_method':'explicit_lineage'} if explicit else {}),
        'engine': new_engine or old_engine,
        'game_id': reported_game,
        'old_project_id': old_project_id,
        'new_project_id': new_project_id,
    }


# ---------------------------------------------------------------------------
# translation and policy guards
# ---------------------------------------------------------------------------

def _translation_row(store, unit_id: str) -> Mapping:
    value = store.translation(unit_id)
    return value if isinstance(value, Mapping) else {}


def _target_revision(store, unit_id: str) -> int:
    revision = _translation_row(store, unit_id).get('revision', 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        return 0
    return revision


def _policy_from_metadata(metadata: Mapping) -> TokenPolicy:
    return TokenPolicy(
        metadata.get('token_commands') or (),
        metadata.get('token_policy_id') or 'rpgmaker-v1',
        literal_tokens=metadata.get('token_literals') or (),
    )


def _token_and_display_conflict(old_unit, new_unit, text: str,
                                old_metadata: Mapping, new_metadata: Mapping) -> str | None:
    """Compare the actual token interpretation and display constraints.

    Declaring an unrelated audited command (or literal) may change a metadata
    list without changing what either policy sees in these two strings, so the
    ordered ``(raw, command)`` signatures of the source and of the proposed
    translation must agree under both policies.  A scanner issue, a changed
    interpretation or any ``validate``/``validate_display_value`` failure is a
    conflict, never a match.
    """

    try:
        old_policy = _policy_from_metadata(old_metadata)
        new_policy = _policy_from_metadata(new_metadata)
    except (TypeError, ValueError):
        return 'TOKEN_POLICY_MISMATCH'
    source = new_unit.source_text
    for value in (source, text):
        old_tokens, old_issues = old_policy.scan(value, new_unit.unit_id)
        new_tokens, new_issues = new_policy.scan(value, new_unit.unit_id)
        if old_issues or new_issues:
            return 'TOKEN_POLICY_MISMATCH'
        old_signature = [(token.raw, token.command) for token in old_tokens]
        new_signature = [(token.raw, token.command) for token in new_tokens]
        if old_signature != new_signature:
            return 'TOKEN_POLICY_MISMATCH'
    for policy in (old_policy, new_policy):
        if policy.validate(source, text, new_unit.unit_id):
            return 'TOKEN_POLICY_MISMATCH'
    for unit, context, source_text in (
            (old_unit, old_unit.context, old_unit.source_text),
            (new_unit, new_unit.context, source)):
        try:
            issues = validate_display_value(source_text, text, context, unit.unit_id)
        except (TypeError, ValueError):
            return 'DISPLAY_VALUE_CONSTRAINT'
        if issues:
            return 'DISPLAY_VALUE_CONSTRAINT'
    return None


def _reuse_conflict(old_view: _UnitView, new_view: _UnitView,
                    old_metadata: Mapping, new_metadata: Mapping,
                    old_store, new_store) -> str | None:
    """Return the conflict reason of a reserved pair, or ``None`` when safe."""

    old_unit = old_view.unit
    new_unit = new_view.unit
    translation = _translation_row(old_store, old_unit.unit_id)
    text = translation.get('text')
    if not isinstance(text, str) or text.strip() == '':
        return 'OLD_UNTRANSLATED'
    if translation.get('stale') or translation.get('status') == 'stale':
        return 'OLD_TRANSLATION_STALE'
    if translation.get('source_hash') != old_unit.source_hash:
        return 'OLD_TRANSLATION_STALE'
    if old_unit.token_policy_id != new_unit.token_policy_id:
        return 'TOKEN_POLICY_MISMATCH'
    reason = _token_and_display_conflict(old_unit, new_unit, text, old_metadata, new_metadata)
    if reason is not None:
        return reason
    target = _translation_row(new_store, new_unit.unit_id)
    if target.get('manual_locked'):
        return 'TARGET_LOCKED'
    if target.get('text') and not target.get('stale'):
        return 'TARGET_TRANSLATED'
    return None


# ---------------------------------------------------------------------------
# entry helpers
# ---------------------------------------------------------------------------

def _review(reason: str, *, old_unit_id: str = '', new_unit_id: str = '',
            detail: str = '', candidates: Iterable = ()) -> dict:
    return {
        'reason': str(reason),
        'old_unit_id': str(old_unit_id),
        'new_unit_id': str(new_unit_id),
        'detail': str(detail),
        'candidates': [str(candidate) for candidate in candidates],
    }


def _row(old_unit_id: str, new_unit_id: str, reason: str) -> dict:
    return {
        'old_unit_id': str(old_unit_id),
        'new_unit_id': str(new_unit_id),
        'reason': str(reason),
    }


def _metadata_mapping(store) -> Mapping:
    metadata = store.metadata()
    return metadata if isinstance(metadata, Mapping) else {}


def _supplied_matches(plan) -> list:
    """Validate the caller supplied matches before any store is written.

    Duplicate old or new pair targets and malformed (missing, bool, negative or
    non integer) ``expected_revision`` values are rejected here so a forged plan
    can never reach the committer.
    """

    if not isinstance(plan, Mapping):
        raise ValueError('MIGRATION_PLAN_INVALID: plan must be a mapping')
    supplied = plan.get('matches', [])
    if isinstance(supplied, (str, bytes, bytearray)) or not isinstance(supplied, Iterable):
        raise ValueError('MIGRATION_PLAN_INVALID: plan matches must be an iterable')
    matches = []
    old_ids: set = set()
    new_ids: set = set()
    for item in supplied:
        if not isinstance(item, Mapping):
            raise ValueError('MIGRATION_PLAN_INVALID: every match must be a mapping')
        for key in ('old_unit_id', 'new_unit_id'):
            value = item.get(key)
            if not isinstance(value, str) or value == '':
                raise ValueError(f'MIGRATION_PLAN_INVALID: match requires a non empty {key}')
        for key in ('text', 'source_hash'):
            if not isinstance(item.get(key), str):
                raise ValueError(f'MIGRATION_PLAN_INVALID: match requires a string {key}')
        revision = item.get('expected_revision')
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
            raise ValueError(
                'MIGRATION_PLAN_INVALID: match requires a non negative integer expected_revision'
            )
        if item['old_unit_id'] in old_ids:
            raise ValueError(
                f'MIGRATION_PLAN_INVALID: duplicate old_unit_id {item["old_unit_id"]}'
            )
        if item['new_unit_id'] in new_ids:
            raise ValueError(
                f'MIGRATION_PLAN_INVALID: duplicate new_unit_id {item["new_unit_id"]}'
            )
        old_ids.add(item['old_unit_id'])
        new_ids.add(item['new_unit_id'])
        matches.append(item)
    return matches


def _unverified_plan(old_views: list, new_views: list, identity: dict) -> dict:
    """Return a match free plan when the project lineage cannot be verified."""

    conflicts = [_row('', view.unit_id, 'PROJECT_IDENTITY_UNVERIFIED') for view in new_views]
    orphaned = [_row(view.unit_id, '', 'ORPHANED') for view in old_views]
    review = [
        _review('PROJECT_IDENTITY_UNVERIFIED', new_unit_id=view.unit_id,
                detail=_REASON_DETAIL['PROJECT_IDENTITY_UNVERIFIED'])
        for view in new_views
    ]
    reconciliation = {
        'reused': [],
        'new': [],
        'modified': [],
        'orphaned': orphaned,
        'conflict': conflicts,
    }
    return {
        'matches': [],
        'review': review,
        'identity': identity,
        'reconciliation': reconciliation,
        'stats': {
            'old_units': len(old_views),
            'new_units': len(new_views),
            'match_count': 0,
            'review_count': len(review),
            'old_unmatched': len(orphaned),
            'new_unmatched': 0,
            'review_reasons': ({'PROJECT_IDENTITY_UNVERIFIED': len(conflicts)} if conflicts else {}),
            'reconciliation_counts': {
                'reused': 0,
                'new': 0,
                'modified': 0,
                'orphaned': len(orphaned),
                'conflict': len(conflicts),
            },
        },
    }


def _cooperative(rows, check):
    for row in rows:
        if check:check()
        yield row


def _overlapping_units(views, check=None) -> set:
    owners = {}
    overlap = set()
    for view in _cooperative(views,check):
        for identity in view.identities:
            previous = owners.setdefault(identity, view.unit_id)
            if previous != view.unit_id:
                overlap.update((previous, view.unit_id))
    return overlap


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def plan_migration(old_store, new_store, *, check=None) -> dict:
    """Plan a migration from ``old_store`` into ``new_store``.

    Returns ``{'matches', 'review', 'identity', 'reconciliation', 'stats'}``.
    Every match is exactly ``old_unit_id``, ``new_unit_id``, ``text`` (the old
    accepted translation), ``source_hash``, ``expected_revision`` (the current
    revision of the target unit) and ``match_method``.  The old store is only
    read; projects stay separate.
    """

    old_metadata = _metadata_mapping(old_store)
    new_metadata = _metadata_mapping(new_store)
    identity = _identity_report(old_metadata, new_metadata)
    old_views = [_UnitView(unit) for unit in _cooperative(old_store.units(),check)]
    new_views = [_UnitView(unit) for unit in _cooperative(new_store.units(),check)]
    if not identity['verified']:
        return _unverified_plan(old_views, new_views, identity)
    old_overlaps = _overlapping_units(old_views,check)
    new_overlaps = _overlapping_units(new_views,check)
    for view in _cooperative(old_views,check):
        if view.unit_id in old_overlaps:view.valid = False
    for view in _cooperative(new_views,check):
        if view.unit_id in new_overlaps:view.valid = False

    old_by_location: dict = {}
    old_by_anchor: dict = {}
    old_by_text: dict = {}
    for view in _cooperative(old_views,check):
        old_by_text.setdefault(view.unit.source_hash, []).append(view)
        if not view.valid:
            continue
        old_by_location.setdefault(view.locations, []).append(view)
        if view.anchor is not None:
            old_by_anchor.setdefault((view.unit.source_hash, view.anchor), []).append(view)
    new_by_location: dict = {}
    new_by_anchor: dict = {}
    for view in _cooperative(new_views,check):
        if not view.valid:
            continue
        new_by_location.setdefault(view.locations, []).append(view)
        if view.anchor is not None:
            new_by_anchor.setdefault((view.unit.source_hash, view.anchor), []).append(view)

    consumed: set = set()
    matched: dict = {}
    conflicts: dict = {}
    modified: dict = {}

    # Phase 1: one old and one new unit with the complete occurrence set, the
    # same source hash, the same scene anchor fields and the same context.
    claims: dict = {}
    for target in _cooperative(new_views,check):
        if not target.valid:
            continue
        owners = old_by_location.get(target.locations, ())
        if len(owners) != 1:
            if owners:
                conflicts[target.unit_id] = (
                    'MULTIPLE_OLD_CANDIDATES', None, [view.unit_id for view in owners])
            continue
        owner = owners[0]
        if owner.unit.source_hash != target.unit.source_hash:
            continue
        if owner.semantic != target.semantic:
            continue
        if _context_key(owner.unit) != _context_key(target.unit):
            continue
        claims[target.unit_id] = owner
    claim_counts: dict = {}
    for owner in claims.values():
        claim_counts[owner.unit_id] = claim_counts.get(owner.unit_id, 0) + 1
    for target in _cooperative(new_views,check):
        owner = claims.get(target.unit_id)
        if owner is None:
            continue
        if claim_counts[owner.unit_id] > 1 or len(new_by_location.get(target.locations, ())) > 1:
            conflicts[target.unit_id] = ('AMBIGUOUS_OWNERSHIP', None, [owner.unit_id])
            continue
        matched[target.unit_id] = (owner, 'exact_location')
        consumed.add(owner.unit_id)

    # Phase 2: reserve the pairs whose source hash and scene anchor are unique
    # in both complete datasets, before any unmatched unit is classified.
    for target in _cooperative(new_views,check):
        if not target.valid or target.unit_id in matched or target.anchor is None:
            continue
        key = (target.unit.source_hash, target.anchor)
        owners = old_by_anchor.get(key, ())
        if not owners:
            continue
        claimants = new_by_anchor.get(key, ())
        if len(owners) != 1 or len(claimants) != 1:
            conflicts.setdefault(target.unit_id, (
                'AMBIGUOUS_SCENE_ANCHOR', None, [view.unit_id for view in owners]))
            continue
        owner = owners[0]
        if owner.unit_id in consumed:
            # Another target already reused this old unit; one old unit never
            # pairs with two targets.
            conflicts.setdefault(target.unit_id, ('AMBIGUOUS_OWNERSHIP', None, [owner.unit_id]))
            continue
        conflicts.pop(target.unit_id, None)
        matched[target.unit_id] = (owner, 'unique_scene_anchor')
        consumed.add(owner.unit_id)

    # Guards: a reserved pair is only a proposal when every reuse guard holds.
    for target in _cooperative(new_views,check):
        entry = matched.get(target.unit_id)
        if entry is None:
            continue
        owner, _method = entry
        reason = _reuse_conflict(owner, target, old_metadata, new_metadata, old_store, new_store)
        if reason is None:
            continue
        del matched[target.unit_id]
        conflicts.setdefault(target.unit_id, (reason, owner, []))

    # Classification of everything that is neither reserved nor conflicting.
    for target in _cooperative(new_views,check):
        if target.unit_id in matched or target.unit_id in conflicts:
            continue
        if target.unit_id in new_overlaps:
            conflicts[target.unit_id] = ('AMBIGUOUS_OWNERSHIP', None, [])
            continue
        if not target.valid:
            conflicts[target.unit_id] = ('UNIDENTIFIABLE_LOCATOR', None, [])
            continue
        owners = [view for view in old_by_location.get(target.locations, ())
                  if view.unit_id not in consumed]
        if len(owners) > 1:
            conflicts[target.unit_id] = (
                'MULTIPLE_OLD_CANDIDATES', None, [view.unit_id for view in owners])
            continue
        if owners:
            owner = owners[0]
            if owner.semantic == target.semantic and owner.unit.source_hash != target.unit.source_hash:
                # Same slot, same scene/file/context proof, changed source text:
                # a modification of the old unit, never a reuse.
                modified[target.unit_id] = owner
                consumed.add(owner.unit_id)
            else:
                conflicts[target.unit_id] = ('LOCATOR_SET_CHANGED', None, [owner.unit_id])
            continue
        same_text = [view.unit_id for view in old_by_text.get(target.unit.source_hash, ())]
        if same_text:
            conflicts[target.unit_id] = (
                'SOURCE_TEXT_AT_DIFFERENT_LOCATOR', None, same_text)

    matches: list = []
    reused_rows: list = []
    new_rows: list = []
    modified_rows: list = []
    conflict_rows: list = []
    review: list = []
    for target in _cooperative(new_views,check):
        unit_id = target.unit_id
        entry = matched.get(unit_id)
        if entry is not None:
            owner, method = entry
            translation = _translation_row(old_store, owner.unit_id)
            matches.append({
                'old_unit_id': owner.unit_id,
                'new_unit_id': unit_id,
                'text': str(translation.get('text') or ''),
                'source_hash': target.unit.source_hash,
                'expected_revision': _target_revision(new_store, unit_id),
                'match_method': method,
            })
            reused_rows.append(_row(owner.unit_id, unit_id, method))
            continue
        owner = modified.get(unit_id)
        if owner is not None:
            modified_rows.append(_row(owner.unit_id, unit_id, 'SOURCE_CHANGED'))
            review.append(_review('SOURCE_CHANGED', old_unit_id=owner.unit_id, new_unit_id=unit_id,
                                  detail=_REASON_DETAIL['SOURCE_CHANGED']))
            continue
        conflict = conflicts.get(unit_id)
        if conflict is not None:
            reason, owner, candidates = conflict
            old_unit_id = owner.unit_id if owner is not None else ''
            conflict_rows.append(_row(old_unit_id, unit_id, reason))
            review.append(_review(reason, old_unit_id=old_unit_id, new_unit_id=unit_id,
                                  detail=_REASON_DETAIL.get(reason, ''), candidates=candidates))
            continue
        new_rows.append(_row('', unit_id, 'NEW'))

    orphaned_rows = [_row(view.unit_id, '', 'ORPHANED')
                     for view in old_views if view.unit_id not in consumed]
    review_reasons: dict = {}
    for item in review:
        review_reasons[item['reason']] = review_reasons.get(item['reason'], 0) + 1
    reconciliation = {
        'reused': reused_rows,
        'new': new_rows,
        'modified': modified_rows,
        'orphaned': orphaned_rows,
        'conflict': conflict_rows,
    }
    stats = {
        'old_units': len(old_views),
        'new_units': len(new_views),
        'match_count': len(matches),
        'review_count': len(review),
        'old_unmatched': len(orphaned_rows),
        'new_unmatched': len(new_rows),
        'review_reasons': dict(sorted(review_reasons.items())),
        'reconciliation_counts': {
            'reused': len(reused_rows),
            'new': len(new_rows),
            'modified': len(modified_rows),
            'orphaned': len(orphaned_rows),
            'conflict': len(conflict_rows),
        },
    }
    return {
        'matches': matches,
        'review': review,
        'identity': identity,
        'reconciliation': reconciliation,
        'stats': stats,
    }


def _checked_pair(old_store, new_store, match):
    old_unit = old_store.unit(match['old_unit_id'])
    new_unit = new_store.unit(match['new_unit_id'])
    if old_unit is None or new_unit is None:
        raise ValueError(f'MIGRATION_PLAN_STALE: unit {match["new_unit_id"]} disappeared')
    if old_unit.source_hash != match['source_hash'] or new_unit.source_hash != match['source_hash']:
        raise ValueError(f'MIGRATION_SOURCE_CHANGED: {new_unit.unit_id}')
    translation = _translation_row(old_store, old_unit.unit_id)
    if (not str(translation.get('text') or '').strip() or translation.get('stale')
            or translation.get('status') == 'stale' or translation.get('source_hash') != match['source_hash']
            or translation.get('text') != match['text']):
        raise ValueError(f'MIGRATION_SOURCE_STALE: {old_unit.unit_id}')
    target = _translation_row(new_store, new_unit.unit_id)
    if target.get('manual_locked'):
        raise ValueError(f'MIGRATION_TARGET_LOCKED: {new_unit.unit_id}')
    if target.get('text') and not target.get('stale'):
        raise ValueError(f'MIGRATION_TARGET_TRANSLATED: {new_unit.unit_id}')
    if target.get('revision', 0) != match['expected_revision']:
        raise ValueError(f'MIGRATION_PLAN_STALE: target revision changed: {new_unit.unit_id}')
    return old_unit, new_unit


def apply_migration(old_store, new_store, plan, *, job_id=None, check=None, on_result=None) -> list:
    """Submit the verified matches of ``plan`` and return ``CommitResult`` list.

    The supplied plan is validated entry by entry (duplicate pair targets and
    malformed revisions are rejected with ``MIGRATION_PLAN_INVALID``) and then
    checked against a freshly generated plan, so arbitrary, forged or stale plan
    text can never be injected into the store.  Supplied ``reconciliation``,
    ``match_method`` or anchor data are never trusted.  Source hashes, old text
    freshness, revisions and manual locks are rechecked for every row before the
    first submit.  A single mismatch raises ``ValueError`` and nothing is
    submitted.
    """

    if job_id is None:
        import uuid
        job_id=_MIGRATION_JOB_ID+':'+uuid.uuid4().hex
    if not isinstance(job_id,str) or not job_id:
        raise ValueError('MIGRATION_JOB_ID_INVALID')
    supplied = _supplied_matches(plan)
    fresh = plan_migration(old_store, new_store,check=check)
    reference = {
        (match['old_unit_id'], match['new_unit_id']): match for match in fresh['matches']
    }

    verified = []
    for match in _cooperative(supplied,check):
        key = (match['old_unit_id'], match['new_unit_id'])
        current = reference.get(key)
        if current is None:
            raise ValueError(
                f'MIGRATION_PLAN_STALE: {key[0]} -> {key[1]} is not a current migration match'
            )
        if (match['text'] != current['text'] or match['source_hash'] != current['source_hash']
                or match['expected_revision'] != current['expected_revision']):
            raise ValueError(
                f'MIGRATION_PLAN_INVALID: plan text for {key[1]} does not match the current plan'
            )
        verified.append(current)

    # Full pre-flight verification before the first write.
    rows = []
    for match in _cooperative(verified,check):
        old_unit, new_unit = _checked_pair(old_store, new_store, match)
        rows.append((match, old_unit, new_unit))

    committer = TranslationCommitter(new_store)
    old_project_id = fresh['identity']['old_project_id']
    results = []
    for match, old_unit, new_unit in rows:
        if check:check()
        old_unit, new_unit = _checked_pair(old_store, new_store, match)
        proposal = TranslationProposal(
            new_unit.unit_id,
            match['text'],
            new_unit.source_hash,
            expected_revision=match['expected_revision'],
            job_id=job_id,
            request_item_id=f'{old_project_id}:{old_unit.unit_id}:{new_unit.unit_id}',
            origin=MIGRATION_ORIGIN,
            metadata={
                'old_unit_id': old_unit.unit_id,
                'old_project_id': old_project_id,
                'new_unit_id': new_unit.unit_id,
            },
        )
        result=committer.submit(proposal)
        results.append(result)
        if on_result:on_result(match,result)
    return results
