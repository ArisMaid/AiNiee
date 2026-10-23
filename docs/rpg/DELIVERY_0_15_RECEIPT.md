# AiNiee RPG 0.15.0-dev 本地交付

源码提交 8b7ce8921fcf568e933abe1cabcc4e3ec72be740。本地交付，未 push/PR/远程 Release，旧交付保留。
便携 ZIP：AiNieeRPG-0.15.0-dev-windows-x64.zip，SHA-256 95d34c660ddbdb2bcd981bf1da55eb7a1b252616942a66573cdbf58e347c87cb。
源码 ZIP：AiNieeRPG-source-8b7ce89.zip，SHA-256 0fdbf86ec406aad2829509dc4baadf96de8236691a0714e14729252fbf793b18。
解压运行 AiNieeRPG.exe；包含 Python/Node，可运行 AiNieeRPG.exe --self-check。
不含游戏素材、工程、译文、用户或游戏字体、存档、截图、凭据或 worker 日志；包含
Matplotlib 等依赖自带的 40 个字体文件及相应许可证。可选外部工具单独安装。

新增构建写入前登记、与冻结输入绑定、实际字节证据及单文件归档恢复。半写入暂存
也保留并重新生成；未登记、绑定不符、证据矛盾或字节变化仍阻断。归档后进程退出
可核对既有证据继续，不把暂存当作已完成检查点。翻译、字体、采集及完成标记接入。
工程及原 BuildJournal 物理格式不改；写入计划 v7 拒绝恢复旧 v6 未完成构建，旧成品
仍可独立 verify，旧诊断保留。跨文件系统归档明确拒绝，不隐含复制后删除。

源码完整回归 417 passed / 207 subtests passed，含安装版 T++8.8.9。新 ZIP 实际 EXE
19 组验收通过；原生句柄 CLI 五场景包括短占用、持续失败恢复、进程退出、半写入退出
以及未登记同名暂存拒绝。恢复同一 build_id，人工后续修改与锁保持，输出使用冻结译文。
当前游戏 17716 单元的一致图副本，加入一条人工样例后注入真实文件占用，恢复同一
构建，复用 1933 文件；完整 9570 个输出清单文件 verify 通过，
含构建元数据的实际输出 9572 文件。其他译文及数据集保持，
原游戏 9570 文件集合/hash 和主 profile4/profile5 库不变。没有真实翻译模型请求或 Game.exe 执行。

DeepSeek 在 900 秒上限处超时，交接失败；guard ready、无拒绝、保护测试未改，日志和
代码现场保留。Codex 接管审查，修复恢复返回键错误、移除重命名测试绕行并将故障注入
限定到归档动作，补齐路径/元数据边界和集成。该超时没有被当成 worker 完成或验收。
旧源码及旧 0.14 EXE 红灯、worker 代码首次验收 8 failed / 13 passed、完整回归中旧故障
注入函数缺少新 writer 参数的现场均保留；修正参数转发后原故障边界及语义断言保留。
使用 deepseek-worker 默认 Flash/max，未指定 maxTokens。

全计划 21 已实现、12 部分实现、1 用户后置，E05 继续按完整范围跟踪，目标未完成。
真实翻译、完整自然游玩、其他游戏、干净机器和远程 CI 验收仍待补齐。所有本轮失败及
测试产物保留，没有批量删除。七项 checksum 及详细证据见对应 JSON 清单。

## 交付证据与保留边界

运行时代码、源码包与便携包对应同一个本地源码提交；本回执在 ready 后单独提交，不
改动已交付 ZIP。只做本地交付，未创建远程 PR、push 或 Release。源/包隐私审计覆盖
原游戏文件内容匹配、私有目录、数据库、存档、凭据模式和工作日志，已通过。

DeepSeek 通过 deepseek-worker 实现登记与归档模块的初稿，在 900 秒上限处超时。
guard ready、无 deniedCalls 或 protectedChanges，状态 timed_out、workerCompleted:false、
verified:false；这次交接失败。Codex 确认该进程及直接子进程已退出后接管，审查全部
代码与失败副作用，修复恢复返回路径键、移除仅为隔离测试故障注入增加的 contextvar
重命名分支，改为将测试故障点限定到归档动作；补齐输入路径和元数据边界。字体、
采集、HTML 和完成标记由 Codex 集成到同一注册写入器，没有接受 worker 的完成声明。

旧源码原生句柄红灯保留在 work/acceptance/rpg-0.15-atomic-resume-red.log；新创建的
合成工程对旧 0.14 EXE 也报 BUILD_STAGING_FILE_SET_CHANGED，日志为
work/acceptance/rpg-0.15-frozen-0.14-red.log。worker 初稿首次 8 failed / 13 passed
保留在 rpg-0.15-worker-review-red.log；审查修正后组合专项 43 passed。
首轮完整回归 416 passed / 207 subtests passed、1 failed：旧字体故障注入函数没有转发
新增可选 writer 参数。补齐参数转发并验证四类输出已登记，原失败边界和字体/采集完整
性断言保留；最终完整回归 417 passed / 207 subtests passed。所有现场和产物均保留。

源码真实 Windows 进程在完整暂存、半写入暂存及归档后退出，恢复实际保留对应字节，
使用冻结译文重建，保留人工后续编辑及锁。登记的预期摘要没有被当作实际字节摘要，
归档临时文件也不自动授予输出成功检查点权限。无登记但名称和内容相同的临时文件
仍会阻止发布。证明归档后返回前退出的源进程用例与新 EXE 的四类 native 锁/退出时序
分开记录，不把合成屏障、源码故障注入或旧 EXE 当成本版自然游玩验收。

新 EXE 五场景在新的合成工程上使用复制 SDK 的导入等待点确定时序，再用 Win32 读
句柄控制 delete-sharing；未加入应用测试钩子。输出构建、字体及采集其他回归也在新
EXE 执行。当前游戏的大副本恢复另由源码路径验证，未声称相同游戏大构建在新 EXE
重复执行。原主工程库和原游戏只读核对，未发送真实翻译模型请求或执行 Game.exe。

只允许已登记、同构建、已知尝试、冻结输入/计划一致的合法目标临时文件单个归档。
未知文件、旧 v6 临时文件不按名称猜测；跨文件系统拒绝且保留，不复制后删除。原
工程及 BuildJournal 的物理 schema 不升级，写入算法标识改 v7，旧未完成构建需要新建。
旧完整副本继续独立 verify。E05 仍按全计划跟踪，未因一个恢复场景补齐而宣称全部完成。

| 产物 | 字节 / 数量 | SHA-256 |
|---|---:|---|
| 便携 ZIP | 253943813 | 95d34c660ddbdb2bcd981bf1da55eb7a1b252616942a66573cdbf58e347c87cb |
| 源码 ZIP | 52123653 / 763 成员 | 0fdbf86ec406aad2829509dc4baadf96de8236691a0714e14729252fbf793b18 |

源码提交：8b7ce8921fcf568e933abe1cabcc4e3ec72be740。
软件清单 3625 文件，七项 checksum 通过。
新解压 EXE：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\extracted-package-check\b749f832b82d48ec8c5abd9a01211c05\evidence。
新 EXE 五种原子恢复场景：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\frozen-atomic-resume\3af6e5729d514d00b7a86ce46bd1b1a1。
当前游戏一致副本：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\atomic-current-game\7098a690f1654cccbc6c3b7dff37282e。
同一构建 970ffb9ec29445939986abd457e0a407，复用 1933 文件，输出清单
9570 文件，含两项元数据共 9572 文件。
实际暂存 SHA-256：e1483e05ecb4e6b84df8c4eb83c09ae4acd911be4c5730b124b0a854d67b2822。
原游戏审计：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\work\final-v15-original-audit\ab6f212530c54123afbf05f3b439a5ae，9570 文件集合/hash 保持。
原 profile4 库 SHA-256：3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935。
原 profile5 库 SHA-256：3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。

交付目录：D:\Github\AI\Codex\RPG一条龙工具\AiNiee\dist-rpg\releases\0.15.0-dev-8b7ce89。
