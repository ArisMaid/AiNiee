# Engineering contract: project format 2

Codex owns this contract and independent acceptance. The worker may modify only ProjectStore.py.

## Compatibility and capability gate

- SCHEMA_VERSION becomes 2. Fresh create() accepts only exact integer 2 (default); reject bool. Existing schemas 1 and 2 remain readable, including readonly frozen snapshots, without an automatic upgrade on open.
- Metadata required_features is a unique list of known nonempty feature identifiers. Supported identifiers for this increment: literal_tokens_v1 and display_value_constraints_v1. Missing means empty. Schema 1 cannot declare nonempty features. Unknown, malformed or inconsistent features fail with StoreViolation before use. A 0.1.1 app already rejects version 2.

Follow-up: font_aliases_v1 is now also supported. A nonempty profile font_aliases or font_settings.aliases declares it through the same monotonic capability gate. Profile format 2 is required, and build plans bind generated runtime bytes by SHA-256. An older format-2 app that lacks this capability must reject the project.

0.3.0 follow-up: event_js_string_v1, js_scoped_object_v1 and display_line_count_v1 add semantic capabilities while retaining physical DB format 2. Every increase of a live format-2 required_features set also keeps a transaction-consistent pre-change backup under migrations/capabilities-v2/UUID/project.sqlite3. Declaration and unit/config writes remain atomic. This prevents a capability upgrade from locking out an older application without a retained pre-upgrade database. Opening or re-extracting without a feature increase creates no new backup. Backups are database snapshots for restoration in the original project; they do not duplicate the immutable source/image/font files and are not standalone build projects.
- _verify_schema runs at open and again AFTER BEGIN IMMEDIATE, INSIDE the rollback-protected try in every _write transaction. A long-open connection cannot write after an unsupported upgrade by another connection. Any verification exception rolls back; the connection remains usable after the external problem is fixed.
- schema_version and required_features cannot be changed via update_metadata. Features are monotonic, sorted union, never removed by re-extraction.
- Infer required features in replace_units from incoming units and extraction metadata: nonempty token_literals OR rpgmaker-v3 policy requires literal_tokens_v1; a nonempty context.value_constraints requires display_value_constraints_v1. update_metadata with token_literals/policy must also validate and infer the literal feature. Fresh create metadata must validate and infer its features.
- All metadata literal lists use TokenPolicy validation. Do not add a path that permits invalid literal grammar through update_metadata/create.

## Legacy upgrade backup and atomicity

- A legacy schema-1 project upgrades ONLY when an advanced feature is first required. Plain reads, jobs, legacy extraction and ordinary translation preserve schema 1.
- In the SAME transaction as the first advanced unit/config mutation, before any data mutation, create a consistent SQLite pre-upgrade backup at migrations/v1-to-v2/<new UUID>/project.sqlite3, then set schema_version=2 and required_features. No file deletion, overwrite, rename, recursive cleanup, or user project mutation outside the requested transaction.
- The upgrade helper runs with BEGIN IMMEDIATE holding the writer reservation. Do NOT call self._connection.backup() or snapshot() on that source connection during its transaction: it can deadlock. Use a separate read-only URI mode=ro connection to the live database to backup the exact committed pre-upgrade state while writers are excluded. Its SQLite snapshot must include WAL commits. PathGuard.safe_join checks the generated backup path, then exclusively reserve the destination ('xb'). Close all helper connections.
- Backup failure aborts the mutation. Later transaction failure rolls back units, schema, feature metadata and revisions. A backup file may remain; it is deliberately retained for audit. No data loss and no bulk cleanup.
- Upgrade with features must happen before writes to units/translation/config so the backup is genuinely pre-mutation. The existing revision increment remains once per successful extraction; capability metadata should not cause a second content/dataset bump.
- No physical SQL table changes in this increment. Preserve public APIs, readonly guarantees, locking/CAS and file ownership checks.

Tests will independently exercise legacy readonly stability, exact backup data, rollback after writes, long-open rejection and fresh invalid metadata. Worker completion is not acceptance.
