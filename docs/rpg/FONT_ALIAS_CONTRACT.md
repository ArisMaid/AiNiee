# Font alias runtime contract

Implement ONLY ModuleFolders/Service/GameProject/FontAliasRuntime.py. Codex owns profile/store/build integration and acceptance tests. Do not edit tests or contracts. The worker may use read/write/edit/glob and single-file grep only; never use directory grep, todo_write, shell, execution, web or subagent tools. A denied call makes handoff fail.

Expose build_runtime(aliases, output_file) -> bytes. Pure Python standard library, deterministic UTF-8 JavaScript output. No filesystem access or subprocess code in this module.

Validate aliases as list/tuple, 1..16 unique strings, each matching ASCII [A-Za-z][A-Za-z0-9_-]{0,63}. Validate output_file as an ASCII basename with a .ttf/.otf/.woff/.woff2 suffix, maximum 128 characters, no slash/backslash/colon/.. or control/quote characters. Raise ValueError for bad input. Keep input order in generated configuration.

The generated MZ script must intercept FontManager.load(family, filename, ...rest) for the declared families, substitute only filename with output_file, preserve this/other arguments/return value, and keep all undeclared families unchanged. Never rewrite source game JS, evaluate arbitrary code, access require/network/storage, or modify font bytes. The app copies the selected font separately to output/fonts.

Timing: the script is appended to index.html after main.js. MZ main.js dynamically loads core managers and plugins. Install immediately when FontManager exists; otherwise listen for document load events in CAPTURE phase so the wrapper installs before target script load callbacks can start plugins. A window load fallback attempts install once and records a missing-manager error if impossible. Do not poll with timers. Remove listeners once installed. Use globalThis.AiNieeFontAliasOverride state with schema_version=1, aliases, output_file, installed, error, and loads (per-family call counts, no prototype). This state is diagnostic evidence only.

If FontManager._urls already contains any declared family at initial installation, fail closed with a clear error rather than claiming an override for an already-started load. Running the identical generated script a second time must be idempotent (same state/wrapper, no reset/double wrap). A second configuration with different ordered aliases or output_file must throw instead of changing a live mapping. Do not accept an arbitrary preexisting global object as verified installation.

The generated code is app-owned and only uses declared family names and the validated basename. Keep it small and readable; no generic plugin framework. Codex will test immediate/deferred load, duplicate execution, late startup rejection, and actual current-game rendering.
