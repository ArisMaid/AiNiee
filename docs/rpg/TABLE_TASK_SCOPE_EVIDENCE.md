# 0.24 表格选区作为一个执行组

日期：2026-10-20。Codex 独立实现、审查与验收。完整开发计划继续执行，A03/D02仍
部分实现；本记录不替代真实模型、自然界面操作、自然玩法或新的冻结程序验收。

## 实现

BasicTablePage、SearchResultPage、EditableIssueTablePage 保存建表时的投影对象。
游戏选区在排队前预留 ui_owned 的 table-translate/table-polish scope，并同步占用
TABLE_TASK。搜索和问题表的多个文件只发一条 file_tasks 消息；没有可用行不占用状态。
消息仅复制路径及 text_index，界面中编辑过的原文/译文不会成为请求来源。

SimpleExecutor 在创建线程前接收预留并核验工程、执行、角色及规范 dataset。没有身份、
旧执行或其他工程的开始消息拒绝，不按当前工程重新解释。运行函数保留直接服务入口，
自行预留独立 scope。配置或线程创建失败、空选区及正常/取消尾部均结清自己的执行。

GameTableExecution 先验证全部文件和索引、去重，再按原文件顺序和连续场景边界准备批次。
整个组选区共享一次 GameBatchPreparation 与限流器，保持 actual_thread_counts 配置的
请求并发数。每批创建实际持久 job 后登记到同一协调器，结清后移出活动集合；主控制器
停止/退出可取消该组的排队 future 和活动 job。等待在途请求及 lease 收尾后才终结组，
不以某个文件先完成释放全局状态。

并发验收发现同组短事务竞争非阻塞工程锁；现由 preparation 内存锁仅串行化创建 job 和
接受响应的短临界区。provider 调用在锁外，并发保留。独立工程操作仍面对原有 OS 锁，
没有将它改成可重入或放宽跨进程保护。排队 future 的取消使用有界 wait/done 检查，避免
shutdown(cancel_futures=True) 后等待取消通知的路径滞留。

计数按每批实际结果累加；check_result=False 或异常均上报失败，空异常信息保留异常
类型，部分已接受行保持。最后发每文件的规范回读更新和完成通知、一次组 TASK_STOP_DONE。
主 BottomCommandBar 接表格开始以显示停止控制，消费本组 Done 后恢复闲置。监控接表格
状态及快照序号，终结前已排队的有效指标仍可显示。同一 scope 开始前就收到停止时也能
消费开始并结清；不会再次接收重复开始。

三个实际表格消费者在碰单元格、缓存或提示前核对建表投影及当前 scope。更换投影、旧
执行、错误 root/id/dataset 的消息拒绝。UI仍通过 CacheManager 做规范回读，不能凭消息
写入接受文本；状态类型及 POLISHED 优先守卫继续生效。普通文档保留原有入口。

## 证据

- 保留 a36af2b 的实际生产方法，在纠正测试中第二文件的全局 text_index 后复核：一个
  跨文件执行组和三个过期消费用例均失败；修复后通过。原错误 fixture、失败日志均保留。
- 新 test_game_table_group.py 包含两请求屏障的真实并发、一次准备/真实 job 关联、排队
  取消与在途等待、部分失败保全、缺/错身份开始拒绝、预留后停止、共享停止控制、三个
  实际 Qt 表格的选区生产和有效/旧消息消费。联合相关链路122 passed，既有警告1。
  完整回归发现直接服务预留覆盖既有STOPING，已在预留前保留取消语义；原失败保留，
  含原取消检查的122项再次通过，最终完整门槛另验。
- Qt 检查仅调用实际对象与槽；修正 fixture 的状态枚举及 QApplication 进程生命周期后
  通过，没有将 fixture 错误归因于产品，也没有把此项称作原生用户点击验收。
- 当前17716单元主工程通过 SQLite backup 生成新保留副本：两文件、两本地模拟请求在
  屏障同时到达、两个持久 job COMPLETED、两行提交、一次组终结；29条既有译文、完整
  units/文件表（含 occurrence 数据）与dataset保持。原主库SHA-256保持
  3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。
- 最新实际源码 offscreen 应用加载17716行、按钮可见、进程退出0、最大心跳195.8751ms，
  原主库保持。此检查为工程视图加载，未测量开始翻译时的自然交互延迟。
- 最终完整源码836 passed /207 subtests passed，含安装版T++8.8.9，零skip/fail/error、
  既有警告1，201.00秒。前次835 passed/1 failed保留，未以其冒充最终通过。私有原始证据在
  work/acceptance/rpg-table-group-v24-*、work/current-table-scope-v24、work/scope-gui-v24。

本轮没有真实 provider 请求、游戏启动、第三方 SDK 修改、原游戏或主库写入及删除。
0.24 EXE尚未生成；最后封存的可用便携包仍是0.23-2e7a4f1。

后续将本次主/表格协议纳入实际新EXE检查，更新打包文档/白名单并新建发行目录，不改
既有封存包。AI自动校对等剩余写入/控制入口继续逐项复核，完整A03及P0不据此宣告通过。
