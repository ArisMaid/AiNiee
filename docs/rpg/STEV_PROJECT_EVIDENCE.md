# Stev 整目录入口与 ProgramData 验收

日期：2026-10-19，0.21.0-dev。默认 writer 仍为原生适配器；显式选择 Stev 的文件在
构建中使用真实 `Jr_Tpp.ReadGame → Jr_Tpp.InjectGame` 项目流程。原单文件候选和只读
比较仍使用独立内存 API，不把单文件成功视为整个游戏构建成功。新冻结程序结果以本版
交付回执为准。完整计划、P0、真实翻译和自然游玩未据此完成。

## 原计划 §14.1 对照

| 要求 | 实现和直接证据 |
| --- | --- |
| 固定 jtpp.py/config，记录补丁 | 固定 AiNiee 基线 7bbb06be33f5968f0723a5200a150d895d4fa5fb；捕获两文件 bytes/hash，路由纳入 config.yaml；实际编译已捕获 Python bytes，不信任匹配时间戳的 pyc |
| 完整游戏复制 work，GameDir 指 work | 按完整冻结清单逐文件独占复制，包括资产及被成品排除的日志/存档；当前游戏9570个输入文件逐项hash与原版一致；所有GameDir均为私有input或前轮输出 |
| 禁用清理/未声明修改/换行插件 | 实际目录API，不调用ToGame/FromGame、dnb、DNoteB、AutoLineFeed、插件安装、水印及表格导出；列表清理临时改为identity，length仅1；精确副作用guard和事后全树检查 |
| 转换ProgramData完整信息 | 保存真实原文、译文、原始合并地址、标签、code及实际LabelName标记；展开每个地址/code向量，并按源文件和完整叶验证pointer；名称标签不授予翻译权限 |
| 反向映射项目，只收声明输出 | 使用实际ProgramData地址，按同一文件/原文每轮最多一条分批；真实InjectGame输出全部登记，只有选定路由文件进入staging，仍须等于原生批准计划 |
| 审计整个工作副本 | 输入/上游前后hash、每轮完整目录/文件/大小/hash及typed语义；记录字节与语义变化，额外写入阻断；资产不写，原游戏/主库不改 |
| 去重丢上下文时保留occurrence | 同文不同译分轮，第三个未请求同文保留；合并长度、歧义、子串及无法证明的位置不写；重复JSON键文件只作发现、禁止获得可写定位 |

§14.5 的来源版本/依赖、位置、零变更/单条往返、重复/配置冲突、取消、来源保全和完整
差异均有对应证据。G01按指定MV/MZ JSON目录入口实现；不声称支持Stev所有交互菜单、
任意引擎、任意自定义字段或跨游戏自然流程。

## 执行边界

父进程 `StevProjectBridge` 接收明确文件表，将所有文件复制到新UUID的`pipeline/input`。
SDK接收私有case路径和清单，不接收原游戏根路径。项目worker使用统一owned进程树、
最小环境、framed协议及300秒执行上限；父进程复制/核验有合作式检查点，取消保留现场。
同一个Stev根/指纹的路由组成一次项目候选，不在每个文件上重复复制整个游戏。

worker真实读取整个目录并执行LabelName，保留初始ProgramData。每轮DataFrame只填
原始ProgramData中已证实的单独地址，index仍为原文；需要不同译文的同文放到不同轮，
下一轮读取前轮真实输出。空变更也执行一次真实目录注入。实际输出不由本地JSON writer修补。

上游固定配置捕获后，明确覆盖ja=False、ReadCode/sumcode/sptext和黑名单为空、
line_length=0、mark=0。这些值用于发现和保持事件结构；原生consumer/TokenPolicy/
WritePlan仍决定权限。配置安全读取复用锁定的PyYAML6.0.3；不运行需要ruamel的原交互main.py。
实际依赖包括Pandas、OpenPyXL、Chardet及PyYAML，均在现有锁中。

仅有两项临时兼容补丁并在finally恢复：声明JSON目标的UTF-8/BOM读写编码适配；禁用
`__del_marked_list`。原始输入完整bytes不改，返回实际上游文件bytes，SDK可改变JSON排版。
明确空译文会触发表格补原文的上游行为，因此该兼容入口拒绝空译文，不静默回填或导出XLSX。
真实列表中已有“☆删除☆”字符串会保留。

guard在依赖/SDK导入、ReadGame和InjectGame时拦截源文件写入、未列输出、删除/移动、
新目录、进程和socket；仅允许精确预建且仍为普通目录的mkdir既有路径尝试，以及Pandas
本机名读取。它针对审计过的固定SDK，不是OS安全沙箱。父子分别核验文件集合、reparse/
hardlink、来源、配置、ProgramData、各轮输出和完整类型保持语义。父进程不因报告hash正确
就信任批准内容；更改报告中的请求即使同步改hash也会被拒绝。

## 当前游戏的重复键资源表

完整目录预检发现BgmList/BgsList/BgvList/SeList分别11/5/23/16个重复键，共55个；它们
不在六个选定回写文件中。旧六文件内存回写验收没有覆盖该情况。原版所有bytes保持。

对这些未请求文件，读取模型匹配本机MZ JSON.parse的最后键值语义，保留完整重复位置清单。
四个真实来源另由本机Node JSON.parse对照通过；这只是JSON解码验证，没有执行游戏脚本。
SDK私有输出实际归并了重复成员，报告明确记录字节变化与逻辑值不变，不将此称为纯空白差异。
其ProgramData位置全部未证实，任何对该文件的写请求都拒绝。父子输出审计仍严格拒绝重复
输出键和其他额外变化。成品对这四个文件采用原字节copy，绝不收集SDK归并后的文件。

## 源码与当前游戏证据

- 新增17项验收：五项目录、九项副作用/来源/父进程/重复键、三项真实Win32发布边界。
  加既有后端/事件专项最终27通过。完整源码518 passed /207 subtests passed，含安装版
  T++8.8.9，一条既有依赖弃用警告，无skip/fail/error。
- 当前游戏源码证据：`work/current-json-builds-v21/052e8c3ab4a44b1f863d1442df052359`。
  Stev约371.63秒、SExtractor约204.12秒；各六文件/16批准JSON位置、9570清单文件verify通过。
- Stev完整9570输入逐项hash保持，真实ProgramData35903行，一轮实际InjectGame输出178个
  JSON并核对16个批准位置。四个重复键文件仅发现且成品copy原hash；全部非路由输出在两
  后端间逐字节一致。另核对原生JS AST、批准图片、字体/映射和所有输出集合/hash。
- 独立副本沿用17716单元/29旧人工样例，再加2 Items并锁1条，共31接受、17685未译；
  构建明确--test，runtime not_run。原游戏全部9570文件、主DB、图/译文/锁及SDK/config保持。
- 真实导入中的取消保留部分输出，确认所属PID已退出，无成功报告/sidecar；来源os.open
  截断、未声明写入、未批准JSON、配置变更、请求持久化失败与报告篡改均有独立拒绝证据。
- 固定来源测试制造时间戳/大小均匹配的缓存，确认目录及旧只读入口均执行实际源码。
  旧提取器误丢合法文本“原文”也已修复，真实候选/路由和配置失效流程覆盖该值。

## Windows目录发布修复

源码专项曾在RPGMTL构建最终目录rename出现WinError5，现场保留，未确定具体占用者。
现在对同输出父目录、同构建UUID的staging→final执行有限0.03/0.06/0.12/0.24/0.48秒
重试，仅处理Windows5/32/33。每次重查安全路径和已有目标，绝不替换已有成品；持续失败
保留完整staging和失败记录。真实GENERIC_READ无delete-sharing目录句柄测试证明短占用
释放后成功、持续占用失败保留、已有输出不改。COMMITTING仍不接受迟到控制请求。

## 协作与失败保留

使用deepseek-worker，deepseek-official/deepseek-flash/max，无maxTokens覆盖；2400秒
上限，1392.119秒完成。仅两个允许文件改变，59次工具调用均通过guard，无协议错误、
保护文件变化或私有游戏/凭据读取。交接verified:false，Codex核对9个hash后审查、集成和验收。

Codex修正缺少ruamel的实现依赖，复用已锁PyYAML；加强既有目录检查，修复源码缓存和
合法文本过滤，补齐完整重复键清单/发现边界和目录发布重试。首轮12失败/10通过、第二轮
2失败/20通过、发布WinError5、初版句柄只用属性访问未能阻止rename等现场均保留。
首个整目录预检因重复键失败，其原游戏/主库保全通过；修正后在新UUID完整重跑，没有略过
问题文件。源码/冻结结果分列，不把worker完成或模拟响应当作验收。

所有原文、译文、工作副本、ProgramData、失败日志和worker记录留在私有work，不随软件/
源码包分发。没有批量删除，没有向编码模型发送游戏文本，没有真实翻译或自然游玩调用。
