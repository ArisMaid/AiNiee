# D05 迁移任务控制与恢复

2026-10-17，代码和源码验收。便携包是否通过需另看相应交付回执。

## 实现

`MigrationExecution.run_review` 负责已注册对账的执行。初次应用核对完整双侧绑定，冻结
两侧身份、数据集、规则、策略和来源；来源同时绑定 content_revision。每次尝试生成
新的 MIGRATE job_id、独立 OS JobLease，保留旧尝试。两工程 ProjectLock 按路径排序。
旧库使用只读 SQLite backup，包含活动 WAL；拷贝有 30 秒限时。

检查点直接使用目标库中原子提交的 accepted proposal：其译文、修订、edit 和全局
版本在同一事务保存。稳定投递命名空间为 `migration-review:<plan_id>`，和执行尝试
job_id 分开。恢复模块核对提案是原计划的连续前缀，逐项验证 old/new ID、原文 hash、
译文、预期修订、实际修订、语言、origin、投递键及元数据；拒绝缺口、重排和拒绝记录。
对应纯函数契约为 MIGRATION_RECEIPTS_CONTRACT.md。

进度 checkpoint 是界面提示；accepted 提案是恢复依据。因此进程在提交后、更新进度
之前退出时，恢复也不会再次应用已提交译文。已提交条目后来发生人工编辑或锁定时，
保留目标当前值。报告中的 accepted/results 表示历史提交，当前译文状态从数据库查询。
未提交条目全部重新运行原有匹配、令牌、值约束、revision 和人工锁 preflight；任一
条目变化，剩余条目均不写入。两侧工程目录、来源版本、目标数据集或策略变化须重做对账。

任务在逐项提交之间协作暂停/取消；结果发布前进入 COMMITTING。结果报告使用新的
UUID 文件，不覆盖失败报告；对账 registry 的 applied 状态和 job COMPLETED 同一
SQLite 事务发布。取消或失败保留已提交译文、提案、冻结输入和所有产物。

## 入口

- GUI“迁移旧译文”：暂停、继续、取消、恢复未完成迁移；运行时关闭受控，部分提交
  后失败也会通知父页面刷新。恢复时重新加载原对账快照供查看。
- `migration-apply-review --project PROJECT --plan-id ID`。
- `resume-migration --project PROJECT --job-id ID`。
- 原有 `migrate --apply` 也生成注册对账并进入同一任务链；不再绕过任务控制。
- 同一次活跃尝试使用 `job-control` 的 pause/resume/cancel；退出后恢复会建立新尝试。

## 独立测试

新增纯记录校验、恢复和真实 Qt 控件验收，覆盖：

- 进度仍为 0 时取消，但已提交 1 条；恢复复用它，后来的人工改稿和锁保持。
- 未提交条目编辑/锁定、来源修订、目标 profile 变化、计划/输入损坏和提案损坏拒绝。
- 暂停期间没有新增提交，继续沿用同一尝试；取消后保留旧尝试，新尝试才完成。
- 实际 Python 子进程 `os._exit(41)` 在提交后、checkpoint 前退出，再从 CLI 恢复。
- `os._exit(42)` 在原子发布后退出，COMPLETED/registry 均已提交，拒绝重复应用。
- SQLite trigger 注入结果发布失败：registry 和 COMPLETED 同时回滚，恢复复用所有提案。
- 实际 Qt 按钮完成暂停、继续、取消及从已注册计划恢复，运行期间不能销毁线程。

最终完整源码回归：202 passed / 178 subtests，包含实际 Translator++ 8.8.9 本地 API。
XML：`work/acceptance/rpg-0.7-final.xml`。

当前游戏的独立数据库图副本：17706 单元、9570 条来源文件记录、27 条可靠匹配。
第 8 条原子提交后暂停，此时进度为 7；取消后恢复复用 8 条、新增 19 条，最终只有
27 条迁移提案。完成条目的人工锁保持；旧 profile4 数据库 SHA-256 仍为
`3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935`。
程序驱动真实 Qt 控件并检查暂停/恢复截图；这不是人工物理桌面验收。
没有复制素材或验证该数据库副本可构建，没有第二款游戏/其他实际版本，也未调用模型。
证据：`work/migration-recovery-current-acceptance.json`，完整测试 XML 在 work/acceptance。

## DeepSeek 交接与边界

DeepSeek 生成纯记录重建模块初稿。首两次未找到凭据，没有模型调用或修改；定位到新版
Harness headless 默认禁用 credentials 后，启动器显式启用已配置的凭据插件。没有读取、
复制或打印密钥。实际模型任务尝试 working_directory 和目录 grep，被 guard 拒绝；
因此交接记录为 policy_violation，不能按 worker completed 验收。

原始稿和失败记录保留。Codex 检查 guard 日志、写入范围、所有绑定逻辑后，独立编写
测试并集成；保护文件未变。Codex 完成任务控制、事务、CLI、GUI、故障注入与交付。
不会把该失败交接描述为成功交付，也没有放宽 guard。

旧版没有冻结输入的迁移不支持原地续跑，需要新对账。此功能不补齐外部第三方工具
完整进程树超时控制、其余插件规则、自然游戏路径、真实翻译接口或多游戏验收。
