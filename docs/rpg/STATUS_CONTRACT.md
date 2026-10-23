# Implementation status drafting contract

Write only `docs/rpg/IMPLEMENTATION_STATUS.md`, in Chinese. Use only read/write/edit
tools. Never call grep, glob, todo, shell, network or agents. Exact optional reads:
`docs/rpg/DEVELOPMENT_PLAN.md`, `docs/rpg/USER_GUIDE.md`, this contract.
Codex owns review, testing and final delivery. Do not invent evidence.

The document must map all 34 tasks A01-H03 to implemented/partial/pending, with
concrete limitations and next acceptance criteria. Never call the full plan done.
Use these supervisor-verified facts as the evidence snapshot (2026-10-16):

- Baseline 7bbb06be33f5968f0723a5200a150d895d4fa5fb, existing fork ArisMaid/AiNiee,
  branch codex/rpg-localization-core; no push, PR or release. Actual LICENSE is
  AGPL-3.0, not GPL. Python 3.13.15 lock and Node 24.16.0/Acorn 8.19.0.
- Core source paths are ModuleFolders/Domain/GameProject,
  ModuleFolders/Service/GameProject, ModuleFolders/Infrastructure/GameAdapters,
  UserInterface/GameProject, Tools/rpg_pipeline.py, RpgApp.py.
- SQLite is authoritative, BEGIN IMMEDIATE transactions, per-connection RLock,
  source-hash/revision CAS, persistent OS project write lock. This is an explicit
  departure from the planned dedicated single writer thread. Two-store CAS
  concurrency acceptance passes. No implemented schema upgrade from future versions.
- Path guards refuse reparse/hardlink/traversal/overlap. All source files hashed,
  writable text snapshot captured. Original game 9570 files verified unchanged after
  browser validation. Never publish game assets, API keys, private work or worker logs.
- Native MV/MZ: DB/System fields, dialogue, scroll text, speaker reset, linked
  102/402 choice branches, actor commands, no-op byte preservation, exact JSON
  pointer changes. JS Acorn worker targets approved string literal ranges and checks
  AST shape, BOM/CRLF/Unicode. Ownership conflict refusal.
- Token markers enforce source controls, order and exact placeholders. 15 real-game
  units remain blocked for unknown R/en controls; no guessed rules.
- Cache projection, model-result ID matching, stale/locked/CAS protection; manual
  UI/import/OpenCC/translate/polish/table helper routes go through committer. Real
  LLM requests were NOT executed. Mock tests cover batch and table routes.
- Job state/restart recovery exists; full pause/cancel UI and resume checkpoints
  for every extraction/build/translation step are still incomplete. Failed build
  staging is retained, never resumed as if complete. No directory deletion.
- Game profile: 17386 units, 17934 occurrences, 178 JSON, 151 maps. Kd.words and
  8 approved plugin command rules implemented. SH_Nuiit, arbitrary 355/655 script
  texts and most 357 plugin args remain pending. Profile consumer evidence exists.
- Font cmap and estimated width checks; project-local font snapshot and MZ output
  System font override implemented. No actual full Chinese font gameplay acceptance.
- Frozen build snapshot, separate staging/output, full source and output hashes,
  manifest verification, disk budget checks. Real output test changed only two
  files with 11 Chinese UI terms. Not full game translation. No patch-only package.
- Qt game page, new/open/extract/validate/import/export/font/build/manual edits,
  legacy translation integration. Display caps at 5000 rows and filter, NOT a full
  unlimited virtual list. Full main window and real project opened in offscreen
  smoke. No user-driven complete interactive flow or real API acceptance yet.
- Browser-local output copy reached title and Scene_Map map46; runtime collector
  captured 25 Japanese display events. One layout error and 64 CanvasTextAlign
  warnings reproduced with original text bytes as baseline too. Title image
  buttons still English. NW.exe/save-load/battle/custom scene/branch flow not done.
- Unit acceptance last: 32 passed, 6 subtests. Optional real source extractors were
  present for this run. GUI source smoke exit0. Portable build and synthetic self
  check passed; final rebuild/audit/ZIP still pending after latest edits. CI workflow
  exists but has NOT run remotely; no clean-machine acceptance.
- Stev/RPGMTL/SExtractor isolated READ extraction APIs actually tested, source
  paths/pointers coverage compare and ambiguity reporting. Third-party WRITE,
  full project/state conversion, roundtrip for all engines NOT implemented. No
  automatic mixing backend write results.
- Migration requires exact locator set/source/policy match and target CAS/lock;
  tests pass, no fuzzy auto import.
- Runtime collector test output only; dedupe/ring bound/stop/read-only association.
  Map capture above; attribution can have multiple candidates and is never auto rule.
- Translator++ installation/actual API work now in progress by Codex. Mark H01
  IN PROGRESS with acceptance pending; do not claim installed or roundtrip yet.
- Image OCR/repaint H02 and multi-game suite H03 pending. Windows portable package
  is scoped to RPG, not all old AiNiee document parsers (e.g. Magika excluded).

Include prioritized followup gates and distinct code/tests/synthetic/private
game/browser/NW/remote CI evidence levels. Avoid speculative dates or effort spent.
