# AiNiee RPG 0.14.0-dev 本地交付

源码提交 fe5eb71cb6022cd558009d593ca7073db9a903bf。仅本地交付；未 push、PR 或远程 Release，旧交付保留。
便携包 AiNieeRPG-0.14.0-dev-windows-x64.zip，SHA-256 745ddb5f40d1e4fc941a7ee706761728c1d15310ace5c9b50e1a2b7c0d3a0985。
源码包 AiNieeRPG-source-fe5eb71.zip，SHA-256 593b088ce5e433db8812bb1aa3534ef4ccc300f529d1305cb06cd38a055f275c。

解压运行 AiNieeRPG.exe；包含 Python/Node，可运行 AiNieeRPG.exe --self-check。
不含游戏素材、工程、译文、用户或游戏字体、存档、截图、凭据或 worker 日志。
包含 Matplotlib 等依赖自带且附许可证的字体；可选外部工具单独安装。

0.14 修复任务枚举后正常结束造成的恢复竞争：取得租约后，在写事务内条件判断活动
状态，已完成/失败/取消任务保持终态。只读活动摘要，不解码历史大结果；检查点及
响应保留。锁文件不删除，不按年龄/PID 抢占。工程格式和构建写入计划 v6 不变。

源码完整回归 390 passed / 207 subtests，含官方安装版 Translator++ 8.8.9。
新增 17 项恢复专项用例，含真实 Windows 所属进程树退出及模型执行方终态竞争；
模型请求器为合成实现。新 ZIP 实际解压 EXE 的 19 组验收全部通过，包含自检、GUI、
格式/profile、迁移、三后端与图片/OCR、各恢复流程、进程树故障、后端比较、命令
审计、CommonEvents、JS AST/来源字节审计、配置文件原生句柄及新工程并发恢复。
构建文件替换另对 Windows 5/32/33 错误作最多六次尝试，总延迟 0.93 秒；每次重新
检查目标及暂存路径的重解析点和硬链接。新增七项源码测试及新 EXE 实际构建故障
验证：短占用释放后可发布，持续占用有界失败、原文件及完整暂存保留，不发布；
解除占用后显式新建构建可通过。没有宣称该暂存属于可自动复用的恢复检查点。

新 EXE 在当前游戏一致图副本上完成两个完整 GUI 并发读取 17716 行、存活写操作及
恢复拒绝、所属后端随父进程结束、遗留任务恢复和新候选成功。副本只添加一条人工
测试译文，之后数据集和译文保持；主工程数据库不变。实际冻结 CLI 的 SQLite 屏障
复现旧 0.13 的终态竞争，新版本 exit 0，FAILED 与检查点保持。屏障为合成故障时序。
原游戏 9570 文件集合/hash、原 profile4/profile5 库、旧格式只读兼容、验收后软件
hash 与源码/素材/凭据审计通过。没有执行 Game.exe 或真实翻译模型请求。

DeepSeek 通过 deepseek-worker 实现 ProjectStore/JobController 的两文件修复，guard
ready、无拒绝、受保护测试未改；Codex 负责设计、审查、独立测试、集成和交付。
使用默认 deepseek-flash/max，未指定 maxTokens；worker completed 本身不是验收。
B04 基础工程服务/重启/并发打开/租约已实现；全计划 21 已实现、12 部分实现、
1 用户后置，完整目标未完成。真实翻译、完整自然游玩、其他游戏、干净机器与远程
CI 等验收不包含在本次结论中。失败现场和本次测试产物保留，无批量删除。
统计逐行校验 34 个唯一任务 ID；旧 18/15 及本轮初始 19/14 汇总落后于明细。
本轮实际新增补齐 B04 一项，其余两项差额为汇总修正；旧交付原文保留。

详见 PACKAGE_MANIFEST.json、EXTRACTED_PACKAGE_CHECK.json、LEGACY_COMPAT_CHECK.json、
DELIVERY.json 与七项 SHA256SUMS.txt。

## 证据与修正记录

运行时代码提交 546998e；后续 fe5eb71 仅修正文档中的逐项汇总。PyInstaller 分析期间
运行时代码未变，状态文档在构建后复制，包内文档 SHA 与 fe5eb71 一致；源码 ZIP
对应该提交。本回执单独提交，不改变已交付的 ZIP 或运行时代码。

DeepSeek 两个独立任务分别只改 ProjectStore/JobController 与 PathGuard；guard ready，
deniedCalls/protectedChanges 均为空。Codex 设计受保护的红灯测试、复核改动并独立执行
源码、完整 CLI 和新 EXE 验收。后一个任务按更新后 Skill 无观察窗口运行；未读取或复用
Harness 凭据，未发真实翻译请求。两个 worker 均为 Flash/max、无 maxTokens 覆盖，
completed 保持 verified:false，测试与交付结论由本回执单独给出。

旧恢复逻辑三个源码终态竞争用例红灯，旧 0.13 EXE 的 SQLite 写事务屏障也返回 exit 1；
新实际 EXE 相同时序返回 exit 0，FAILED、stage 与 checkpoint 保持。真实原生模型执行
方失败时序、暂停后进程退出及人工锁定保留另有源码进程测试，不把屏障当作自然时序。

首轮完整回归 382 passed / 207 subtests passed、1 failed，原因是副本 Map001.json 替换
返回 WinError5；原目标、完整暂存、日志及数据库保留。源码原生句柄红灯随后复现相同
错误。七项新测试覆盖短占用、持续失败、两类无关错误、no-overwrite、延迟期间目标或
暂存新增硬链接。修复后专项组合 30 passed，最终完整回归 390 passed / 207 subtests
passed，保留临时目录 c1a34f0f51ea46128653a98bfb0bee3d。未重跑与改动无关的旧术语表组。

实际新 EXE 的构建用复制 SDK 的导入等待点确定时序，再由父进程持有真实 Win32
禁止 delete-sharing 的读句柄。短占用释放后 verify 通过；持续占用失败且未发布，原
目标及完整暂存保留，新建尝试成功。未声称未登记的 atomic_write 暂存可在原构建中
自动复用；未知文件仍阻止发布，由 E05 继续跟踪。本次没有批量删除或清理目录。

逐项状态有明确适用范围；21 项已实现不等于 P0、完整自然游玩、真实翻译、全部插件
或多游戏兼容已经验收。汇总由 34 个唯一任务 ID 重新统计，旧汇总曾落后于明细；本轮
仅新增补齐 B04，不把统计修正记为新增功能。完整目标保持未完成。

| 产物 | 字节 / 数量 | SHA-256 |
|---|---:|---|
| 便携 ZIP | 253919536 | 745ddb5f40d1e4fc941a7ee706761728c1d15310ace5c9b50e1a2b7c0d3a0985 |
| 源码 ZIP | 52101861 / 759 成员 | 593b088ce5e433db8812bb1aa3534ef4ccc300f529d1305cb06cd38a055f275c |

软件清单 3625 文件，七项 checksum 全部通过。
新解压 EXE 证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\extracted-package-check\51b2d3ad62ff40a79ad3efc194e41da0\evidence。
当前游戏并发/租约证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\frozen-project-leases\c3d9de9d337c490b9e9ecb3f9b1b629e。
构建原生句柄故障证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\frozen-atomic-build\dc199b7825964ffbb91efc818ed6cbcc。
终态事务屏障证据：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\recovery-barrier\a01065cfb0d94faf9e9dd777c8fe0de3。
原游戏复核：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\final-v14-original-audit\a943d06822144f7bb29663b6357572f3，9570 文件集合与 SHA 保持。
原 profile4 库 SHA：3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935。
原 profile5 库 SHA：3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。

交付目录：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\dist-rpg\releases\0.14.0-dev-fe5eb71。
