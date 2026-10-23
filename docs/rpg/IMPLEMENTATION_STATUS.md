# RPG工具当前实施与交付状态

更新：2026-10-24，Codex。当前程序7.2.4.1，增加外部工具管理与按需下载配置。
本次变更见 [发布说明](RELEASE_7.2.4.1.md) 和 [工具配置说明](EXTERNAL_TOOLS.md)。
旧0.41.0-dev-launcher-44261db封存记录保留原身份；下列游戏数据结论来自0.41验收，
本次没有重做模型翻译或将旧游戏验收改记为新版本实测。

**当前0.141的P0按用户批准的两处原版语法例外及列明范围通过。**
开发任务33项已落实，H03多游戏验收按用户决定后置。**完整A01–H03目标仍未完成**，
不会以当前游戏或合成更新代替其他真实游戏。真实DeepSeek内容翻译另按用户安排后续执行。

当前工程18669单元、999接受记录（含人工样例和原文锁）、17670未译；当前确定性
问题0、历史570条保留。2241静态字符缺字0。原版9570文件/原存档保持；9570输出
payload核对通过。181/183份原/输出JSON、188/189份JS文件可解析；1739事件块中
两处原版草稿精确保留，新增语法错误0。不能把这些计数称为完整中文译文质量。

验收决定：[P0逐项记录](P0_ACCEPTANCE_AUDIT_0.41.md)、
[用户批准的语法例外](BASELINE_SYNTAX_SOP.md)。
交付：[启动补订记录](DELIVERY_RECEIPT_0.41_LAUNCHER.md)、
[0.41数据/程序记录](DELIVERY_RECEIPT_0.41.md)、[使用说明](USER_GUIDE.md)。

## A01–H03逐项索引

各项对应原计划的实现及完成证据，不扩大具体版本、格式或场景范围。旧文档中的
“待验/部分”保留其当时快照含义；当前结论与下面列明的后续证据优先。

| ID | 原计划实现 | 当前状态 | 证据 |
| --- | --- | --- | --- |
| A01 | 建立 fork、upstream、功能分支，记录基线 SHA 与许可证 | 已实现，限定范围已验 | [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md) |
| A02 | 锁定 Python 与依赖，验证 GUI 启动和最小打包 | 已实现，限定范围已验 | [DELIVERY_RECEIPT_0.41](DELIVERY_RECEIPT_0.41.md) / [DELIVERY_RECEIPT_0.41_LAUNCHER](DELIVERY_RECEIPT_0.41_LAUNCHER.md) |
| A03 | 梳理译文所有写入点、自动输出和 Stev 文件副作用 | 已实现，限定范围已验 | [WRITE_ENTRYPOINT_AUDIT](WRITE_ENTRYPOINT_AUDIT.md) |
| A04 | 建立 MV/MZ 合成样例、私有游戏路径配置和忽略规则 | 已实现，限定范围已验 | [DEVELOPMENT_PLAN](DEVELOPMENT_PLAN.md) |
| B01 | Models、SQLite schema、迁移、单写线程、版本比较提交 | 已实现，限定范围已验 | [STORAGE_DECISION](STORAGE_DECISION.md) / [FORMAT_V2_EVIDENCE](FORMAT_V2_EVIDENCE.md) |
| B02 | GameRoot 检测、绝对路径边界、重解析点拒绝 | 已实现，限定范围已验 | [SCAN_EVIDENCE](SCAN_EVIDENCE.md) |
| B03 | 全文件 manifest、hash 与可改文件 source 快照 | 已实现，限定范围已验 | [P0_ACCEPTANCE_AUDIT_0.41](P0_ACCEPTANCE_AUDIT_0.41.md) |
| B04 | GameProjectService、工程锁、基础 JobController | 已实现，限定范围已验 | [JOB_RECOVERY](JOB_RECOVERY.md) / [PROCESS_OWNERSHIP_EVIDENCE](PROCESS_OWNERSHIP_EVIDENCE.md) |
| C01 | 标准数据库和 System 字段规则 | 已实现，限定范围已验 | [PROFILE5_EVIDENCE](PROFILE5_EVIDENCE.md) |
| C02 | EventRules：对话、滚动、选择、角色文字 | 已实现，限定范围已验 | [COMMAND_AUDIT_EVIDENCE](COMMAND_AUDIT_EVIDENCE.md) |
| C03 | JsonLocator、WritePlan、JsonPatcher、语义差异审计 | 已实现，限定范围已验 | [NATIVE_PROCESS_CONTRACT](NATIVE_PROCESS_CONTRACT.md) / [P0_ACCEPTANCE_AUDIT_0.41](P0_ACCEPTANCE_AUDIT_0.41.md) |
| C04 | AdapterRegistry、能力声明与写入所有权冲突检查 | 已实现，限定范围已验 | [C04_OWNERSHIP_EVIDENCE](C04_OWNERSHIP_EVIDENCE.md) |
| D01 | TokenPolicy、tokenizer、保护/还原/顺序校验 | 已实现，限定范围已验 | [CONTROL_R_EVIDENCE](CONTROL_R_EVIDENCE.md) / [FORMAT_V2_EVIDENCE](FORMAT_V2_EVIDENCE.md) |
| D02 | CacheBridge、场景分组与上下文策略 | 已实现，限定范围已验 | [CONTEXT_PREPARATION_EVIDENCE](CONTEXT_PREPARATION_EVIDENCE.md) / [KIND_PROMPTS_EVIDENCE](KIND_PROMPTS_EVIDENCE.md) |
| D03 | TranslationCommitter、模型 ID 对齐与 result_sink | 已实现，限定范围已验 | [WRITE_ENTRYPOINT_AUDIT](WRITE_ENTRYPOINT_AUDIT.md) / [FAILED_RETRIES_EVIDENCE](FAILED_RETRIES_EVIDENCE.md) |
| D04 | 接管人工编辑、校润、OpenCC、导入和自动输出 | 已实现，限定范围已验 | [MAIN_TASK_SCOPE_EVIDENCE](MAIN_TASK_SCOPE_EVIDENCE.md) / [TABLE_TASK_SCOPE_EVIDENCE](TABLE_TASK_SCOPE_EVIDENCE.md) / [PROOFREAD_SCOPE_EVIDENCE](PROOFREAD_SCOPE_EVIDENCE.md) |
| D05 | 任务暂停、取消、迟到结果和检查点恢复 | 已实现，限定范围已验 | [JOB_RECOVERY](JOB_RECOVERY.md) / [VALIDATION_RECOVERY_EVIDENCE](VALIDATION_RECOVERY_EVIDENCE.md) / [EXTRACTION_RECOVERY_EVIDENCE](EXTRACTION_RECOVERY_EVIDENCE.md) |
| E01 | JS Worker、字节范围映射、编码器、AST 差异检查 | 已实现，限定范围已验 | [DIRECT_DISPLAY_EVIDENCE](DIRECT_DISPLAY_EVIDENCE.md) / [DISPLAY_LABELS_EVIDENCE](DISPLAY_LABELS_EVIDENCE.md) |
| E02 | 当前游戏各自定义 JSON 消费者跟踪与 profile | 已实现，限定范围已验 | [CUSTOM_JSON_SCOPE_EVIDENCE](CUSTOM_JSON_SCOPE_EVIDENCE.md) |
| E03 | Kd.words、357 参数和必要事件脚本文字适配 | 已实现，限定范围已验 | [E03_FOLLOWUPS_EVIDENCE](E03_FOLLOWUPS_EVIDENCE.md) / [DERIVED_STATUS_EVIDENCE](DERIVED_STATUS_EVIDENCE.md) |
| E04 | FontInspector、LayoutProfile 与问题输出 | 已实现，限定范围已验 | [FONT_COVERAGE_EVIDENCE](FONT_COVERAGE_EVIDENCE.md) / [FONT_LAYOUT_EVIDENCE](FONT_LAYOUT_EVIDENCE.md) |
| E05 | BuildService、构建输入快照、staging、manifest | 已实现，限定范围已验 | [CURRENT_BUILD_RECOVERY_EVIDENCE](CURRENT_BUILD_RECOVERY_EVIDENCE.md) |
| F01 | 游戏汉化页面、虚拟列表、问题导航与构建面板 | 已实现，限定范围已验 | [GUI_WORKFLOW_EVIDENCE](GUI_WORKFLOW_EVIDENCE.md) / [COMPACT_UI_EVIDENCE](COMPACT_UI_EVIDENCE.md) |
| F02 | 运行第 17.3 节路径、修复已证实缺陷 | 已实现，限定范围已验 | [P0_ACCEPTANCE_AUDIT_0.41](P0_ACCEPTANCE_AUDIT_0.41.md) / [FULL_OUTPUT_RUNTIME_EVIDENCE](FULL_OUTPUT_RUNTIME_EVIDENCE.md) |
| F03 | Windows 便携包、离线自检、隐私与素材审计 | 已实现，限定范围已验 | [SANDBOX_ACCEPTANCE](SANDBOX_ACCEPTANCE.md) / [DELIVERY_RECEIPT_0.41_LAUNCHER](DELIVERY_RECEIPT_0.41_LAUNCHER.md) |
| G01 | Stev worker、地址映射与副作用白名单 | 已实现，限定范围已验 | [STEV_PROJECT_EVIDENCE](STEV_PROJECT_EVIDENCE.md) |
| G02 | RPGMTL 项目桥接与同文不同译处理 | 已实现，限定范围已验 | [RPGMTL_COMMON_EVIDENCE](RPGMTL_COMMON_EVIDENCE.md) / [RPGMTL_JS_EVIDENCE](RPGMTL_JS_EVIDENCE.md) |
| G03 | SExtractor worker、sidecar 与规则转换 | 已实现，限定范围已验 | [SEXTRACTOR_MAIN_EVIDENCE](SEXTRACTOR_MAIN_EVIDENCE.md) |
| G04 | 后端提取比较与覆盖差异报告 | 已实现，限定范围已验 | [BACKEND_COMPARISON_EVIDENCE](BACKEND_COMPARISON_EVIDENCE.md) |
| G05 | 新版本工程和可靠旧译文迁移 | 已实现，限定范围已验 | [MIGRATION_REVIEW_EVIDENCE](MIGRATION_REVIEW_EVIDENCE.md) / [MIGRATION_RECOVERY_EVIDENCE](MIGRATION_RECOVERY_EVIDENCE.md) |
| G06 | 输出副本运行采集和漏提关联 | 已实现，限定范围已验 | [RUNTIME_CAPTURE_EVIDENCE](RUNTIME_CAPTURE_EVIDENCE.md) |
| H01 | T++ 工程互通、版本探测与外部 API 桥接 | 已实现，限定范围已验 | [TRANSLATORPP_EVIDENCE](TRANSLATORPP_EVIDENCE.md) |
| H02 | 图片资源、OCR、框定位、重绘与编码 | 已实现，限定范围已验 | [IMAGE_EVIDENCE](IMAGE_EVIDENCE.md) |
| H03 | 扩展插件规则和多游戏验收集合 | 用户后置 | [DEVELOPMENT_PLAN](DEVELOPMENT_PLAN.md) |

## 证据范围及保留限制

- F03：实际0.40 Windows Sandbox自检、GUI及用户主窗口确认；0.41未变组件的比较
  和新增字段实际EXE流程分列。新启动脚本在宿主PS5.1及实际0.41原生窗口验证，
  没有重新声称0.41来宾实测或首次黑窗单一根因已解决。
- F02：原装完整副本完成计划列明路径，0.40人物页/0.41设置页另验。固定tick、
  引擎输入、战斗/手机显式准备、失败父run和原版缺图/console提示保留，不称全剧情游玩。
- 后端：官方T++8.8.9实际安装/API往返；Stev整目录ProgramData、SExtractor真实
  main_extract和RPGMTL指定JSON/JS均有直接证据。可选程序另装，不嵌入其完整产品；
  未批准字段、任意正则、其他引擎不获得自动回写能力。
- E02/E03：已确认显示字段定位，有限来源清单中的其他项有排除/SOP依据；不按日文
  特征自动开放，school→282等未证明显示的候选保持原文。新消费者出现即重新审查。
- H02：声明PNG/MV.rpgmvp/MZ.png_、人工干净底图及可视批准；实际三标题六区域已验。
  全游戏图片、复杂背景自动擦除、音频和全部美术质量未验。
- 模型语意质量、多游戏/其他真实更新版本、全部未触发剧情和远程CI未验。
  D03按原计划使用翻译桩验证响应关联，不把桩当真实提供商或真实后端。
- 存储/进程采用已登记实现决定：STORAGE_DECISION及WORKER_PROTOCOL_DECISION，
  不再维护一套只为匹配最初示例名称的重复框架。恢复证据不包括断电/物理磁盘耗尽。
- 便携包排除BabelDOC等8个依赖族，普通文档工作流不由RPG回执授予全功能声明；
  具体见PORTABLE_SCOPE。字体、游戏、存档、原始日志、私有截图和凭据不随包。

完整历史快照保存在[历史实施状态](history/IMPLEMENTATION_STATUS_20261023_before_P0_acceptance.md)，
其中旧失败、限制及各轮证据均未删除。本页替代历史文件中的待办状态，不改动已封存报告。
当前源码无后续DeepSeek worker/子agent调用；没有批量删除或在线发布。
