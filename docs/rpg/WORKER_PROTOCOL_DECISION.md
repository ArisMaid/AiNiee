# 一次性worker与父作业的职责

2026-10-22，Codex核对原计划12.4。按用户2026-10-20的迭代约束，继续采用现有
一次请求的worker，不为基线提案中的每个事件名称另建一套流式状态系统。游戏工程
的恢复、问题归属与进度仍由父作业负责；原计划的产品职责保留，消息形式有差异。

Windows协议实际只有request、result、cancel三种帧，均校验protocol_version、
request_id、job_id、键集合、UTF-8/重复键与大小；结果必须是一行完整JSON。
每次调用有新request_id，工作进程通过worker_control绑定当前持久作业job_id。
不是面向第三方客户端承诺原拟ready/progress等消息类型的协议兼容实现。

| 原拟职责 | 当前实现 | 直接核对位置 |
| --- | --- | --- |
| ready | 父进程同步完成所属进程树、管道和启动验证，之后发送唯一请求；没有独立ready帧 | WindowsProcess、OwnedProcess |
| progress | 父服务在文件/规则等工作边界更新持久job及Qt进度，worker内部没有虚构百分比 | ExtractionService._DocumentCache、BuildService、JobControl |
| unit/issue | 经过类型校验的结果负载返回单元/问题；父服务汇总、所有权检查并提交 | ExtractionService._packed/_unpacked、BackendWorker、JsBridge |
| checkpoint | 父OperationJournal/BuildJournal保存可复核结果和输入摘要；边界完成后记录进度 | ExtractionService、BuildService、JobControl.checkpoint |
| result/error | 绑定身份的result帧携带ok/value或error；非零退出、EOF、协议异常由父作业记失败 | WorkerProtocol.response、JsBridge._call、各后端桥接 |
| cancel/cancelled | 请求对应的cancel帧；Node结果含cancelled/error，父进程有限等待后只结束自己的Job树；父JobControl确认取消 | worker.cjs、OwnedProcess.run、JobControl |
| attempt_id | 不重复放入短命worker帧。恢复保留旧job，新job携带resume_from；构建另有BuildJournal attempts，每次子调用仍有唯一request_id | ExtractionService、BuildJournal、WorkerProtocol.request |

标准输出只承载协议；普通日志与错误输出有独立限制。参数数组、明确cwd/环境、
超时/取消、独占Windows Job及禁止按进程名结束的边界保持。父进度不代表worker
内部每一步都能中断，暂停按已声明边界生效；提供商请求的取消限制另按SOP提示。

本轮核对当前调用链和既有真实进程专项结果：0.8管道/进程树26项及18子项的原始
XML保留；WorkerProtocol.py与OwnedProcess.py自e22f87c以来未变。其后冻结包
self-check仍实际调用绑定身份的Node解析。没有为文档复核再跑全部故障注入或新增
套件；不能把静态职责表单独称作新的真实进程验收。

该实现决定取代基线12.4的消息类型枚举形式，不取代状态、身份、取消、隔离或恢复
要求。当前短任务协议若以后需要流式事件，再按实际需求扩展并单独验收。
