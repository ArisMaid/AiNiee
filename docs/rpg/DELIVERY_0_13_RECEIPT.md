# AiNiee RPG 0.13.0-dev 本地交付

源码提交0c8d01ad72b4fed92db90348fb0291e305f27eab。仅本地交付，未push/PR/远程Release，旧交付保留。
便携包AiNieeRPG-0.13.0-dev-windows-x64.zip，SHA-256 99c34ae572e7f2ff67295356b4d5334f210d8915538b97807244bcc1425ef19f。
源码包AiNieeRPG-source-0c8d01a.zip，SHA-256 dfc7066c3e0e6ef0b3e4208fd5fd80e119969d4634959c41e2dadbb5dec07e72。

解压运行AiNieeRPG.exe，包含Python/Node；离线自检AiNieeRPG.exe --self-check。
不含用户游戏素材、工程、译文、用户指定的游戏字体、存档、截图、凭据或worker日志；外部工具单独安装。

新增RPGMTL指定JS文字真实read/write、来源区间证明、每位置本地译文、Unicode转义
传输和父进程AST/译后值/区间外字节审计。仅指定单/双引号文字；不翻译模板/正则，
plugins.js注册表留给原生规则。候选/构建/检查点用相同证明，不静默改用原生writer。
GUI只向已有批准文字的JS提供原生/RPGMTL选择；JSON比较仍保持原有范围。

源码完整回归366 passed / 207 subtests，包含安装版T++8.8.9；另有保留式术语表复测11项通过。
当前游戏图副本两个JS文件9个接受位置通过真实候选、路由构建和独立Acorn审计，完整
9570个游戏清单文件verify通过（副本另含2个构建元数据文件），17716单元/29译文和原profile5数据库不变。原9570文件集合及hash、
原profile4数据库再次保持。无全游戏运行或真实模型翻译结论。

新ZIP实际解压EXE仅System32 PATH完成17组：自检、17716行GUI、格式v2、profile3、
迁移、三后端/图片/OCR路由、构建恢复、校验恢复、提取/审查、迁移恢复、进程树故障、
共享后端比较、命令审计、CommonEvents证据与上游失败、完整比较证据与类型冲突，
以及Windows配置短占用恢复/持续失败/读取拒绝，旧文件保持，和新JS三个位置/同文不同译/转义/BOM/CRLF/拒绝未支持路由/显式恢复原生构建。
旧格式1/profile4只读兼容、验收后软件文件集合/hash、源码/游戏内容/凭据审计通过。

DeepSeek负责基础审计与映射模块，guard无拒绝、受保护测试未改；Codex审查修正并完成
SDK/GUI/构建集成、独立测试与交付。使用deepseek-worker默认Flash/max，未指定maxTokens。
G02按指定JSON/JS能力完成；总计18项已实现、15项部分实现、用户后置H03，完整计划
仍未完成。真实翻译及其他游戏按用户决定后置，完整自然游玩、干净机器和远程CI未验收。
0.13写入计划v6拒绝恢复旧算法未完成构建，旧暂存和译文保留。RPG/EXE及保留式复测产物保留。旧术语表首轮自动清理合成临时目录的漏查与修正详见回执。

PACKAGE_MANIFEST.json、EXTRACTED_PACKAGE_CHECK.json、LEGACY_COMPAT_CHECK.json与
DELIVERY.json可核对，七项checksum见SHA256SUMS.txt。

## 本地证据与边界

开发提交608b0b2包含RPGMTL JS桥接；c158ee8补齐根目录文档审计；6afe9e0增加
Windows替换配置的有界重试；最终0c8d01a拒绝配置读取I/O失败后的空配置覆盖。
本回执在上述源码交付之后单独提交，不改变已打包的运行时代码。

首轮新增说明未登记被审计拦截；c158ee8候选通过ZIP/源码/自检，但新GUI遇到配置替换
WinError5，保留在dist-rpg/releases/0.13.0-dev-c158ee8并标记NOT_READY，不能当成交付。
读取错误的load/save两项红灯用例随后复现旧问题，修复后的源码与新EXE分别验收。
没有通过忽略错误、放宽素材/凭据审计或静默改用原生writer来获得通过。

最终新EXE前15组已完成后，新JS私有验收脚本的导出父目录包含源目录，被路径守卫
正确拒绝；只将脚本改用独立interchange目录。保留该次失败与15组当前EXE证据，
仅重跑JS及尚未运行的配置两组，合计17组；同一解压EXE/软件集合hash前后不变。

补充旧术语表首轮11项测试自带TemporaryDirectory自动清理了新建合成临时目录；运行
前漏查，不符合禁止批量删除要求。原游戏/工程不在这些临时目录中，未受影响。
已移除该清理，改为mkdtemp保留并补齐独立Qt路径初始化；两轮保留式复测各11项通过，
共22个新目录保留。中止的独立Qt启动日志、配置红灯用例及所有RPG/EXE失败现场也保留。
没有把那一轮称为全部产物保留。测试入口只约束pytest自身清理，其他旧测试仍需先检查。

当前游戏验收沿用已有29条接受译文，只在一致图副本中选择两个JS文件的9个位置；
原profile5数据库未变。游戏清单9570个文件，加两个构建元数据文件，总9572个输出文件；
verify通过，不等于全游戏已翻译或全自然游玩通过。原9570文件集合/hash与原profile4库
另行复核不变。没有运行原Game.exe，也没有发送真实翻译请求。

配置修复仅在Windows5/32/33替换错误上最多六次尝试，五次延迟总0.93秒。新EXE真实
原生文件句柄证明短占用释放后GUI恢复，持续占用时保留旧配置和独立暂存，禁止读共享
时直接失败、不产生暂存、不将原配置移为损坏文件。它不提供跨程序配置编辑CAS。

软件、源码、来源与交付元数据的SHA均可从DELIVERY.json和SHA256SUMS.txt核对。
未在新EXE重复自然游戏路径，也未把旧版冻结证据当成本版执行结果。

| 产物 | 字节 / 数量 | SHA-256 |
|---|---:|---|
| 便携ZIP | 253914551 | 99c34ae572e7f2ff67295356b4d5334f210d8915538b97807244bcc1425ef19f |
| 源码ZIP | 52086046 / 755成员 | dfc7066c3e0e6ef0b3e4208fd5fd80e119969d4634959c41e2dadbb5dec07e72 |

软件清单3625个文件，校验和7项。
新解压证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\extracted-package-check\97447896b10d418c95d8c7d6abea24b5\evidence。
当前游戏图副本证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\rpgmtl-js-current-game\748aabed4ee9419abc87f5e3757ed5a7。
原游戏复核证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\final-v13-original-audit\b878b4017ccc4422bd190ec6446615aa。
原profile4库SHA-256：3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935。
原profile5库SHA-256：3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。

交付目录：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\dist-rpg\releases\0.13.0-dev-0c8d01a。

依赖范围澄清：软件依赖Matplotlib自带40个字体文件，DejaVu/STIX许可随包；没有打入用户指定的游戏中文字体。交付说明已同步澄清并刷新七项checksum，运行时ZIP与源码ZIP未变，原说明和checksum快照保留。
