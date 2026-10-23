# Third-party components

The fork retains AiNiee's AGPL-3.0 license and upstream copyright notices.
Baseline: NEKOparapa/AiNiee commit 7bbb06be33f5968f0723a5200a150d895d4fa5fb.
Existing fork: ArisMaid/AiNiee. New code is under the repository license.

The portable RPG build bundles Python/PyQt5 and their dependencies; Python
distribution license files available in the installed environment are collected
under licenses/python. Dependency versions are listed in requirements-rpg.lock.
Acorn 8.19.0 is MIT licensed; its LICENSE is retained inside the Acorn runtime
directory. Node.js 24.16.0 is redistributed with its complete license text under
licenses/node-license.txt. Python and Qt binary redistribution notices remain applicable.

Optional source extractors are installed separately and are not bundled into the
portable archive:

| Component | Inspected source revision | Integration boundary |
| --- | --- | --- |
| RPGMTL | 0fa346b020e439fd392027f735107a283c9836d9 | approved JSON, CommonEvents script and JS literals via isolated SDK workers; per-occurrence mapping |
| SExtractor | 8d8d976fd04ae54e7c677705af937273d04a376a | mainExtractJson/mainExtract RPGMV JSON extract/import in separate private processes; memory API retained for read-only comparison |
| StevExtraction | source already present at AiNiee baseline above | Jr_Tpp ReadGame, ProgramData and InjectGame on complete private copies; selected JSON outputs audited before publication |
| Tesseract Windows build | UB Mannheim 5.4.0.20240606 | optional local OCR process, not bundled |
| tessdata_fast | 87416418657359cb625c412a48b6e1d6d41c29bd | optional Japanese language data, not bundled |
| Translator++ | 8.8.9 | on-demand official public archive; loopback exchange, not bundled |
| 7-Zip | 26.05 | on-demand official x64 MSI, administrative extraction only, not bundled |

On-demand sources and exact SHA-256 values are in Resource/ExternalTools/catalog.json.
7-Zip license and source: https://www.7-zip.org/license.txt and https://www.7-zip.org/ .
Translator++ public release: https://github.com/dreamsavior/TranslatorPlusPlus/releases/tag/8.8.9 .
Downloaded tools retain their upstream license files; they are separate installations.

Consult each upstream repository's license before distributing its source or
binaries. Compatibility APIs do not grant rights to game assets, fonts or
translations. No original game assets, private work directories, API credentials,
model responses or DeepSeek execution logs are part of the portable application.
