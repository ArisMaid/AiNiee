# 0.20.0-dev 本地交付回执

日期：2026-10-19。运行源码提交 `c7a1e90505f82433bf578e66a7c2dc85f014234c`，分支 codex/rpg-localization-core。
本地目录 `dist-rpg/releases/0.20.0-dev-c7a1e90`。未 push、PR 或远程 Release，旧版交付保持。
本回执在运行源码封包后提交；ZIP 内源码对应上述提交，交付文件以七项 checksum 核对。

## 交付与验证

- `AiNieeRPG-0.20.0-dev-windows-x64.zip`：254037369 字节，SHA-256 `1a03470578bb821f2ecd7db4083f329f442b0b356346ac59615d0639cb374297`。
- `AiNieeRPG-source-c7a1e90.zip`：52227375 字节，797 成员，SHA-256 `91f4c95dd36e3ccda476980acb4744b22eb69cd57005fb1fe9d59fc27ad41a49`。
- 3630 软件文件逐项 SHA、七项交付 checksum 和 ZIP 完整性通过。
- 源码专项 27、完整 501 passed /207 subtests passed，含安装版 T++8.8.9；一条既有依赖弃用警告，零 skip/fail/error。
- 新 ZIP 解压后实际 EXE 自检、GUI 和 22 组专项，共 24 组通过。子进程 PATH 仅 System32，使用包内 Python/Node/Qt。

## G03 真实主入口

SExtractor 默认回写改为真实 `main_extract_json.mainExtractJson → main_extract.mainExtract`：
提取/导入各一个新 worker，真实读文件、导出列表、读取译文和写出；不修补本地输出或自动降级。
逐阶段固定输入/配置/目录和可写文件，核对 ctrl/text/列表、原位置、类型保持的完整批准差异。
空变更也真实往返，返回实际上游 bytes；工具可改变 JSON 排版，不能再当作原字节透传。

工程格式 2、写入计划 v7 保持。`src/engine.ini` 新纳入路由指纹，旧 SExtractor 路由需重新
生成候选并选择。只读覆盖比较仍为独立内存 API，不把覆盖结果当作显示许可。
通用 JSON 模块对当前六文件的实际缺覆盖/TypeError 已保留；正式路径固定 RPGMV，不自动回退。
原计划 §14.3 七项及 §14.5 最低条件逐项对应见 SEXTRACTOR_MAIN_EVIDENCE.md。

源码五项入口验收先在 0.19 全失败，最终入口/副作用/既有数组事件专项 27 通过。
新解压 EXE 的零变更、两处同文不同译、未请求同文保持及完整构建均通过；未声明文件写入、
os.open 来源截断和 socket 创建在发生前被拒，配置改变阻断构建。实际导入写部分文件时取消，
确认所属 PID 55456 已退出、部分文件保留、无成功 sidecar/候选发布且译文不变。
阶段间取消、父进程证据持久化失败也有源码直接验收。guard 是固定 SDK 的审计边界，非 OS 沙箱。

## 当前游戏源码与冻结构建

源码和新 EXE 各执行 Stev/SExtractor 两个完整测试构建。每后端六文件、16 批准 JSON 位置，
含 Items、Skills、System、Map023、CommonEvents、SH_Nuiit；9570 清单文件另加两个构建元数据文件。
核对实际 writer/sidecar、SExtractor 每文件两阶段/PID/入口及配置 hash、完整来源和实际输出；
另核对 JS AST、批准图片字节、显式字体/映射及全部输出集合/hash。两个后端非路由输出逐字节一致。

| 执行 | 后端 | 构建秒 | 清单文件 |
| --- | --- | ---: | ---: |
| 源码 | stev | 214.56 | 9570 |
| 源码 | sextractor | 232.60 | 9570 |
| 冻结EXE | stev | 201.61 | 9570 |
| 冻结EXE | sextractor | 221.59 | 9570 |

主工程 17716 单元/29 接受译文保持。各独立副本保留旧人工样例、加两个 Items 并锁一条，
共 31 接受、17685 未译；明确 `--test`，verify 通过，runtime not_run。没有模型请求或游戏启动。
原游戏全部 9570 文件（包括构建排除的日志/存档）、主 DB、图/译文/锁、SDK source/config 保持。
构建来源保护集 9568 加两个显式字体相关文件，不能把清单数量等同于原游戏集合。

源码证据 `work/current-json-builds-v20/ed9711691019409e980557d2003b857e`；
冻结证据 `work/current-json-builds-v20/b76a55481acd49f68794f5f1e5daf203`；
新主入口故障证据 `work/frozen-sextractor-main-v20/6a7d9a1258d1447caf7f14d6b6c73e4f`。
新 EXE 既有格式、迁移、租约、恢复、所有权、JS、存储与三种窗口 GUI 组也重新执行。
旧格式 1/profile4 只读 summary 及数据库 SHA 保持；0.19 七项封存 checksum 保持。

## 协作、范围与目标

使用 deepseek-worker，deepseek-official/deepseek-flash/max，无 maxTokens 覆盖；复杂任务上限
1500 秒，1294.458 秒返回。目录 grep 被 guard 拒绝一次，policy_violation 按失败交接，
仅四个授权文件改变，保护文件在交接时不变。Codex 接管修复哈希键映射、依赖本机名误拦截、
持久化及控制向量检查并加入配置固定，独立测试、审查和交付；没有放宽 guard。
原型驱动参数/规则名及首轮依赖误拦截的失败现场均保留，未归因于游戏。

总表更新为 23 已实现、10 部分、1 用户后置；G03 在指定 RPGMV/MZ JSON 主入口范围已实现。
完整计划和 P0 仍未完成：G01 整目录 GameDir/ProgramData、其余显示来源/事件、排版/图片质量、
完整自然游玩、真实翻译、干净机器和远程 CI 等仍有未完成项。其他游戏按用户决定后置。
本次条件续跑检查时目标系统返回 usageLimited，未擅自改为 active/complete；单次自动化已移除。

包无游戏素材、工程/译文、用户字体、截图、凭据或 worker 日志；包含 Matplotlib 依赖附带
40 字体及许可证。本机隔离 PATH 验证不代替干净机器。没有批量删除文件或目录。
