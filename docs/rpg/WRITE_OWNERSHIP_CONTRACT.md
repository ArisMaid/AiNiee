# Write ownership before extraction publication

Worker scope: only ModuleFolders/Domain/GameProject/WriteOwnership.py. Codex owns
integration, registry, tests and acceptance. Use read/write/edit only. Do NOT use
grep (even with a file), glob, shell, execution, network, deletion, todo or agents.
All needed files are named here; do not explore directories or private work.

Expose ownership_issues(units)->tuple[Issue,...], using Models.Issue. Inputs are
TranslationUnit objects with unit_id and occurrences; Occurrence has
occurrence_id, relative_path, locator(dict), adapter_id, role. Issue constructor is
Issue(code,severity,message,unit_id='',path='',details={}). Its fields must be
JSON serializable. Do not read files, resolve filesystem paths, write anything,
execute scripts or mutate input units/locators. Source hashes/address resolution
remain the existing patchers' job; this function proves ownership, not values.

Paths: normalize backslashes and casefold for the Windows target. Reject
absolute/drive/UNC, empty/dot/dotdot components, colon/control characters and
trailing dot/space components. Issue code WRITE_LOCATOR_INVALID for malformed or
unsupported locators, severity error. Every unit needs at least one occurrence.

Classify by physical address, independent of producer ID except image-region:

- JSON: .json file and a nonempty RFC6901 pointer beginning /. Decode ~1/~0,
  reject bad ~ escapes and dot/dotdot decoded components; empty member names
  such as / are valid. Root replacement is unsupported. Duplicate or ancestor/
  descendant token paths conflict, even across adapters or within one unit.
  Prefix means token prefix, not string prefix: /name and /names do not overlap.
  Numeric string object keys keep their spelling. Valid extracted array indexes
  already use canonical spelling; actual resolution stays with JsonPatcher.
- JS: .js file, integer (not bool) start/end, 0<=start<end, no pointer. Byte
  half-open ranges overlap when left.start < right.end and right.start < left.end;
  exact duplicate, nested and partial overlaps reject; touching ends are allowed.
  Object_path/property_path/adapter IDs do not make one physical span separate.
- image-region adapter: supported png/png_/rpgmvp path; region_id is 32 lowercase
  hex, pointer equals region/<id>, source_sha256 is 64 hex, box is [x,y,w,h] exact
  nonbool ints with nonnegative x/y and positive w/h. Per file <=500 regions.
  Duplicate region IDs or intersecting pixel boxes conflict; edge touching is
  allowed. Different disjoint regions are permitted as one image writer plan.
  Do not attempt image decode or file-bound checks here.
- Mixed/ambiguous locator kinds and unknown shapes reject; do not guess.

Existing locator metadata must remain compatible. JSON may also carry
value_codec and raw_expression (event-script literal codec). JS may also carry
expected, source_sha256, scope_function and property_fields, in addition to
object_path/property_path. These recognized fields are NOT physical ownership
dimensions; ignore their values for overlap detection. In particular JS
source_sha256 is source verification metadata, not an image-kind marker.
Do not validate or expose source/expected/raw_expression values in diagnostics.

Conflict code WRITE_OWNERSHIP_CONFLICT, severity error. Attach current unit_id
and original current path; details contains kind, occurrence_id, other_unit_id,
other_occurrence_id and a JSON-safe address descriptor. Include no source or
translation text in diagnostics. Emit at most one conflict per incoming claim
(a representative conflicting owner is enough), not every pair in a dense
overlap. Ordering must be deterministic. Invalid claims do not participate in
overlap resolution. Malformed source does not get silently deduplicated.

Use sorting/trie/sweep so JSON/JS are O(total pointer length + n log n), not
pairwise n². Image comparisons are bounded by the same 500-regions/file limit
as ImageService. Preserve all unrelated addresses and distinct files.

Codex tests cover JSON escaping/prefixes, case/path aliases, linked distinct
occurrences, JS UTF-8 byte intervals and aliases, images, malformed shapes,
deterministic bounded diagnostics and large nonoverlapping datasets. Service
tests will prove extraction rollback and refusal of legacy unsafe snapshots.
Worker completion is not acceptance.
