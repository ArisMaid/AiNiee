# Ordered operation checkpoint journal

Worker writes ONLY ModuleFolders/Service/GameProject/OperationJournal.py.
Use read/write/edit tools only; no grep, glob, shell, execution, agents, network
or directory exploration. Codex writes integration and runs tests. Read this
file and tests/game_project/test_operation_journal.py; optionally read the exact
PathGuard.py sibling. Never inspect work, private projects or credentials.

Implement a focused SQLite append-only checkpoint journal, standard library
plus PathGuard.safe_join. No deletion or replacement. Caller owns ProjectLock.
API:

- OperationJournal.create(path, descriptor) creates a NEW journal exclusively;
  descriptor exact keys operation(nonempty str), algorithm(nonempty str),
  input_digest(64 lowercase hex), item_count(nonbool int>=0). No other keys.
- OperationJournal.open(path, descriptor) opens an EXISTING regular journal and
  verifies its schema, exact expected descriptor and all retained rows.
- journal.completed -> int number of retained contiguous rows.
- journal.results() -> tuple of independent JSON dict copies in index order.
- journal.append(rows) accepts a nonempty list of dicts, max128 rows, and cannot
  exceed item_count. One atomic SQLite transaction for the ENTIRE batch. No
  caller-supplied index: assign completed..completed+len(rows)-1. Reject duplicate
  unit_id within/all retained rows (each row must have nonempty str unit_id;
  other payload fields are generic JSON). All validation occurs before write.
- close(), context-manager support.

Create parent with safe_join(path.parent,path.name) and mkdir(parents=True,
exist_ok=True) AFTER validating arguments. Exclusively create file via O_EXCL;
existing files and failed artifacts remain. Open must never create missing
file/parent. Re-check PathGuard boundaries/no links and reject hardlinked files
for create/open. Sqlite synchronous FULL, journal_mode DELETE, parameterized
values. Do not hold transactions except for schema creation or append.

Schema: a schema-version marker (1), canonical descriptor JSON and its SHA-256,
ordered item rows index/payload_json/digest. Each row digest binds index AND
canonical payload. Reject missing/gapped/negative/out-of-range indices, duplicate
unit IDs, bad descriptor/hash/schema, malformed JSON, duplicate JSON keys,
NaN/Infinity and non-dict payloads. Do not log/publish payload text. Pure JSON
validation must also reject non-string mapping keys and non-native values rather
than json.dumps coercion. Reasonable limit each serialized row <=4MiB and total
128-row batch <=16MiB. No source filesystem reads except the journal itself.

JournalError(ValueError) with stable codes (message prefix):
JOURNAL_DESCRIPTOR_INVALID, JOURNAL_INPUT_CHANGED, JOURNAL_CORRUPT,
JOURNAL_ROWS_INVALID, JOURNAL_LIMIT_EXCEEDED. FileExistsError on exclusive
create; FileNotFoundError on missing open. A corrupt file never gets rebuilt or
overwritten. Failure closes connection, retains file. A valid append followed
by process os._exit must be readable by a fresh process; an invalid append has
no effect on earlier committed rows. Returned copies cannot change cache/data.
Keep under ~300 lines; avoid an elaborate framework or unrelated convenience API.
