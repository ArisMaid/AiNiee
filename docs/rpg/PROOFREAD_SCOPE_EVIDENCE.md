# 0.24 原生游戏 AI 自动校对

日期：2026-10-20。Codex独立实现、审查与验收。补充A03/D02/D04入口，不改变完整
计划及真实模型/自然玩法的验收条件；最新已封存便携包仍是0.23。

## 请求及提交

问题表排队前预留table-proofread scope，捕获建表投影及规范dataset，共用主/表格的
停止控制、真实job登记和一次组终结。只处理译文，来源字段保留并提示。UI只传路径/
索引及最多500字的问题提示，原文和当前译文来自SQLite。TaskExecutor先接收预留再
创建线程；普通文档仍用ProofreadTask，带游戏身份的消息拒绝进入旧worker。

每单元单独请求，共享一次工程准备/限流并保留配置并发数。配置初始化及取平台均指定
proofread角色。输入有规范原文、有效接受译文及规范诊断，UI提示不具有写入权限。
缺失、陈旧或无效当前译文为null，允许从当前来源重译；手工锁排除，未知来源控制符
在请求前拒绝。有效当前译文按已验证的token顺序映射到同一套源marker，避免两次
protect随机前缀不同。返回为精确单元ID的JSON映射，沿用恢复、源hash/CAS、锁、
策略、dataset及逐条SQL writer守卫。

校对属于现有POLISH操作，payload明确request_mode=proofread，绑定时核验模式；
接受origin=polish，重建投影显示POLISHED。未新增schema或伪造job_id。跳过/空响应、
格式/ID错误和被拒绝的译文至多尝试两次，每次有独立真实job/lease。重试固定原输入、
保护和期望revision；CAS/锁/dataset或策略变化不重试。原响应与拒绝提案保留，已接受
结果不重复请求。统计累加尝试及token，未启动即取消的future不计请求。停止等待迟到
响应收尾但不接受它，然后发一次校对组完成及一次终结。

## 证据及范围

- 两个初始反例证明未提供原生校对路径、无scope游戏消息会启动普通worker。修正
  初次Mock锁fixture后仍复现两项失败，全部现场保留。
- test_game_proofread.py新增25项，覆盖规范与伪造单元格、已有/缺失译文、角色、六种
  有限重试、marker与统计、人工修改/锁/dataset拒绝、固定CAS重试、两次失败保全、
  排队/在途取消、真实Qt生产者、来源保持、普通文档兼容、受损身份及开始/停止。
  排队fixture曾同步执行线程池worker而滞留，经确认该测试进程退出后改为恢复真实
  Thread再调用目标，没有改产品迁就替身。
- 确定性取消统计反例先失败：一个真实在途请求加一个取消future旧计数2，修复后1。
  新用例及相关主/表格/身份/SQL链路联合170 passed，既有scipy/qfluent警告1。
- 当前17716单元主工程经SQLite backup保留副本，两文件/两屏障并发本地模拟请求、
  两个POLISH job带proofread模式且COMPLETED、两行接受、一次终结通过。选中一个
  已有译文和一个未译单元；其余28条旧译文、完整图/文件及dataset保持。主库SHA保持
  3343edfef58d1b3037909afaf9f98bb55771d41f6483e3c6d14876c37638dae5。
- 最终完整源码861 passed /207 subtests passed，含安装版T++8.8.9，零skip/fail/error、
  既有警告1，208.68秒。实际源码应用进程再通过四组主入场/实际Qt校对重试与消费/
  排队和在途取消/每条SQL事务dataset边界；可信且故意失败的私有SDK钩子调用实际
  模块，本地模拟响应，不是正常后端成功或自然按钮验收。新EXE分别验证。原始私有证据在
  work/acceptance/rpg-proofread-v24-*与work/current-proofread-v24，不进入交付包。

没有真实provider、游戏启动、原游戏/主库写入、SDK修改或批量删除。Qt对象/槽及本地
请求不等于自然按钮、模型语义质量、新EXE或干净机器验收。
