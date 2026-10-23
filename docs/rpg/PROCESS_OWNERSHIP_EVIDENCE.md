# 外部 worker 进程树控制验收

日期：2026-10-18。0.8 源码验收；便携交付另行登记。

Windows 10+ 的 JSON/JS 兼容后端和本地 OCR 统一经过 OwnedProcess。
WindowsProcess 使用 JOB_LIST 在创建时绑定独占 Job，主线程暂停创建，完成管道与
归属检查后才恢复；仅继承三个明确的标准输入/输出句柄。拥有者退出时 Job 关闭并
结束成员，正常返回也清理残留后代，避免根进程先退出、孙进程继续持有管道。
不按名称扫描或结束进程，不以保存的 PID 找回并终止进程。

输入使用完整写入循环，两条输出管道同时排空并各自限制累计字节；超时和取消
先向受控 worker 发送绑定 request_id/job_id 的取消帧，短暂等待后结束独占 Job。
不支持取消协议的 OCR 仍受同一进程树和时间边界约束。调用者的原始取消异常保留。
暂停在当前文件或识别单元完成后、提交结果前确认，运行中的 worker 仍受原超时约束。

Python 请求和取消共用 ProtocolInput 缓冲，支持两个帧在一次 OS 读取中到达。
控制线程使用 PeekNamedPipe 检查后只读取已到达字节，避免本机 CPython/NumPy 在
另一线程阻塞读取 stdin 时导入挂起。第三方 stdin 置为空，不与协议读取竞争。
这是已测试的规避方案；尚未证明 NumPy 内部的精确根因。参见
[Microsoft PeekNamedPipe 文档](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-peeknamedpipe)。
协议拒绝重复键、非有限数值、错误身份、错误版本、非法 UTF-8 和额外响应帧。
原有非 Windows 源码调用保留旧单次协议；Windows 所有权失败不降级启动。

## 已通过的源码检查

首轮独立专项：26 passed / 18 subtests，证据
`work/acceptance/rpg-0.8-pipe-focused.xml`。包括：

- 实际 Windows 子进程的 Unicode 参数、二进制管道、显式环境和无关可继承句柄隔离。
- 恢复线程前父进程退出、根进程退出后仍存活的后代、ResumeThread 后故障及句柄转移失败。
- 真正的超时/取消、输出溢出、双管道排空及 I/O 线程结束。
- Python/Node 取消确认、同批到达的帧、错误任务拒绝及分段 UTF-8。
- 保持控制管道打开时实际导入 NumPy；真实固定 Stev、RPGMTL、SExtractor 提取。
- 实际 Node 解析的 Unicode 区间和最小环境，含父进程预加载/提供商配置排除。

单次 OCR / 后端候选新增持久化任务和提交边界，OCR GUI 有暂停/继续/取消。
第二组专项 26 passed / 7 subtests，包含真实兼容后端回写/构建、OCR Qt 控件控制、
单次任务的失败/锁释放、真实 owned 进程取消、COMMITTING 拒绝迟到取消、
以及候选生成期间 SQLite 提交新译文后拒绝过期候选。证据
`work/acceptance/rpg-0.8-external-focused.xml`。源码完整回归（含安装版 T++）
230 passed / 196 subtests，证据 `work/acceptance/rpg-0.8-final.xml`。

当前游戏只读重提取 17706 单元 / 18254 occurrence，ID、来源 hash 和位置完全相同；
JSON 单元 17564、JS 单元 136、确认图片单元 6（重新检查来源 hash）。原有 27 条
接受译文保留，9570 个原游戏文件集合与 SHA-256 一致，原工程 DB SHA-256 为
`3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935`，前后相同。
驱动首轮遗漏服务原有的三条 actor 引用排除规则，导致多出三条；修正驱动后通过，
未改变产品规则。私有结果位于 `work/process-current-game/d481cbf8d81e4a8694c5837c2c7c12e5`。

新便携 EXE 验收已完成，详见 DELIVERY_0_8_RECEIPT.md；四组真实进程树故障通过。
源码与冻结验收记录分别保留。真实翻译由用户决定后续交给 DeepSeek，当前无翻译请求。
中断的单次任务保留记录，重新运行会建立新尝试，不宣称中途恢复 OCR 的内部计算。

## DeepSeek 分工与交接状态

使用 deepseek-worker 本机 Skill 工作流；
实际 Skill 路径记录在私有任务清单，不向公开文档附带用户目录。
DeepSeek 提供 WindowsJob、WindowsProcess、ProtocolInput 初稿；Codex 负责原生契约、
审查修复、调用链与 GUI 集成、故障注入、独立测试及交付。

WindowsJob 交接完成；WindowsProcess 初稿运行超时，按失败交接保留，Codex 审查后
修复启动回滚和关闭超时行为。ProtocolInput 交接快照判为 policy_violation：Codex
在 worker 运行期间修改了受保护的接入/测试文件，触发前后快照检查；guard 无拒绝，
工具日志仅显示 worker 写了获准模块。这是 Codex 编排错误，仍按失败交接记录。
未放宽 guard，也未回滚或删除文件。后续任务在启动前固定受保护文件。

DeepSeek 后续实现 ExternalTask 单次任务编排，155 秒完成，guard 无拒绝、受保护
文件无变化；Codex 审查时修正 on_job 回调为项目现有的单 dict 参数，再进行上述
独立测试。所有 worker 保持 Flash/max，未设置 maxTokens，实际观察窗口打开。

这些交接结果均不等于验收完成。独立测试结果与冻结交付结果分别记录。
