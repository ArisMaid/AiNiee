# 游戏全文分析接入记录（0.25 源码）

2026-10-20，Codex。对应 A03、D02 与计划 §11。最新已封存程序仍为0.24-c04e572；
本记录是后续源码增量，不借用0.24的861项/207子测试或28组EXE结果扩大声明。

## 实现与产品约定

复用 AnalysisTask 的两阶段提取、合并和至多两次响应尝试。游戏模式在界面排队前
预留现有 GameTaskCoordinator 的 analysis 执行；开始、进度、停止、完成均携带
工程/root/dataset/执行身份。实际分析登记一个 ANALYSIS job 和租约，等待接口时
不持工程写锁；未启动future可取消，全部在途收尾后才发送一次完成并释放界面。

原文直接取规范SQLite单元，按文件和token预算组块。分析用于建立整个工程的术语
候选，不按每个短场景增加模型请求。角色使用接口管理中的 extract 绑定。
分析结果是建议；是否加入应用词典由用户确认，不自动改写接受译文或应用词典。

候选保存在元数据 analysis_result，含独立revision、dataset及来源job；人工编辑与
模型保存共用版本比较。模型完成和候选保存为一次事务，人工修改使旧结果冲突。
首次保存声明既有能力机制中的 analysis_metadata_v1，旧构建不接受未知能力。
投影重建恢复有效候选；来源dataset变化时旧候选留在记录中，当前视图不继续采用。

全文分析取消、失败或进程退出后，用户重新执行；已保存候选保留，不实现阶段断点
恢复或多层重试框架。应用词典是应用级设置，不随切换游戏自动隔离；不同游戏通过
现有词典导入/导出管理。在运行汉化任务时，避免同时修改词典或启动接口测试。
这些约定由使用说明明确，不另造工程词典同步或全局联网调度系统。

## 已运行的验证

- 用户追加迭代约束之前写入的17项必要存储检查通过：并发CAS、人工版本/来源变化、
  实际job身份、完成与元数据同事务、SQL故障回滚、幂等重放、投影与译文保全。
  日志 work/acceptance/rpg-analysis-store-green.log，保留目录
  work/acceptance/pytest-retained/7eacf790a34b4c84a23f0dc7874dbee3。
- 追加约束之后未再新增单元/回归测试，也未重复跑全套；使用实际Qt源码流程冒烟。
  真实 AnalysisPage.start_analysis → TaskExecutor → 两阶段AnalysisTask → SQLite →
  AnalysisPage.on_analysis_task_done走通；一个本地提取请求、一个本地合并请求，
  一个COMPLETED实际job。候选重建保持，外工程Start/Done拒绝。
- 同一流程另验证取消排队并等待一个在途请求，旧候选/接受译文保持；接口两次失败
  保留旧结果；在途人工改候选后旧模型保存拒绝，保留人工文本和revision。
  证据 work/analysis-flow-v25/b3f143d68b12491394604cbde10d5861/result.json，
  日志 work/acceptance/rpg-analysis-source-smoke-v25-final.log。

冒烟使用实际Qt对象、离屏平台和本地请求桩，不是自然点击、真实模型或冻结EXE验收。
前两次私有驱动停在QApplication准备阶段，未创建工程/发起请求；现场与栈保留。
补用程序已有QtBootstrap（中文路径插件/字体初始化）后通过，没有给产品新增超时
重启或恢复兜底。第三、第四次成功记录也保留，最终证据以上述最终驱动为准。

0.25运行源码94de3b9的新EXE及全新ZIP解压后的EXE已通过同一实际Qt流程。核对
GameAnalysisExecution、TaskExecutor、AnalysisPage、ProjectStore等均来自包内路径；
两阶段本地请求、实际ANALYSIS job/候选事务、外工程拒绝、取消等待在途、失败保留
与人工修改优先通过。通过可信且故意失败的私有SDK导入钩子运行包内实际方法，
不等于自然点击或真实provider。全新解压证据位于交付目录EXTRACTED_PACKAGE_CHECK.json，
最终说明见DELIVERY_RECEIPT_0.25.md。没有重复整套回归或新增单元测试。

当前游戏的真实DeepSeek全文分析、语言质量尚未验收；不据此声明整个游戏翻译或
完整开发计划完成。
