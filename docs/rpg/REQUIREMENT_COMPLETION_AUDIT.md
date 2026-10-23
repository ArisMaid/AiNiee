# 原计划条款复核

2026-10-23最终更新：用户已明确接受两处原版语法基线例外，第17.3.6条和精确
摘要已登记；当前来源/ZIP/输出完整清单及全文件/事件脚本语法另已独立核对。
当前P0决定见P0_ACCEPTANCE_AUDIT_0.41.md，状态索引见IMPLEMENTATION_STATUS.md。
33项开发已落实，H03多游戏按用户决定后置，完整目标仍未完成。下文为此决定前
保留的条款映射与阶段快照，其中“P0/profile仍开放”不再代表最新判定。

2026-10-23。本表按DEVELOPMENT_PLAN.md原条款核对，不能用第19节“33项已实现”
直接推出目标完成。已实现组件的限定证据见下表；未闭合条款保持开放。本表尚不是
全目标完成证明，也不改变用户只验当前游戏、真实翻译以后进行的安排。

## 当前缺口及下一步

0.41启动补订落实了实际可交付的正常入口：PS5.1参数/日志检查和宿主实际EXE
响应窗口通过，日常不启用offline，不迁移已有配置。原0.41软件和运行代码保持；
仅包装/说明补订，不将宿主窗口观察改称新沙盒验收。见
DELIVERY_RECEIPT_0.41_LAUNCHER.md及SANDBOX_ACCEPTANCE.md。

最新0.41封存/实际程序验证已通过，见DELIVERY_RECEIPT_0.41.md。四名称问题有
完整来源、SDK、实际EXE及原装设置页证据；独立源码分类也已关闭参数141项的
待分类状态，202叶子中61定位/141明确保留/0未分类。旧菜单标签与条件比较
耦合，因此按SOP成组保留。封包报告中的141待分类是此前快照，补充证据独立
保存，不能将分类计数当作完整profile或全目标通过。

新增4个名称的修复和完整验证已进入封存0.41，其余141参数的分类补充独立保存。
原93项SOP清单与参数清单使用不同分母，详见E03_FOLLOWUPS_EVIDENCE.md。
整体目标和正式profile仍保持未完成。

0.40来宾自动自检/offscreen GUI已实际执行并独立复核通过，50份证据、包/EXE
摘要及中文截图均已取得。初始只有黑色控制台的失败保留；后续同一来宾正常
启动诊断在第6秒采样观察到本版原生响应窗口，用户确认主界面出现。F03按列明
启动SOP关闭，未隔离单一根因；见SANDBOX_ACCEPTANCE.md。以下“来宾待执行”
属于历史快照，完整profile及整体目标不由本次环境门槛自动关闭。

第17.3节12项已另逐项核对直接证据、稳定实现和原版限制，见
P0_ACCEPTANCE_AUDIT_0.40.md。本轮进一步核对剩余93项的数值/对象别名：变量80
14个消费作用域及2个后续helper均未读配置name；282的已找到数值引用分清写入、
公共事件ID与坐标。保留未证明的动态边界，并未把“未发现”升级成完整profile通过。
另明确原版公共1、45的两段非完整JS草稿及其静态无调用/无自动触发范围；不修原
游戏草稿以凑语法零错误，不重复构建或增加底层分析框架。

0.40源码复核取得反例：变量375经Scene_Heart.profileVars.teisou进入原人物页，
不是旧SOP所称未证明显示用途。新增6个source-span后SDK、完整18665/995图、
9570文件构建及原装消费者通过；0.39旧包缺口保持。0.40新包已封存，实际EXE的
六字段往返、旧图升级与当前GUI通过，本版实际沙盒入口待执行。原99项SOP
减少为93项，剩余有限清单和全动态路径不由本次反例推定通过。详见
DERIVED_STATUS_EVIDENCE.md。正式profile与整体目标继续未完成。

2026-10-23交付更新：0.39已封存并通过实际EXE离线/GUI/扫描重开检查，变化模块
冻结语义代码核对通过，详见DELIVERY_RECEIPT_0.39.md。下表源码条款均已有列明
实现与证据；其中“冻结另验”保留为此前快照。独立F03来宾执行现已通过，
自检/GUI exit0、中文截图与用户正常窗口确认齐备，见SANDBOX_ACCEPTANCE.md。
原包保持，修正辅助脚本另附；真实翻译、H03与§17.3.12的正式profile判定分列。

| 条款 | 当前直接观察 | 状态与下一步 |
| --- | --- | --- |
| 10.4；11.2.6 | 原分类提示缺失；表格翻译/润色无重试、校对仅两次尝试、主任务默认10轮 | 分类提示0.38已封包；重试0.39源码实测及冻结语义比对通过。未称冻结进程执行17份请求；见KIND_PROMPTS_EVIDENCE、FAILED_RETRIES_EVIDENCE及0.39收据 |
| 7.1.3–4 | 0.39增加持久识别证据，交叉记录入口/核心声明、标准缺项及加密状态；运行版本在静态阶段明确未测 | 当前真实MZ报告、MV www合成、重开/提取、冲突拒绝及原装NW0.48.4二进制hash对照通过；冻结EXE合成扫描/提取/跨进程重开通过，见SCAN_EVIDENCE及0.39收据；不声称静态自动测出NW版本或其他游戏实机通过 |
| 12.4 | 现有一次请求协议与父作业进度/问题/检查点职责已逐项对照，身份/大小/取消边界存在 | 按用户避免底层过设的约束采用WORKER_PROTOCOL_DECISION，并在原计划索引登记。消息形式明确不同，未称原流式消息API兼容；进程协议代码自e22f87c未变，原真实26项证据保留 |
| 13.5 | 既有构建/Stev阶段磁盘预检保持；0.39按清单计算资源基线，在构建和后端按钮提前提示额外副本及历史目录保留 | 当前9570文件/1.68GiB和三个实际源码Qt按钮提示通过，冻结相关模块完整语义一致；冻结summary统计通过，未直接观察冻结tooltip。见SCAN_EVIDENCE及0.39收据；不增加空间预约/自动清理 |
| F03；21.3 | 0.39实际Sandbox自检/GUI均exit0，原PATH无Python/Node，摘要与中文截图独立复核，用户确认正常窗口 | F03按第19节完成，33/0/1；不继承为完整§17.3/profile或真实模型验收。映射SQLite失败与null退出码误判已用本地SOP/包装脚本修正 |
| H03；17.1 L4 | 用户决定目前只测当前游戏 | 用户后置，保留未来多游戏验证；不以合成更新或当前MZ替代其他MV/MZ实机兼容 |

## 按原章节保留的证据映射

下表指向现有行为证据及当前源码职责；“已有证据”仅覆盖各文档明示范围，并非已将
每一项原条款重新独立验收。上述开放项优先于下表，不会被历史成功记录覆盖。

| 原条款/范围 | 实现或证据入口 | 复核边界 |
| --- | --- | --- |
| 1.1(1–3)、3.1–3.3 | GameProjectService、GameProjectPage；GUI_WORKFLOW_EVIDENCE、COMPACT_UI_EVIDENCE | 选目录/工程/提取/显示与问题操作；自然按钮、模型质量、运行验证分开 |
| 1.1(4)、11.2(5) | GameAnalysisExecution、AnalysisTask；ANALYSIS_WORKFLOW_EVIDENCE | 术语候选需确认；应用词典按SOP管理，不自动污染译文 |
| 1.1(5–8) | ValidationService、BuildService、PatchService、MigrationService | 控制/结构/字体、独立副本、补丁、可靠迁移；实际运行另验 |
| 4.1–4.4、5.1–5.5 | Models、ProjectStore、CacheBridge、PathGuard；IMPLEMENTATION_CONTRACT、STATUS_CONTRACT仅作历史接口背景 | SQLite权威、投影可重建、来源/工程/输出隔离；示例类型名/表名不作为另一套数据真相 |
| 5.6(1–7)、B01/B04 | ProjectStore.commit、ProjectLock；STORAGE_DECISION、MANUAL_EDIT_ATOMIC_EVIDENCE | 明确采用SQLite串行事务/连接锁/CAS替代专用单写线程；逐单元提交与审计，不假称整个批次一次事务 |
| 6.1–6.3、C04 | Registry、WriteOwnership；CAPABILITIES_CONTRACT、C04_OWNERSHIP_EVIDENCE | 已注册组件能力、物理写入区间及冲突拒绝；无自动混合回写 |
| 7.2、7.3全部事件类别、7.4(1–7) | JsonExtractor、EventRules、JsonPatcher；PROFILE_EVIDENCE、CONTROL_R_EVIDENCE、EVENT_LITERAL_CODEC_CONTRACT | 字段白名单、行槽与关联选项、无改动字节保持、语义差异限定；未知命令保留候选 |
| 8.1、8.2(1–8)、8.3 | JsBridge/worker.cjs、EncodedJsonText；JS_SCOPED_OBJECT_CONTRACT、test_js_output_audit.py、E03_FOLLOWUPS_EVIDENCE | 静态AST、UTF-16/字节映射、编码/模板、批准节点、原装NW路径；未执行脚本来发现未知文字 |
| 9.1–9.4 | 当前0.141 profile；PROFILE5–8_EVIDENCE、E02_REMAINING_FIELDS_EVIDENCE、E03_FOLLOWUPS_EVIDENCE | 指纹/规则批准；自定义JSON各字段消费者与SOP；99项SOP不称全局不可达 |
| 10.1–10.3、11.3 | TokenPolicy、TranslationCommitter、ProjectStore.commit；LITERAL_TOKEN_CONTRACT、CONTROL_R_EVIDENCE、FORMAT_V2_EVIDENCE | ID准确对应、marker还原、真实ESC/字面控制、策略/CAS；语意质量提示与确定性阻断分开 |
| 11.1、11.2(1–4,7–8) | CacheBridge、GameBatchPreparation、GameBatchRunner；CONTEXT_PREPARATION_EVIDENCE、SCOPE_ACCEPTANCE_0.36 | 稳定身份、连续场景、选项问题、只读邻文、token分类；真实提供商后置 |
| 11.4各写入入口、11.5 | GameCacheIdentity、GameTaskScope；WRITE_ENTRYPOINT_AUDIT、MAIN_TASK_SCOPE_EVIDENCE、TABLE_TASK_SCOPE_EVIDENCE、PROOFREAD_SCOPE_EVIDENCE | 原生提交、人工/导入/OpenCC/主任务/表格/校对、输出预检和自动输出；普通文档另走原路径 |
| 12.1–12.3、12.5 | JobController、JobControl、BuildJournal、OperationJournal；JOB_RECOVERY、PROCESS_OWNERSHIP_EVIDENCE、CURRENT_BUILD_RECOVERY_EVIDENCE | 状态/租约/暂停取消/迟到结果、任务树退出；不把状态字符串等同于成功 |
| 13.1(1–5)、13.2(1–8)、13.3–13.4 | BuildService、BuildJournal、PatchService；BUILD_RESUME_CONTRACT、PATCH_CONTRACT、CURRENT_BUILD_RECOVERY_EVIDENCE | 冻结输入、检查点、staging发布/失败保留、完成标记恢复、源hash绑定补丁；runtime字段保持真实 |
| 14.1(1–7)、G01 | StevProjectBridge/Worker/Codec；STEV_PROJECT_EVIDENCE | 真实ReadGame/ProgramData/InjectGame、独立完整副本、声明输出与副作用审计；歧义只发现 |
| 14.2(1–7)、G02 | RpgmtlCommonMapper、RpgmtlJsMapping、BackendJsWriter；RPGMTL_COMMON_EVIDENCE、RPGMTL_JS_EVIDENCE | 固定项目上下文、同文不同译、指定JSON/JS；明确不支持项不获得写能力 |
| 14.3(1–7)、G03 | SExtractorMainBridge/Worker；SEXTRACTOR_MAIN_EVIDENCE | 真实main_extract、独立新进程、sidecar/配置hash、MZ指定文件往返；无任意正则改全游戏 |
| 14.4各桥接要求、H01 | TranslatorPlusPlusClient、TranslatorPlusPlusBridge；TRANSLATORPP_EVIDENCE | 官方8.8.9已独立安装和实际API往返；本轮读取安装package.json仍为8.8.9，没有重跑API；不是任意T++版本或其原生导出全部通过 |
| 14.5 | BACKEND_WRITE_CONTRACT、各后端具体证据、BACKEND_COMPARISON_EVIDENCE | 固定版本、映射、往返、冲突、取消、来源/输出审计逐后端；进程隔离不称OS安全沙箱 |
| 15.1(1–5)、15.2–15.3 | FontService/FontInspector及profile布局约束；FONT_COVERAGE_EVIDENCE、FONT_LAYOUT_EVIDENCE、SCOPE_ACCEPTANCE_0.36 | 实际输出字形、已知窗口测量、项目字体与副本加载；11px装饰标题按原文/英文SOP，不宣称中文布局通过 |
| 16.1、17.3(9–10)、F02 | FULL_OUTPUT_RUNTIME_EVIDENCE、F02_UI_BATTLE_EVIDENCE、NATURAL_INPUT_EVIDENCE | 原装Game.exe列明路径；受控入口与自然导航/物理输入分列，不要求虚构全剧情通过 |
| 16.2、G06 | RuntimeCapture；RUNTIME_CAPTURE_EVIDENCE、FULL_OUTPUT_RUNTIME_EVIDENCE | 采集去重/限频/关闭/来源关联，未触发路径不纳入覆盖 |
| 16.3(1–7)、H02 | ImageService/Codec、OCR与人工图像复核；IMAGE_EVIDENCE | 声明的PNG/MV/MZ格式、3标题6区域、尺寸/alpha/引用/输出；复杂背景和所有游戏图片不继承通过 |
| 17.2各验证领域 | 相关现有专项及各阶段回执 | 按用户新约束选择实际受影响检查；本轮71项，不新增或反复全量套件 |
| 17.3(1–8,11–12) | 当前工程/输出独立清单、CURRENT_BUILD_RECOVERY_EVIDENCE、各版CURRENT_SOURCE_CHECK | 控制与结构、资源hash、缺字0和恢复；完整P0/profile正式验收仍未关闭 |
| 17.4–17.5 | ValidationService、GameProjectService.summary、STORE_PREPARATION_EVIDENCE、COMPACT_UI_EVIDENCE、0.38 EXTRACTED_PACKAGE_CHECK | 分子分母/过滤口径、实际GUI和提交指标；目标值不自动变成已测全环境性能 |
| 18–19 | IMPLEMENTATION_STATUS与逐版回执 | 34任务统计是索引；本表开放条款及直接失败优先，不能据统计关闭全目标 |
| 20.1(1–6)、20.2 | MigrationService；MIGRATION_V2_EVIDENCE、LINEAGE_CONTRACT、MIGRATION_REVIEW_EVIDENCE、MIGRATION_RECOVERY_EVIDENCE | 新工程、唯一映射/结构和token签名、CAS/锁、模糊候选不自动应用、DB backup；其他真实发行版本用户后置 |
| 21.1–21.3 | build_rpg.ps1、audit_rpg_package.py、rpg_pipeline.py、0.38交付目录 | 软件/源码ZIP与7项摘要、固定依赖和许可证；实际CLI参数以--help为准，原文命令块保留设计基线 |
| 22–24、迭代约束 | USER_GUIDE、THIRD_PARTY_NOTICES、PORTABLE_SCOPE、各证据与用户约束 | 不新增分布式平台/清理框架、不批量删除、不发布私有素材/凭据；SOP可处理的限制不扩张技术承诺 |

本轮没有因审计增加全游戏构建。三项源代码/职责开放核对已有直接证据和明确实现
决定。0.39已封存，实际来宾诊断和独立干净Windows验收亦已完成；旧失败、旧
准备包和本轮成功分列。只读复核当前18659/989确定性问题0，520条为历史记录。
完整profile的§17.3.12判定、真实翻译质量与用户后置H03仍不由组件统计代替；
99项来源SOP并非任意动态别名/eval/存档状态下的不可达证明，不抹去这些边界。
