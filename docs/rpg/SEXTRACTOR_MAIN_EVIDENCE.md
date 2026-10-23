# SExtractor 真实主入口接入与 G03 验收

日期：2026-10-19。实现版本：0.20.0-dev。源工具固定为
satan53x/SExtractor `8d8d976fd04ae54e7c677705af937273d04a376a`。
范围是 RPGMV 模块处理的 MV/MZ JSON 和原生已批准位置；其他引擎、任意规则及全游戏
自然游玩不据此通过。源码和新冻结 EXE 的证据分别记录，最终便携状态见本版交付回执。

## 实际调用与文件边界

SExtractor 的默认 JSON 回写已改为两个新进程，均调用真实
`main_extract_json.mainExtractJson → main_extract.mainExtract`。提取、格式列表导出、
列表译文读取、parse/replace/write 均由原工具执行；没有以本地 writer 修补其输出，
也没有失败后转回旧内存 writer。只读覆盖比较仍使用原来的独立内存解析 API，和这条
默认回写路径分别声明。

父进程只发送原文 bytes、已批准 changes 和捕获配置；不传原游戏目录。
每次调用建立全新 UUID case，提取和导入分别拥有独立 cwd/main，PID 必须不同。
固定使用 RPGMV、JSON、列表格式 7；关闭自动分段、替换、文本追加、压缩字符串、
JIS、动态配置和其他自动改写。保留主入口自己的真实 IO 流程。

| 阶段 | main 下允许的文件 |
| --- | --- |
| 提取 | src/engine.ini、document/input.json、document/ctrl/all.orig.json |
| 导入 | 上述三项，加 document/ctrl/all.trans.json、document/new/input.json |

四个工作子目录预先创建。Python 运行期 guard 只允许该阶段的声明输出，拒绝额外
文件、删除、移动、目录创建、进程启动和 socket 创建/IO；仅放行 Pandas 初始化所需的
本机名读取 `socket.gethostname`，这不进行连接或名称解析。运行后父子双方再检查完整
文件集合、目录、reparse/hardlink、大小、来源/配置/列表字节和 SHA。该 guard 针对审计过的
固定 SDK，不是操作系统安全沙箱。

原始 UTF-8/BOM/CRLF bytes 在两个阶段均完整保留；sidecar 保存 source hash、原始 ctrl、
批准指针、config hash、阶段 PID/目录/清单、入口源码 hash 及实际输出 hash，阶段协议还
保存原始列表及含头部偏移的定位。可由私有清单重新检查原格式与原位置。
返回的是实际 `new/input.json` 的 bytes。空变更也执行真实提取/导入并比较语义，可能采用
工具的 JSON 排版；不能再声称该候选只是未调用 writer 的字节透传。构建中完全没有译文
的其他文件仍按原 BuildService 规则复制。

## 同文不同译与配置固定

主入口普通字典格式会合并同文，不能直接用原文作唯一键。实现读取实际导出的
all.orig.json，核对其每项与真实 ctrl/text 的对应；只用唯一完整叶证明定位 requested
changes，再按记录位置填入列表译文。未请求位置填原文，显式空译文也有独立位置。
导入阶段重新解析同一原文，控制列表、原文向量必须与提取一致。最终结果与原生批准
计划作类型保持的完整 JSON 比较，额外变化拒绝。根字符串数组、数字字典键等既有
不可表达位置保持拒绝。

402/357 及已批准的 122 字符串字面量规则仅在当前新进程暂时启用，finally 恢复，
工具源文件不改。原生 consumer、TokenPolicy、value codec 和所有权仍决定显示权限。
原生默认 writer、JS AST 与图片/字体流程不获得新的翻译权限。

现在的路由指纹包含 SDK Python 源码及 `src/engine.ini`。旧 SExtractor 路由需要重新
生成候选并设置，不能沿用只固定 Python 的旧证明。其他后端根目录维持原有指纹范围。
工程格式 2、写入计划 v7 不变；旧工作和中断产物保留，没有自动迁移或清理。
实际依赖为 Python、PyQt5.QtCore/QSettings、Pandas、python-rapidjson 及列出的 SDK 源文件；
缺失会失败，不提供假的 Qt/JSON 模块或自动安装。

## 原计划逐项核对

| 开发计划 §14.3 | 直接证据 |
| --- | --- |
| 每次提取/导入独立 worker | 两个 PID、独立 main/cwd；真实导入中取消后无候选发布 |
| 包装 main_extract.py、日志与协议分离 | 实际 mainExtractJson/mainExtract，入口与依赖来源 hash；有界丢弃日志 |
| ctrl、来源、格式映射 sidecar/hash | 原文 bytes、实际导出、ctrl/span、两阶段清单和实际输出的 SHA |
| JSON/RPGMV 对 MZ 实测 | 下述通用 JSON 负例评估，以及 RPGMV 当前游戏六文件完整构建 |
| 中文/空格/BOM/CRLF/空字符串/嵌套 JSON | 真实主入口和既有数组、事件编码验收；同文多位置及多行数组 |
| 导入只到 work，再统一校验 | 3/5 文件白名单、阶段 guard、双重源/配置核验、完整预期 JSON、BuildService staging |
| 不可靠正则限制范围 | 固定 RPGMV/完整叶；不开放任意正则或自动切换 JSON 引擎 |

§14.5 最低条件分别由固定 source/config、实际依赖失败、定位记录、真实零/单条往返、
重复/来源/配置冲突拒绝、阶段间及运行中取消、来源保全、完整差异/清单覆盖。
G03 按原“独立进程和 MZ 样例往返”验收；这不关闭 G01 的 GameDir/ProgramData 桥接，
不关闭完整 P0、真实模型、自然游玩或其他游戏验收。

## JSON 模块实际表现

通过同一真实主入口，以通用 `extract_JSON` 模块读取当前游戏的捕获文件，独立进程
实测：Items/Skills/CommonEvents 均 0 记录；System/Map023 均 TypeError；SH_Nuiit
可提取 352 记录，但这不构成显示权限或回写许可。主库、捕获源及上游 source/config
保持。结果证明不能把普通 JSON 模块当作自动兼容回退，正式路径固定 RPGMV。

## 直接验收与保留记录

- 私有真实入口可行性：`work/sextractor-main-probe-v20/e881854e8da540988f36594448986956`，
  提取/导入不同 PID，四个指定位置、重复同文、多行嵌套数组和完整字节来源核验通过。
- 通用 JSON 六文件评估：`work/sextractor-generic-json-v20/6c4fc2dd7c574df1ab6dc84cd2942822`。
- 五项入口验收先在 0.19 全部失败；不把旧内存 API 的通过当作主入口接入。
- 最终专项 27 项通过。完整源码 501 passed / 207 subtests passed，含安装版
  Translator++8.8.9，一条既有依赖弃用警告；无 skip/fail/error。
- 源码当前游戏：`work/current-json-builds-v20/ed9711691019409e980557d2003b857e`。
  Stev 与 SExtractor 各六文件、16 个批准 JSON 位置的路由及完整测试构建通过；各
  9570 清单文件 verify。SExtractor 构建的每个 writer sidecar 均核对真实两阶段、
  入口/config hash、原文、全部阶段文件 hash 与实际上游输出；另核对原生 JS、
  批准图片字节和显式字体，非路由输出在两个后端间逐字节一致。
- 独立副本沿用主图 17716 单元，29 条旧人工样例保留，再加 2 条 Items，共 31 接受、
  17685 未译；构建明确为 --test。原游戏全部 9570 文件（含构建排除的日志/存档）、
  主 DB、单元图/译文/锁、SDK source/config 保持。无应用模型请求或游戏启动，runtime not_run。
- 新冻结 EXE 同链路、故障与当前游戏验收，以本版交付回执为准，不能由源码结果替代。

使用 deepseek-worker，deepseek-official/deepseek-flash/max，无 maxTokens 覆盖。
复杂任务上限 1500 秒，1294.458 秒返回；目录 grep 被 guard 拒绝一次，policy_violation
按失败交接，四个授权文件外无写入、保护文件不变。Codex 接管审查与验收：修复模块名/
文件名哈希映射、依赖本机名误拦截、证据写入失败处理、控制列表/目录检查并加入配置 pin。
首轮专项 13 失败/12 通过的误拦截现场保留；收紧故障匹配后 25、最终 27 通过。
原型的 env 参数和规则名驱动错误也保留。没有将失败归因为当前游戏，未放宽网络连接
或来源写入限制。所有请求、源/译文、阶段文件、失败日志留在私有 work，不随源码/便携包分发。
