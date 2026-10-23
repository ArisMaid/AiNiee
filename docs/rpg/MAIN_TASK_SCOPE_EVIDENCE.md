# 0.24 主任务执行身份与逐行提交证据

日期：2026-10-20。实现、审查、复现和验收均由 Codex 完成；没有新增 worker。
范围是主翻译/校润、其控制消息、监控、继续检查和真实原生请求的持久 job 关联。
完整 A01–H03 目标保持 active，A03、D02 仍部分实现。表格多文件组的完整协议尚待接入。

## 执行与请求的关系

- BottomCommandBar 在发送排队 Start 前预留工程内存 scope 并同步占用任务状态。
  scope 包含原投影对象、root、project_id、dataset_revision 和每次执行独立 UUID；
  UUID 不冒充数据库 job_id。继续任务也做平台/校润前置检查。
- CacheManager 先过滤 Start，游戏继续不使用普通缓存保存后重载路径，避免更换捕获的
  投影。普通文档保持原行为；定时保存线程去重。支持的载入入口在任务或待消费 Done
  期间拒绝接管，最后一步与预留共用协调器锁。
- TaskExecutor 在创建线程、初始化平台和请求前接收同一预留，核对规范数据库身份/
  dataset。直接服务入口仍支持自行预留；UI 入口不接受无身份的降级执行。异常和线程
  启动失败只终结自己的执行。后台完成先终结协调器，随后发送携带身份的 Done。
- UI 所有的执行要等实际 Done 消费后才能再次预留或接管投影；Done 仅消费一次。
  自己的失败 Done 可解除自己占用的界面，但损坏投影仍被标记为必须重载。
- TranslatorTask/PolisherTask 将 scope 传给 GameBatchRunner。Runner 创建真实数据库
  job 与 lease 后才登记，payload 保存身份、dataset、目标 IDs；请求结束后释放活动
  job 记录，保留本执行的实际 job 历史以核验结果。停止后登记竞态转成持久取消。
- 停止和退出只取消本执行的活动真实 job；主任务等待请求和 future 收尾后发终结，
  不再以旧 watcher 的迟到消息将新任务设为闲置。provider 客户端仍走关闭流程。

## 消费前核验

future callback 捕获原 scope 和统计对象；当前工程、执行及实际 job 不符时，在更改
统计或请求保存前拒绝。MonitoringPage 在更新任何卡片前核对同一上下文。延迟 Continue
检查通过 Qt object 信号到实际 UI 接收端后，再比较检查代次、投影对象、root/id/dataset、
重载标记、执行对象和闲置状态；游戏是否可继续按当前规范投影的角色状态计算。

并发复现证明：第一条回调在保存通知处暂停，第二条回调先显示完成 2 行，再释放第一条；
旧实现显示退回 1 行，尽管统计已为 2。修复以统计锁内捕获的 total_requests 作为
game_progress_revision；同执行较旧/重复/非精确非负整数的指标消息不更新任何卡片。
定时器的纯身份消息可以更新时间，新执行的定时消息先清除上次执行指标。

## 每条数据库写事务的独立守卫

另一个复现先接受批次第一条，再通过实际 Store 替换数据集，旧实现接受了旧批次第二条。
协作式工程锁不足以保护直接 Store 调用。现在 ProjectStore.commit 在每条 writer 事务内
复核真实 TRANSLATE/POLISH job 的 dataset、可选工程 ID、唯一目标 ID 列表、request_item_id、
角色和 COMMITTING 状态。冲突保留提案和 issue，不改接受文本、锁及内容版本。
已送达同一提案的精确重放仍幂等；手工编辑/独立未知投递键保留每单元来源与 CAS 语义。
该补充没有修改 schema2 或 rpg-build-atomic-stages-v7，也没有修改第三方 SDK。

## 可复核证据与边界

- 原 Start/Done 两个控制反例已原样移入 test_game_event_regressions.py，修复后通过。
- 数据集逐行写入反例：先 1 failed；后公共 test_game_dataset_writer.py 共 14 项通过，
  包括 SQL writer 等待后的新 epoch、坏 epoch/目标/角色/状态及幂等重放。
- 同执行进度排序反例：先 1 failed；修复后新公共排序用例、入场、请求、实际消费者和
  writer 联合 63 passed，既有 scipy/qfluent 警告 1。
- 真实 QApplication 队列 3 项通过：工作线程结果经 UI 接收端消费，投影/执行变化后丢弃。
- 实际源码应用的 offscreen --gui-check 成功：17716 行工程视图载入，进程退出 0、按钮
  可见，最大心跳间隔 165.1481 ms。原主库 SHA-256 保持
  3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。
  此检查发生于主接线阶段；后续进度排序和 writer 守卫由专项与最终源码门槛覆盖。
- 本轮完整源码最终门槛另记在 IMPLEMENTATION_STATUS.md；早先 810 项完整运行属于
  排序补充之前，不扩张为新代码验收。

私有原始日志、JUnit、失败现场及源码应用结果保留在 work/acceptance 和 work/scope-gui-v24。
没有批量删除，没有修改原游戏/主工程，没有真实 provider 请求、自然按钮流程或自然玩法。
最新验证便携包仍为 0.23-2e7a4f1；没有以源码检查冒充新的 0.24 EXE。

下一步保持配置并发度，将 Basic/Search/EditableIssue 表格多文件选区封成一个执行，
共享一次准备与限流、关联每条真实请求、停止全部活动/排队任务、只发一次组终结，并在
三个实际表格消费者更新或提示前过滤工程与执行身份。完成后再验新源码和新便携包。
