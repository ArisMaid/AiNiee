# Event display literal codec

Codex 0.25 extension (2026-10-20): the original CODEC_ID/API below keeps its
semantics. LINE_CODEC_ID='event-js-line-string-v1' adds decode_line_literal and
encode_line_literal(text, *, original) for one JSON-quoted string in an exact
profile-approved 355/655 line. Prefix/suffix code is preserved; multiple strings,
single quotes and multiline expressions are unsupported. It reuses the JSON
codec, does not execute JavaScript and declares event_js_line_v1 through the
existing capability gate. See PROFILE6_EVIDENCE.md for source-flow evidence.
The original worker handoff contract below is retained as historical scope.

0.32 also adds event-js-span-v1 in EventScriptSpan.py for four reviewed static
template parts at three exact CommonEvents 355/655 leaves. It reuses the existing
Acorn extract/patch/audit worker, rather than changing the literal codecs below.
Profiles declare event_js_spans_v1 plus source-line, logical-text hashes and exact
UTF-8 node ranges. Multiple parts of one line compile into one physical JSON
write. Ownership rejects duplicate, overlapping and mixed whole-leaf claims.
The DB keeps distinct stable fragment IDs; old runtimes reject the new capability.
Backend whole-leaf coverage records cannot select between shared fragments and
are reported as ambiguous reference evidence. No new arbitrary script execution
or inference of display permissions is introduced.

Worker scope: only ModuleFolders/Domain/GameProject/EventLiteralCodec.py. Pure Python standard library. Codex owns profile, event selection, occurrence mapping, SQLite capability gate, writer/backend integration and acceptance.

Only read/write/edit/glob and single-regular-file grep may be used. No directory grep, todo_write, execution, shell, network, deletion or other tools. Do not edit this contract or tests. Do not inspect game assets or credential files.

Expose CODEC_ID='event-js-json-string-v1', MAX_LITERAL_BYTES=65536, decode_literal(expression)->str and encode_literal(text, *, original=None)->str. Keep the implementation small: this is a JSON-string subset codec, not a JavaScript parser.

- decode_literal accepts only str whose complete UTF-8 byte length is <= MAX_LITERAL_BYTES and whose complete JSON parse result is a string. It may contain ordinary JSON surrounding whitespace. Numbers, bool, null, arrays, objects, single quotes, backticks, concatenation, parenthesized expressions, comments, trailing statements, invalid JSON escapes and lone UTF-16 surrogates are rejected with ValueError. The source never executes, and invalid input is never repaired or silently replaced.
- encode_literal accepts only str with well-formed Unicode, using json.dumps(...,ensure_ascii=False). U+2028/U+2029 must be emitted as backslash-u escapes so the expression remains usable with older JS string parsers. Literal newline, NUL, quotes and backslashes must be JSON-escaped. Reject output exceeding MAX_LITERAL_BYTES (including its quotes/escapes), even if input text was smaller. ValueError for malformed inputs, never truncate.
- If original is supplied, validate it with decode_literal first. When it decodes to exactly text, return original byte-for-byte as a Python string: preserve surrounding JSON whitespace and original escape spelling. Otherwise generate a new quoted literal. Invalid original always rejects; it cannot be ignored even if text is valid.
- encode/decode roundtrip preserves text. No backtick/eval/exec imports, filesystem access or subprocesses. Empty string is a valid literal; the extractor separately decides whether to make a display unit.
- These APIs do not choose display fields or authorize write addresses. The native writer must validate the raw source hash and profile-approved occurrence before calling the codec.

Codex tests include strict grammar counterexamples, no-op preservation, Unicode and output bounds, and a Node VM oracle executing only generated synthetic string expressions with an isolated context (never game source).
