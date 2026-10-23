# Cross-version migration, second slice

Codex owns architecture, tests and acceptance. DeepSeek may edit only
ModuleFolders/Service/GameProject/MigrationService.py. No execution, shell,
network, deletion, todo tools or directory grep. Read this contract, the allowed
source, Models/TokenPolicy/ValueConstraints/TranslationCommitter, and protected
tests as needed. Preserve public canonical_occurrence_identities, plan_migration,
apply_migration and existing stats/reason fields. Never write SQL or old_store.

## Identity before reuse

Read each store metadata once per plan. Nonempty equal project IDs are rejected
with MIGRATION_SAME_PROJECT. Explicit differing nonempty engines, game IDs or
target languages raise MIGRATION_PROJECT_MISMATCH (before any mutation).
game_id accepts positive int or nonempty string excluding "0"; reject bool,
blank/null/nonpositive values as missing. Missing language defaults to zh-CN.
Automatic reuse requires equal nonempty engines and equal known game IDs.
Missing identity produces a readable plan with no matches and one
PROJECT_IDENTITY_UNVERIFIED conflict per target unit. Do not silently match
different games or invent identity from a directory name/title. A legacy MV
project with no game ID can be inspected but needs verified lineage before
automatic reuse; this slice does not invent a UI override.

Return identity={verified,engine,game_id,old_project_id,new_project_id}. Projects
remain separate and immutable sources are not changed.

## Locations and unique scene anchors

Keep the scoped JS/global identity behavior. Every occurrence must have a valid
stable location; a mixed valid+invalid locator set is unidentifiable, never
silently reduced to a partial set. Duplicate canonical locations also reject.

Two phases, with no fuzzy strings:

1. Unique equal full occurrence sets + equal source_hash + equal semantic
   context may use match_method=exact_location. Ambiguous target ownership must
   not produce two matches from one old unit.
2. For remaining units use match_method=unique_scene_anchor ONLY if the source
   hash and scene anchor are unique in BOTH complete old and new datasets.
   Anchor includes a nonempty scene_id, kind, speaker, sorted occurrence
   (relative_path,adapter_id,role) multiset, JS scope/object binding and event
   code/variable_id/table/field when present. Do not include transient byte
   offsets, command_index, pointer indexes, revisions or hashes of whole files.
   Nonempty source text alone, a generic same-word match, a different scene,
   different speaker/kind/scope/role, changed linked occurrence count, ambiguous
   same-scene text or file renaming is insufficient. Only the pointer/byte
   location may move under a stable scene/file/context proof.

Reserve safe pairs globally before classifying unmatched units. Inserting a new
event at index 5 shifts old A from 5->6 and old B from 6->7: reuse A/B by unique
anchors even though their new pointers initially coincide with other old text.
New text occupying a consumed old slot is new, not a modification of that slot.
One old unit can pair with at most one target. Same-location changed source is
modified only if its old partner was not consumed elsewhere. A different
source/speaker/scene is never rescued by fuzzy similarity.

## Translation and policy guards

Require a nonempty nonstale old translation bound to old source_hash. Preserve
target manual locks and existing nonstale target translations. Reuse requires
equal unit token_policy_id. Metadata command/literal lists may gain unrelated
declarations: compare actual ordered (raw,command) token signatures under both
policies for source AND proposed translation, require no scanner/validation
issues, then run both policies' validate and old/new validate_display_value.
Changed token interpretation or any guard failure becomes review, not a match.
This allows adding an unused audited R command without invalidating every
unrelated source, but never promotes an old unknown R result or a changed
literal marker interpretation. Do not replace central commit validation.

## Reconciliation and apply

Return reconciliation with five lists of rows: reused, new, modified, orphaned,
conflict. Each row has old_unit_id/new_unit_id (empty when absent) and reason.
Every target occurs exactly once in reused/new/modified/conflict; every old unit
without a unique counterpart is orphaned once. Reused are proposed safe reuse,
not yet accepted writes. Modified pairs reference their old unit; ambiguous
candidate IDs are informational and do not consume an old counterpart. Target
locks/untranslated old/token differences are conflicts with reason codes.
stats.reconciliation_counts contains the five exact counts. Retain existing
matches/review/stats keys; review includes conflicts/changed-source diagnostics.

apply_migration still replans and verifies every requested pair, source hash,
translation text and expected_revision before submitting through committer.
Reject duplicate old/new pair targets in supplied matches and malformed/bool
revision values with MIGRATION_PLAN_INVALID before any write. Explicit project
identity mismatch aborts before any write. Never trust supplied reconciliation,
match_method or anchor data to authorize writes. Keep per-row old text freshness,
target lock and central source/revision checks; provenance includes project and
old unit. Idempotency remains through the existing proposal delivery keys.

Tests cover shifted occupied indexes, all five classes, scene/speaker/scope
ambiguity, one-to-one reuse, unrelated vs changed token interpretation, missing
identity, forged/stale/duplicate plans, source-store immutability and real SQLite
application. Worker completed/verified:false is not acceptance.

Post-review decisions: keep named JS property components while allowing numeric
array index shifts; reject cross-unit partial address overlaps on either side;
normalize positive numeric string IDs and reject unsupported non-zh-CN targets.
CLI owns both project locks in deterministic path order. Preflight is followed
by another old-text/target-revision check immediately before each submit; this
does not claim an atomic multi-project batch transaction.
