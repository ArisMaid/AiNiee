# 0.22 源码：人工编辑译文与锁的原子提交

2026-10-19，Codex 审查与独立验收。以下为源码证据；实际便携 EXE 与交付状态另验。
工程格式2、写入计划v7保持。原0.21封存不改写，也不将旧回归结果当作此缺陷不存在的证明。

## 已复现的问题

原 GameProjectPage._GameProjectJob._commit_unit 为修改锁定译文，会分别提交解锁、
译文及重新上锁三个事务。在实际自有子进程中，于 UPDATE translations SET text 触发
SQLite trace 时退出77，重开数据库后原译文仍在，但 manual_locked 已变为 false。
无效控制符提案也曾临时改锁，改变 updated_at 和 content_revision 后再恢复锁值。

首轮独立4项中3失败、1项锁定元数据对照通过。原失败目录与stdout/stderr均保留，
没有通过取消异常退出场景或只比较文本来消除失败。

## 实现边界

- 新 TranslationCommitter.edit_manual(proposal, locked=bool) 仅供明确的用户编辑命令。
  locked 必须是精确bool，None不能静默转成普通提交通道。Store仍验证 origin=manual。
- ProjectStore.commit 新增 keyword-only manual_lock；普通 submit、导入、OpenCC、
  模型和迁移不传该参数，原有人工锁阻断保持。
- 源 hash、revision、单元状态、schema/capabilities、当前TokenPolicy和显示值约束在
  BEGIN IMMEDIATE 后复核；接受文本、目标锁、revision、proposal、edit和content_revision
  在同一事务提交。没有先提交解锁、嵌套事务或第二连接补锁。
- 同文且已接受来源有效时，仅改变锁元数据，不增加文本revision或accepted edit。
  旧stale译文同文确认必须重新校验、产生新revision。无译文的空行可只锁定为rev0占位。
- 元数据锁命令不把空白未译值当成新翻译检查；显式传入的阻断issue仍拒绝并保留审计。
  译文改变时的控制符/空译文规则没有因此放宽。
- GUI保留工程锁和版本输入，调用新的提交器命令；拒绝/冲突返回changed=false，
  锁元数据操作保留results=[]。异常或进程退出由SQLite回滚，同时保留原文本和锁。

## 独立验收

保护测试 test_manual_edit_atomic_lock.py 的4项覆盖真实退出77、一次事务接受、拒绝后
整行和content_revision保持、同文锁元数据操作。新增 transaction_guards 的11项覆盖
严格bool、普通manual/model仍不能越锁、空未译行锁、stale同文重批、来源/revision冲突、
审计插入故障回滚和显式阻断issue。保留原版对照及失败日志。

首次交接后48项/9子检查通过。Codex再补测发现：None未拒绝；空行锁返回错误控制符
问题；元数据分支忽略显式阻断issue。分别保留3失败/7通过和单项失败现场，修正后
包含原有存储、模型、作业、GUI及场景组共59 passed /9 subtests passed。
没有因测试通过而声明真实模型、自然游玩、完整计划或P0完成。

源码回归中的进程退出使用独占owned子进程及临时数据库，不针对原游戏或主工程。
当前游戏主库只读场景核验另见 SCENE_BATCH_EVIDENCE.md。

## 协作记录

使用deepseek-worker，无窗口；2400秒上限，513.64秒返回completed、verified:false。
只修改授权3文件，46次工具调用，零guard拒绝、保护文件变化或协议错误；Codex独立
核对15个after hash，再审查、补测和修复。任务没有读取游戏文本或凭据。
该交接成功不等同于验收成功；上面的独立证据才支持源码结论。

私有日志：work/acceptance/rpg-v22-manual-lock-red.*、rpg-v22-atomic-owner-red.*、
rpg-v22-atomic-provided-issue-red.*、rpg-v22-atomic-green.*；最终定向临时目录
work/acceptance/pytest-retained/b65dff6968b745cca2930c710e561cfc。
冻结程序、完整源码回归和封包结果须以0.22交付回执为准。

## 最终源码检查

完整源码548 passed /207 subtests passed，含安装版Translator++8.8.9；一条既有依赖弃用
警告，零skip/fail/error。首次完整回归的旧fixture将所有文件混成一批，在场景守卫前置
失败；修正为真实分批、保留所有原目标并对每批验证dataset变化不得到供应商，18项专项
通过，再完整重跑通过。原失败与临时目录保留，没有放宽产品守卫。

新增实际应用进程驱动的五组人工命令及独立退出77场景也通过，所属PID50764确认已退出，
原译文/revision/时间戳/锁和触发工程译文/来源保持。它通过私有、可信且故意失败的SDK导入
钩子调用实际应用模块与GUI命令方法，不代表普通按钮点击或成功后端回写。源码模式使用
真实本机模块，包内模块路径还须在冻结程序复验。
驱动前两次因生成字符串丢失反斜杠，实际没有建立控制符负例，现场保留；修正构造后通过，
没有将其错误归因为产品或修改产品检查。证据work/frozen-manual-edit-v22/e7e71fc809b7403cbb85bb19b4526365。
