# AiNiee RPG 使用说明

当前版本为7.2.4.1。可进行 MV/MZ 工程扫描、规则提取、AiNiee 翻译与校润接入、人工编辑、校验和独立副本构建。外部工具可在“工具与恢复 → 外部工具管理”一键下载配置或选择已有安装，详见 EXTERNAL_TOOLS.md。完整计划的验收状态见 IMPLEMENTATION_STATUS.md；程序版本不代表游戏汉化已经完成。

完整解压当前 Windows 便携包到可写的本地目录，然后双击
Start-AiNieeRPG.cmd。它明确使用Windows Qt平台，并将本次启动记录写到
Logs/launch/<独立编号>；看到主界面才算窗口打开。不要直接在ZIP内运行，程序及
日志目录避免使用方括号或反引号，遇到此限制启动器会明确报错，不移动已有文件。
中文、空格、&和!目录已检查；工程目录作为参数传入时另已检查方括号和尾部反斜杠。

日常入口没有启用离线模式，仍需在AiNiee中配置所用提供商和模型。默认保留原有
配置/缓存位置，不自动迁移或重置设置。启动器不会等待程序退出，也不把创建
进程当作GUI验收。关闭程序时，需在其退出确认弹窗中确认。

需要独立离线诊断时，在程序所在目录用Windows PowerShell执行以下命令：

```powershell
& '.\Start-AiNieeRPG.ps1' -Offline -DataRoot 'C:\RpgLocal\diagnostic'
```

可加 `-Project 'C:\RpgLocal\project'` 打开工程。DataRoot将配置、缓存与日志放在
指定目录，不读取原配置，因此需要另行设置模型；日常不要照抄离线诊断参数。
这两个脚本需与AiNieeRPG.exe放在同一目录；旧封存0.41包没有它们，补订包已包含。
详情见SANDBOX_ACCEPTANCE.md及DELIVERY_RECEIPT_0.41_LAUNCHER.md。

0.41补齐当前设置菜单的4个自定义开关名称。先备份工程再重提取，新名称与原先
两段开关状态文字使用同一组参数规则；开关ID、标识及行为保持。旧995条记录和
锁在升级验证中保留，新4条采用中性样例，实际设置页显示和切换已检查。正式
翻译时请替换验证样例；本版没有执行真实模型翻译。见E03_FOLLOWUPS_EVIDENCE.md。

0.40补齐人物页变量375的6个派生状态片段；请先备份工程，再用新版重提取。
它们通过数值别名进入人物页，旧0.39包未提取。可筛选heart:derived-status。
“未経験”占位词同时参与比较，译文不要使用伴侣姓名；伴侣姓名仍按身份保留。
当前13个固定姓名已核对；修改身份或使用改过姓名的存档后应重新核对。示例采用
中性占位词，非正式译文；详见DERIVED_STATUS_EVIDENCE.md。其余93项来源仍按
当前SOP保留，发现实际显示时先记录消费者，不按日文特征自动授予回写权限。

在Windows Sandbox中，将软件、工程、缓存和检查工作目录放在沙盒本地磁盘；
宿主映射目录用于输入文件和收集完成结果。本次映射工作区出现过SQLite磁盘I/O
错误，本地工作区通过。0.40已完成自检、GUI检查和正常窗口确认；重新验收使用
当前Tools/prepare_sandbox_acceptance.ps1或0.40独立验收附件中的修正版，封存
源码ZIP内辅助脚本仍是封包快照。生成器为正常窗口明确设置Windows Qt平台，
使用独立本地配置/缓存并重定向启动日志。初始控制台停滞未隔离单一根因；若仅
出现黑色控制台，不据此当作界面已打开，保留日志再定位。具体范围见
SANDBOX_ACCEPTANCE.md。沙盒退出会清空来宾临时目录，重新打开验收配置即可
从头检查；已完成的结果保存在宿主，无需恢复旧来宾路径。

0.37再定位13个词典效果名称及两个城市/城镇模板替换值，当前18659单元。备份后
用新版重提取，效果数字code、模板和其他控制保持；两个地名通过术语保持一致。
当前没有这些模板的自然数据实例，采用受控原函数/原窗口演示，样例不是正式翻译。
其余99项配置/未证实显示来源按原文SOP保留，不自动开放；若实际看到它们进入
玩家显示，先记录场景、变量和调用，再补规则。详情见E03_FOLLOWUPS_EVIDENCE.md。

0.36增加8个动态颜色章节目标和地图提示的25个正文位置，当前18644单元。
先备份工程，再用新版重提取。固定颜色边界由程序保留，正文内完整控制符、姓名
及换行仍须保留。含js_fixed_affixes_v1的新工程需要0.36及以后的支持版本，旧版
会拒绝打开，不手改能力标志。正式译文须检查目标窗口和实际动态名称的最终宽度；
当前验收使用中性占位样例，未执行真实模型翻译。见E03_FOLLOWUPS_EVIDENCE.md。

0.35源码定位11个装饰性英文标题，当前18619单元；这批不计作中文布局通过。
它们使用11像素高位图，部分中文会裁顶。翻译前点击页面提示中的“筛选装饰标题”，
10项保留原文并锁定；Experience手工短写为E X P并锁定。主菜单中文条目继续使用
已有规则。CLI和其他入口也遵守此SOP；接受记录数量包含保留原文，不等于中文
译文数量。来源、实际裁切反例和最终SOP显示证据见E03_FOLLOWUPS_EVIDENCE.md。

0.34新增49个随机标点/部位词显示片段，当前18608单元；本批已进入本地新
便携包。先备份工程再重提取，身份键和台词的{Part}/{Punc}模板保留，组合词
尽量短，最后检查原Ticker显示。游戏在替换部位词前判断长度，参数20/30不保证
最终宽度；优先缩短译文。中性样例与真实翻译分开，范围见E03_FOLLOWUPS_EVIDENCE.md。

0.33源码增加90个章节目标/标题、技能类型名称/帮助及召唤/情报/历史显示位置，
当时18559单元；动态颜色跨片段章节已在0.36另行处理。实际ESC姓名控制已补保护，含这类
控制的工程应使用本修正版，旧0.32保护不完整。不要手工删除姓名、编号或控制
前缀。范围、验证占位词和未验来源见E03_FOLLOWUPS_EVIDENCE.md。

0.32源码再接入63个陷阱/传送点名称、时间名、要求名称、任务/回想提示及人物页
标题、两个hint前缀及四个事件模板片段，共69个新单元，当前源码图18469单元；
本版冻结已包含这批规则，旧0.31不支持event_js_spans_v1新能力。保留旧工程备份，
使用包含该能力的新版，不手删声明。传送点旧存档保存的名称
需重新激活路标后由游戏原逻辑刷新，不自动回填。私有验收工程含验证占位词和锁，
正式翻译请从原版新建工程或明确处理测试样例。范围与原装显示见DISPLAY_LABELS_EVIDENCE.md。

0.31源码补齐当前游戏UniqueParams.unit字段规则，复用原JSON处理；当前104项均
为空，所以重提取不会凭空新增单位。非空时按简短单位用语编辑并检查具体窗口。
当前自定义表的显示、身份、资源及元数据边界见CUSTOM_JSON_SCOPE_EVIDENCE.md。
不要因为语音索引、逻辑键或备注含日文就批量翻译；0.30默认包不含本单位规则。

0.31另补六份已审查插件的14个直接显示片段，复用现有AST区间读写；动态颜色
指令跨片段的一条地点提示按SOP保留原文，见DIRECT_DISPLAY_EVIDENCE.md。
提取新版规则后工程需要js_source_spans_v1能力，旧0.30程序会拒绝打开；保留旧
工程备份，使用包含该能力的新版，不手删能力声明。源插件版本变化时重新审核
profile；普通译文编辑照常通过页面进行，不手动编辑已登记源快照。

0.30完整输出另已在原装Game.exe验证列明开场、菜单/说明、存读档、战斗与随机
手机路径；程序文件保持，部分入口为显式测试准备。范围和失败记录见
FULL_OUTPUT_RUNTIME_EVIDENCE.md；不能据此推定全部剧情、资产或译文质量通过。

当前工程备份已选择Noto Sans CJK SC Regular 2.004，本次2190个输出静态字符缺字0；
字体不随软件包分发。选本地字体后，对保留日文的副本执行font-check --include-source，
确认报告字体与输出配置一致。动态姓名/变量、图标及分页另用代表值和长值检查；纯
控制码消息可能完全没有采集记录，空layout_issues不能作为通过。长菜单优先缩短
术语，勿缩全局字号。来源、27字实际显示及长变量反例见FONT_COVERAGE_EVIDENCE.md。

当前0.141游戏的System.elements兼作属性逻辑标识。开始翻译前筛选system.elements，
逐项保留原文并锁定；0.30编辑器可点击“保留原文并锁定”后按“确定”。0.29包需手工
复制原文、勾选锁定。CLI、直接AiNiee及第三方入口也必须先完成此步骤，不改属性名。
0.30项目页提示并检查此约定；既有人工锁会排除模型任务并拒绝自动覆盖。

0.30源码再补119个任务开始、聊天联系人/正文、衣物名称和视频标题/频道备注值。
聊天按原行翻译，保留[self]所在行及模板/控制符；包含贴图资源的3段混合聊天仍保留。
需要处理时先在独立输入副本人工改正文、保留贴图行，再重新扫描。不要修改登记
源快照或封存副本。剩余14个备注候选的逐项处理和验收见NOTE_FOLLOWUPS_EVIDENCE.md。

0.29源码合计增加349个备注值，涵盖任务说明、频道名称/说明、技能提示、人物关系、
经历单位、技能台词和文书。频道等共享备注的各项分别编辑，
工具合并回写并保留其他备注；只有一项接受译文时，另一项保留原文。保留控制符和
换行，不引入ASCII尖括号；问号占位提示建议原样保留，未启用数据不代表新剧情已验。
Items/Skills本版选择原生回写。请在工程备份重新提取；旧未完成提取/构建保留后新建。
旧0.28不能打开含共享备注能力的新工程，不手改能力字段绕过。见NOTE_GROUPS_EVIDENCE.md。

技能台词保留{skillName}模板；技能312有两个message2，工具只编辑引擎实际使用的
最后一个，先前值保留。任务说明转为共享备注时保留已有ID、译文和锁，重新提取后
仍保留。旧迁移审阅方案需要新建；不要手改算法版本。见NOTE_CONSUMERS_EVIDENCE.md。

0.28源码的font-check会将缺字关联到具体单元和文件。默认只查当前接受译文；测试
副本保留未译日文时加--include-source，并查看scope_counts，区分译文和保留原文。
报告是所选单字体的静态cmap检查；动态变量值和系统回退字形须在游戏内另验。
缺字报告的退出码为1，请保留报告并按涉及单元处理，不能理解为程序崩溃。

0.28的runtime-report增加layout_profiles、layout_issues和layout_stats。仅对确有宽度
数据的观察给出横向测量；TEXT_LAYOUT_OVERFLOW提示检查裁切或压缩。短菜单优先
缩短译文，再新建测试副本复查；不自动改窗口或全局字号。没有采到、旧记录无宽度、
动态值、纵向分页和图片文字不由空问题列表判为通过。详见FONT_LAYOUT_EVIDENCE.md。
新采集脚本使写入计划升至v10，旧未完成构建保留并新建，不手改检查点版本继续恢复。

0.28当前游戏规则还提取Items.json中36个SG説明及11个SG共通説明备注值。编辑时
只处理显示值，保留控制符和显式换行，不加入ASCII尖括号。标签名和其余备注不会
送入模型；0.29只对明确的频道字段对补共享回写，其他标签及动态脚本仍未开放。Items.json本版
选择原生回写。请在备份工程重新提取；旧未完成提取保留并新建，含note_tag_text_v1
的工程不能用0.27打开。详情及原装引擎证据见NOTE_TAG_EVIDENCE.md。

0.27源码的运行诊断新增完整窗口/消息采集、100新事件/秒与最新3000条。仅在私有
测试副本显式使用build --test --runtime-capture；导出JSON后，用runtime-report
--project 对应工程 --file 采集JSON生成只读定位报告。候选不自动变成规则；组合文字
和图片继续人工复核。stop()关闭后需重开副本开始新采集；旧未完成构建保留并新建。
诊断正文不可公开，详细步骤及边界见RUNTIME_CAPTURE_EVIDENCE.md；0.27便携EXE范围见交付回执。

0.27源码还在构建清单列出来源/profile/版本及文件关联单元；补丁导出须与工程内
完成构建登记一致。曾手改输出或清单时，请在工程中重建，不通过同步修改哈希绕过。
发布后未登记的输出先显式恢复。补丁及应用结果会说明是否含已知诊断脚本文件，
诊断补丁只用于私有测试。恢复与补丁实测见CURRENT_BUILD_RECOVERY_EVIDENCE.md。
便携包未提供的PDF/MTool依赖及使用约定见PORTABLE_SCOPE.md，其他普通文档不按RPG验收推导。

0.26源码增加当前游戏82处显示文字：奖励/直播提示、实验室项目、人物资料、声望文字，
以及资料姓名前缀与称号尾词。请在工程备份中发起新提取；原有有效译文和锁保持。
含新静态模板片段的工程需要0.26，0.25会明确拒绝。模板变量仍由游戏计算，编辑时
只处理提取出的静态文字；`{self}`等现有占位符和已限定的换行仍需保留。
实验室的`-`为显示分隔符，按使用约定原样保留。含模板片段的JS文件选择原生回写，
RPGMTL目前只支持已测的普通字符串；不会自动切换后端。源码验证与便携包/实际运行
分别记录，源码范围见PROFILE7_EVIDENCE.md，新包的实际EXE/完整构建范围见DELIVERY_RECEIPT_0.26.md。

0.26另增加当前游戏12个插件的55个显示参数及4段嵌套脚本静态文字。参数会自动按
明确的JSON层级提取和写回，编辑时只改显示文字，保留已有占位符和换行。
plugins.js请选择原生回写，RPGMTL登记文件路由本版明确不支持。兼作菜单导航键或
配置身份的名称按使用约定保留原文，不能仅因含日文就批量替换；详见PROFILE8_EVIDENCE.md。
请在备份工程新提取，原有效译文/锁保持；0.25不能打开含新参数能力的工程。

0.24源码的主翻译/校润、多文件表格及AI自动校对共用工程执行隔离和停止控制。
问题表“AI自动校对”使用接口管理的校对绑定，读取规范原文和当前接受译文，只处理
译文字段；缺译文时可重译，来源字段和人工锁保持。格式/控制符错误至多尝试两次，
冲突结果保留供检查。请等待组内全部请求收尾，再开始新任务或切换工程。源码和新
便携包分别完成本地检查；真实模型和完整自然游玩另验，详见PROOFREAD_SCOPE_EVIDENCE.md
及DELIVERY_RECEIPT_0.24.md。新ZIP实际EXE28组、当前游戏两后端9570文件测试构建
及七项checksum已通过；包内说明是构建时快照，最终证据见交付目录DELIVERY.json。

0.39源码的游戏翻译、润色和AI校对在初次请求失败后最多重试两次。主任务设置更少
轮次时仍按较小设置执行，表格部分成功时只重发失败条目。达到上限会提示未完成并
保留原有有效译文，请修正规则或设置后手动重试。人工锁、人工改译导致的版本冲突
不会通过重试覆盖。该策略待新便携包交付；0.38及以前仍按各版原行为。

0.25源码现已接入游戏“全文分析”：使用规范原文、提取角色和单个实际任务，支持停止，
结果保存在工程并可重建。候选需确认后加入应用词典，不自动改动游戏译文；取消或失败
后重新执行，旧候选保留。应用词典为全局设置，不同游戏通过词典导入/导出管理，任务
运行时避免同时修改词典或启动接口测试。详见ANALYSIS_WORKFLOW_EVIDENCE.md。
0.25便携包已通过该流程的冻结验证；0.24便携包仍有旧全文分析隔离缺口，游戏工程
请使用0.25或后续版本。最终冻结证据见DELIVERY_RECEIPT_0.25.md。

0.25源码的当前游戏profile另增加14个事件脚本显示位置，包含直播标题、炼成奖励
标题及学校提示。已有工程需发起一次新提取；旧中断记录不续用。当前工程备份已验证
原29条译文/锁保留，另补入279个此前已实现的选项问题指针。只支持已批准位置中的
单个双引号字符串，其余脚本保持候选，不尝试自动修补。详见PROFILE6_EVIDENCE.md。
0.25便携包已包含本增量，实际EXE完成9570文件测试构建；炼成标题和学校提示另有
原装引擎受控显示证据，完整自然路径仍未验收。详见DELIVERY_RECEIPT_0.25.md。

0.23源码已接入有界只读前后文、结构可证明的选项问题来源，以及每轮共享的工程图准备。
人工锁与译文版本仍按批次读取；缺少有效译文时校润会明确拒绝。旧工程需要重新提取，
才能补上新增的选项问题来源；旧提取算法的中断记录不能续用，应发起新提取。
源码、模型实译与新便携包验收分别记录，详见CONTEXT_PREPARATION_EVIDENCE.md。
已校润条目会从工程记录恢复“已校润”，刷新后不会自动重复进入校润轮次；重新人工
改译的条目可再校润，人工锁与来源变化继续优先处理。
游戏项目的“重置状态”会保留已接受译文及人工锁，把可重置条目重新排入任务；重载
工程后意图仍保留。重置前发出的旧结果不能覆盖新任务版本；版本变化或保存失败时会
提示重新加载，校润重置只处理已校润且未锁定的有效条目。
游戏输出在翻译/转换开始前检查目录，写入前再次检查；工程内可使用AiNieeOutput、
AiNieePolishOutput或exports，其他自定义位置请选择独立于工程和原游戏的目录。
原游戏、捕获source和jobs等权威目录会拒绝。交换与质量报告各自生成独立JSON，
不会覆盖已有文件。启用质量检查时，报告合并控制符/值约束与常规质量检查，并标明
运行及模型质量验收未执行；未译、排队任务和有效文本质量分别记录。

0.22修复编辑锁定译文时异常退出可能丢失人工锁的问题：译文和目标锁在一次事务提交，
失败保持原值；普通自动结果仍不能越过人工锁。翻译/校润和表格按连续场景分批，
不同场景不混入同一请求；表格按源文件顺序处理，空场景不会继承邻接场景。
严格边界可能增加请求批数；该版本尚未接入完整上文提示词，后续源码改动见上文。
详见MANUAL_EDIT_ATOMIC_EVIDENCE.md和SCENE_BATCH_EVIDENCE.md。

0.21已接入Stev真实整目录ReadGame/ProgramData/InjectGame构建，完整工作副本与输出
差异核对后只采纳选定文件。config.yaml纳入指纹，旧Stev路由需重选；重复键文件仅发现、
原字节复制，不获得写权限。详见STEV_PROJECT_EVIDENCE.md。

0.20 的 SExtractor JSON 回写改用真实 main_extract 主入口：提取、导入各一个新 worker，
只访问 work 中的单文件副本及捕获配置；实际输出通过原生批准差异后才进入构建。
需要完整固定版 SExtractor 源码，包含 main_extract.py/JSON/helper/RPGMV 及 engine.ini。
现在还固定 engine.ini 指纹，旧 SExtractor 路由须重新生成候选并设置；不会自动降级。
Pandas、python-rapidjson 和 PyQt5.QtCore 为真实运行依赖。空变更候选也执行真实往返，
JSON 排版可能变化；构建中完全无译文的其他文件仍复制。细节及已测范围见
SEXTRACTOR_MAIN_EVIDENCE.md，冻结程序状态以本版回执为准。

0.19 修复 SExtractor 对 System 菜单等数组文字的请求字段转换。仍需先生成该文件的真实
候选并核对原生批准差异，才能选择文件回写后端；无法证明位置时拒绝，不自动切换工具。
当前游戏 Stev / SExtractor 的受限回写证据及与原 CLI 设计的差异见
BACKEND_CURRENT_GAME_EVIDENCE.md，最终便携程序验收以本版交付回执为准。

0.18 的游戏工程页和高级设置页支持整体滚动，小窗口可访问顶部操作和底部状态；长构建
状态换行显示。侧栏根据页面实际最小宽度提前折叠，保留原有动画。当前游戏已在1280×720
窗口走通新建、提取、人工样例、构建及核验闭环，另测1024×720和1600×1000窗口；这是
窗口尺寸测试，没有改变物理显示器分辨率。界面自检会等待底栏稳定可见并命中才截图，
无法显示时明确失败。证据及限制见 COMPACT_UI_EVIDENCE.md；真实翻译和完整自然游玩仍待完成。

0.17 在提取提交前分离并校验输入，避免等待数据库写锁期间外部修改模型造成不一致。
重复序列化和 SQL 绑定准备移至写锁外，连续新增行批量写入；译文、修订、问题及任务完成
仍原子提交。连接使用按需分配的 32 MiB 页缓存预算；多连接会增加内存预算，数据库格式
及同步设置保持。当前游戏与 30000 单元本机热缓存样例事务低于 200ms，冷缓存及其他设备
仍待验证；整个调用会增加锁外校验时间。证据和范围见 STORE_PREPARATION_EVIDENCE.md。

0.16 把常用操作、工具与恢复、Translator++ 分为三个操作页签。完成构建后，下方会显示
最近副本的路径；“校验副本文件”和“打开输出目录”都会在后台核对文件内容及当前工程
中的构建登记，发生变化时拒绝打开。打开目录会请求 Windows 文件管理器显示该目录，
不会启动游戏，也不会将运行期状态改为通过。检查期间可以暂停或取消；历史旧副本保留。

“送往 AiNiee 翻译”改为后台准备工程，完成后才切换视图；载入期间可取消，准备失败或
有新的翻译任务启动时保留原缓存。该操作不会调用模型。先完成提取，再送往翻译视图。
载入后语言选择器同步为日语→简中，显示值与保存的配置保持一致。
主题监听线程改为可正常停止的轮询，避免 Windows 退出时强制终止线程。缓存写失败时
保留独立临时文件供检查，不自动删除。0.16 测量见 GUI_WORKFLOW_EVIDENCE.md，本版复测见
STORE_PREPARATION_EVIDENCE.md；完整性能及自然游玩验收尚未完成。

0.15 使用构建写入计划 v7：在创建输出暂存文件前，将唯一名称及构建、尝试、冻结输入
绑定登记到工程内。持续占用或进程退出后，恢复会核对登记和实际字节摘要，逐个把已登记
暂存保留到工程记录目录，再从冻结输入重新生成。半写入暂存也保留，但不会直接作为
已完成检查点发布。无登记、登记损坏或绑定不符的文件仍会阻止发布；旧构建的未登记
暂存不会按文件名猜测归属。工程记录和输出跨文件系统时保留现场并明确拒绝归档。
工程数据库格式和现有译文不升级。v6 及此前的未完成构建需新建，旧暂存、译文及完整
副本保留；完整副本仍可独立校验。便携包状态以对应版本交付回执为准。

0.14 修复工程恢复与任务正常结束之间的竞争。恢复只将仍处于活动状态、且没有进程持有
租约的任务标为 INTERRUPTED；已完成、失败或取消的任务保持原记录。锁文件会保留，
是否可恢复由操作系统句柄决定，不按文件年龄或 PID 推测。多个窗口可以同时查看工程；
持有工程写锁的扫描、提取、构建或外部候选任务仍会阻止另一个写操作和恢复操作。
模型等待期间只持任务租约，人工编辑可提交，迟到响应仍受修订及锁定检查约束。
本次不修改工程格式或构建写入计划版本，具体证据与适用边界见 JOB_RECOVERY.md。
构建替换文件遇到 Windows 5/32/33 错误时最多尝试六次，总延迟 0.93 秒，每次重新检查
目标和暂存路径。持续失败会保留旧目标及完整暂存，不发布输出；解除占用后可新建构建。
未登记的 .staging 文件仍会阻止恢复尝试发布，不会被忽略或自动当成已验证检查点。

“比较后端提取…”完成后会打开只读报告，可按原文、位置、角色、编解码和后端定位
筛选，查看额外候选、遗漏、歧义与字段类型冲突。大地址组只在界面预览前100项，完整
地址保留在报告文件。原文和hash供人工审查，不授予回写权限；旧报告缺信息时重新比较。

0.6 源码新增“恢复提取…”与文件级 JSON/JS 检查点。恢复使用当时冻结的规则；规则
修改后新建提取。旧任务无检查点时重新提取，人工译文及锁仍保留；便携状态见交付回执。
0.13更新构建写入计划版本。此前版本的未完成构建需重新构建，旧暂存与诊断保留；
工程、已接受译文与旧版本完整副本继续可读。
Windows替换配置遇到短暂共享/访问错误时最多等待0.93秒重试；仍失败会报错、保留旧
配置与独立临时文件，不会先清空旧配置。它不提供多个程序同时编辑配置的冲突合并。
读取配置的I/O错误会直接报错，不会被当成空配置继续写入默认值。
“迁移旧译文…”先生成五类对账，再应用可靠匹配。无 game_id 时需要明确关联两份工程；
不能用游戏名覆盖已知 ID 冲突。已有有效译文/锁保留，计划后发生编辑需重新对账。
迁移已支持暂停/继续/取消和任务检查点恢复；中断后使用“恢复迁移…”复用已核验提案。

0.5 源码新增提取前地址重叠检查和统一后端能力表。旧工程若出现重复位置，应先查看
校验问题并修正规则；未译冲突也会阻止送译和构建。`capabilities` 列出支持范围，
不表示外部工具已经安装或文件已经通过回写。便携验收结果见交付目录 DELIVERY.json。
离线校验增加“恢复校验…”：复用已核验单元，工程有新编辑时须重新校验。

0.4 新增场景锚点迁移和五类对账，并为当前游戏加入经过消费者/原生渲染验证的 R
保留规则。R 不能改为 CR，具体边界见 CONTROL_R_EVIDENCE.md。既有 0.3 ZIP 保持原样。

0.3.0-dev 新增 profile 3 的受限显示字符串和函数词表规则。编辑器中只编辑显示文字，
事件表达式的引号由回写器编码；逻辑字段不会自动开放。受保护地点说明必须保持换行
数量，搜索显示值不能改变零值条件语义。具体已验证范围见 PROFILE3_EVIDENCE.md。
工程仍使用物理格式 2，但包含新增能力；旧 0.2 程序应拒绝此类工程。既有格式 2 工程
增加能力前会保留数据库备份；备份不是包含全部素材的独立工程。旧构建使用原程序
恢复，新版本应新建构建。请先在新工程试用新规则，既有已交付 ZIP 保持原样。

0.2.0-dev 新增占位符、显示值保护和 MZ 自定义字体映射。它新建格式 2 工程，仍可读取格式 1；
旧工程首次启用高级规则时先备份再升级。0.1.1 无法打开格式 2 工程。两版写入计划不同，
旧构建请使用原版程序恢复；新版本需要新建构建。已交付 ZIP 不随源码开发变化。

当前体验版的已核验 profile 会把四个自定义日文字体名称一并映射至所选简中字库。
请在提取规则后重新选择字体，再新建构建。字体仅捕获到私有工程并写入游戏副本，
不随软件便携包分发。其他 profile 需显式声明 font_aliases；该映射限 MZ。

## 启动与依赖

源码环境：Windows x64，Python 3.13，Node.js 24。依赖版本锁定在 requirements-rpg.lock；Acorn 版本锁定在 Tools/package-lock.json。依赖安装到项目的虚拟环境和私有 .tools 目录，不需要修改游戏文件。

```powershell
python -m venv .venv-rpg
.\.venv-rpg\Scripts\python.exe -m pip install -r requirements-rpg.lock
New-Item -ItemType Directory -Force .tools/js
Copy-Item -LiteralPath Tools/package.json -Destination .tools/js/package.json
Copy-Item -LiteralPath Tools/package-lock.json -Destination .tools/js/package-lock.json
npm ci --prefix .tools/js --ignore-scripts --no-audit --no-fund
```

Node 仅用于解析 JS 语法树，不会执行游戏中的 JavaScript。

```powershell
.\.venv-rpg\Scripts\python.exe RpgApp.py
.\.venv-rpg\Scripts\python.exe RpgApp.py --offline
.\.venv-rpg\Scripts\python.exe RpgApp.py --self-check
```

便携包启动 AiNieeRPG.exe，参数与 RpgApp.py 相同。`--self-check` 在新 UUID 目录中生成合成样例并验证 JSON/JS 往返，不调用模型、不启动游戏。所有检查产物保留。离线启动关闭更新统计；游戏模型请求也被拒绝。

## 游戏汉化流程

1. 选择原游戏目录、新建工程目录。工程必须位于游戏目录之外。
2. 扫描并创建项目，再提取文本。扫描记录每个文件的 SHA-256，并保存可改文本文件快照。
3. 查看摘要和问题。未知控制符所在单元会保留、显示问题并从模型批次中排除。
4. 点击“送往 AiNiee 翻译”，在接口管理中自行配置所使用的服务，再开始翻译。接入沿用 AiNiee 的请求器、接口角色和术语数据。开发验收使用模拟响应，没有调用用户模型账户，也没有验证真实翻译质量。
5. 双击单元可以人工编辑和锁定。编辑冲突会被拒绝；需要刷新后重新判断，不会自动采用过期编辑。
6. 必要时配置支持简体中文的字体。目前自动替换副本字体支持 MZ。字体复制到工程，再写入输出副本的 fonts 目录及 System.advanced.mainFontFilename。字体授权由所选字体本身决定，工具不下载或分发用户字体。
7. 先做测试构建。未译单元保留原文，清单明确列出数量。正式构建要求翻译齐全且可识别的字体覆盖通过。
8. 手动运行输出副本，检查标题、菜单、对话、分支、商店、战斗、自定义场景、存读档。离线校验和哈希通过不代表这些游戏路径通过。

原版、工程、输出父目录必须互不包含。构建使用冻结的 SQLite 快照，写入新的 staging，完成后改名；失败产物保留。原文件变化会中止构建。不会覆盖已有输出。游戏存档、debug.log/error.log 不复制。不要把输出目录放进原版目录。

0.39的新建工程会在summary报告中保存静态识别证据：入口引用、标准文件缺项和
加密状态。NW.js版本在输出副本实际运行时记录，目录识别阶段显示未测，不从游戏
package版本推断。旧工程未记录的报告仍明确标为未记录，不会自动改写。
构建/后端按钮提示资源基线大小；Stev还会保留一份完整工作副本。执行前请同时检查
工程盘和输出盘可用空间，另留快照、字体/图片、暂存和历史目录空间。工具不会自动
批量清理，已经失败的工作目录也会保留。详见SCAN_EVIDENCE.md。

## CLI

源码命令前缀为 `.venv-rpg\Scripts\python.exe -m Tools.rpg_pipeline`；便携包使用 `AiNieeRPG.exe --cli`。

```text
capabilities
scan --source GAME --project-root PROJECT
extract --project PROJECT [--profile PROFILE.yaml]
summary --project PROJECT
export --project PROJECT --file NEW_FILE.json
import --project PROJECT --file TRANSLATIONS.json
validate --project PROJECT --offline
font-check --project PROJECT --font FONT.ttf [--include-source]
font-set --project PROJECT --font FONT.ttf
build --project PROJECT --output-root OUTPUT_PARENT --test
verify --build OUTPUT_COPY --offline
resume-build --project PROJECT --build-id BUILD_ID
resume-validation --project PROJECT --job-id PREVIOUS_JOB_ID
resume-extract --project PROJECT --job-id PREVIOUS_JOB_ID
jobs --project PROJECT
recover --project PROJECT
resume-scan --project PROJECT
job-control --project PROJECT --job-id JOB_ID --action pause|resume|cancel
migrate --old-project OLD --project NEW [--apply]
migration-review --old-project OLD --project NEW [--confirm-lineage]
migration-apply-review --project NEW --plan-id ID
backend-check --project PROJECT --backend stev|rpgmtl|sextractor --backend-root TRUSTED_TOOL_ROOT --relative-path data/Items.json
backend-candidate --project PROJECT --backend stev|rpgmtl|sextractor --backend-root TRUSTED_TOOL_ROOT --relative-path data/Items.json
backend-route --project PROJECT --backend native|stev|rpgmtl|sextractor [--backend-root TRUSTED_TOOL_ROOT] --relative-path data/Items.json
backend-audit --project PROJECT --candidate NEW_BACKEND_OUTPUT
tpp-probe
tpp-export --project PROJECT [--open]
tpp-import --project PROJECT --binding BINDING_ID [--file SAVED.trans]
patch-export --project PROJECT --build VERIFIED_COPY --file NEW_PATCH.zip
patch-apply --source ORIGINAL_GAME --patch PATCH.zip --output-root NEW_OUTPUT_PARENT
images --project PROJECT
image-preview --project PROJECT --relative-path img/titles2/Command_0.png_
image-ocr --project PROJECT --relative-path IMAGE_PATH --executable TESSERACT.exe --tessdata TESSDATA_DIR [--language jpn+eng]
image-regions --project PROJECT --relative-path IMAGE_PATH --source-sha256 SOURCE_HASH --file CONFIRMED_REGIONS.json
image-base --project PROJECT --relative-path IMAGE_PATH --clean-base CLEAN.png --font FONT.ttf
image-render --project PROJECT --relative-path IMAGE_PATH
image-approve --project PROJECT --relative-path IMAGE_PATH --sha256 PREVIEW_ASSET_HASH
```

导出应选择工程或其他工作目录中的新文件，禁止写入原版。完整导出保留 unit_id、source_hash 和 expected_revision，请勿删除这些列后用于覆盖旧版本。

迁移要求同一游戏身份可确认、原文与控制符解释一致。完整位置匹配或同文件/场景内
双向唯一锚点的索引移位可复用；说话人、命名字段、作用域和关联位置数量仍需一致。
已有目标译文、锁定、原文变化和歧义都不自动覆盖。报告列出复用、新增、修改、孤立、
冲突；没有旧译文也会列入不可复用诊断。默认只生成方案，`--apply` 才提交。
缺少可验证 game_id 时不自动应用；当前迁移目标语言限 zh-CN。图片文本可复用，
但预览仍需在新工程重新生成和批准。具体证据见 MIGRATION_V2_EVIDENCE.md。

兼容工具只在新子进程中调用单文件内存 API。只读比较、多后端候选回写和逐文件构建
路由均已接入；默认使用原生后端。第三方多提取的 note、资源或逻辑字段不会自动成为
翻译单元。GUI“文件回写后端”或 backend-route 可选择后端，先验证实际候选，再固定
源码指纹。任一定位、原文、工具源码或输出差异校验失败都会阻止构建。具体版本和
能力与限制见 BACKEND_EVIDENCE.md。CommonEvents 可逐文件验证后选择 RPGMTL。
0.13 增加指定 JS 文字的 RPGMTL 候选：仅列出工程中已有批准文字的 JS 文件；Stev 和
SExtractor 在此处不可选。先验证每个已接受译文的位置，再检查 AST、译后字符串值及
批准区间外的字节；失败会保留诊断并拒绝构建。js/plugins.js 注册表仍由原生规则处理。
JS 的引号和转义写法可能变化，运行时字符串值必须一致。比较提取功能目前仍只处理 JSON。

## Translator++

官方 8.8.9 安装器为 `Tools/install_translatorpp.ps1`，下载并核对固定 SHA-256，安装到
独立 `.tools` 目录；需要本机 7-Zip。`Tools/start_translatorpp.ps1` 启动此实例，
`-Headless` 用于本地 API 测试。不会安装或连接翻译服务账号。

游戏页面可“导出 .trans”，用 T++ 打开后编辑保存，再选相同交换批次并从文件导回。
T++ 已运行时也可“导出并送往 T++”及从运行实例导回。导回前先保存当前 T++ 工程；
推送会把该实例的当前编辑工程切换到新交换批次。

相同原文按独立单元保留。原文、单元 ID、交换批次不可改动；过期译文会保留为冲突，
需要重新导出后处理。T++ 交换仅负责编辑译文，游戏副本仍通过 AiNiee 构建。已测版本
的原生导出存在地图指令丢失样例，不能直接替代本工具的结构审计。详见
TRANSLATORPP_EVIDENCE.md。T++ 安装文件不随便携包分发。

## 变更补丁

`patch-export` 只把已核验副本中的变更文件打包，并附带所需来源文件的路径、大小和
SHA-256。`patch-apply` 会核对完整来源文件集合及哈希，写入新的独立副本，再生成构建
清单。它不会在原版目录内打补丁，不覆盖已有副本。来源不匹配、归档成员越界、重名、
内容或大小校验失败均会被拒绝。失败目录保留。

补丁未压缩的变更总量上限 256 MiB，所需来源总量上限 16 GiB，每类文件清单上限
50000。补丁可能包含完整的已变更 JSON/JS 或图片，发布前需自行判断内容授权；软件
不会自动上传补丁。哈希用于一致性和版本核对，不构成发行者身份认证。

## 图片文字

主页面“图片文字…”按顺序提供图片选择、只读预览、可选本地 OCR、区域校正、底图/字体、
翻译预览和批准。确认区域后先返回主译文表填写图片单元译文，再进入图片窗口继续。

OCR 需独立安装 `Tools/install_tesseract.ps1`（需要 7-Zip），在窗口选择其 tesseract.exe
和 tessdata 目录。OCR 可能漏字或给出过紧的框，必须校正原文、坐标和字号。它不会自动
生成翻译单元。区域 JSON 的 box 是 `[x,y,width,height]`；已生成的 region_id 请保留，
用于稳定关联旧译文。例：

```json
[{"box":[0,0,180,40],"text":"START","font_size":24,"color":[255,255,255,255],"align":"center"}]
```

先用图像编辑器准备擦除旧字的 PNG 底图，保留尺寸与框外像素，再选择单个 TTF/OTF
字体。工具会拒绝框外变化、缺字或文字溢出。它提供框内叠字，不提供复杂背景自动修复。
目视核对翻译预览后明确批准，构建才会采用；修改任何译文或设置后需重新生成并批准。
输出保留资源名和 PNG/MV/MZ 加密扩展。当前不支持 JPG、rxgc2、TTC、动画 PNG。
版本、实测证据与边界见 IMAGE_EVIDENCE.md；OCR 引擎和游戏字体不随软件包分发。

## Stev目录构建（0.21）

Stev源码目录必须同时含jtpp.py和config.yaml。选择该文件回写后端后，构建会将完整游戏
清单复制到工程work，再运行真实目录提取/注入；需要额外工作空间和准备时间。单文件
候选通过后，整个目录仍需在构建中独立审计。修改源码或config.yaml后重新生成候选并
选择路由，旧Stev路由不能沿用。无译文时请明确使用测试构建。

同文可按不同位置写入不同译文。合并/不明地址和空译文拒绝；未知字段不自动取得翻译
权限。重复JSON键的文件只作发现，不接收Stev写请求；未选定文件在成品保留原字节。
工作目录及失败现场保留，暂停在worker边界生效，运行中取消会结束所属worker。
范围与实测见STEV_PROJECT_EVIDENCE.md。

## 中断与问题处理

- 比较后端提取：主页面点击“比较后端提取…”，选择文件、后端和已安装源码目录。
  比较结果显示覆盖计数并保存报告；额外项需要核对显示用途，当前译文与回写后端保持。
  比较任务支持暂停、继续和取消，CLI可用 `backend-check`，报告见 BACKEND_COMPARISON_EVIDENCE.md。

- 迁移旧译文：迁移窗口可暂停、继续、取消或“恢复未完成的迁移…”。取消保留已提交
  译文，恢复先核对原对账和未提交条目的修订。来源、规则或待提交条目改变时重新生成
  对账；已提交条目的后续人工编辑和锁定保留。CLI 可用
  `resume-migration --project PROJECT --job-id ID`，详情见 MIGRATION_RECOVERY_EVIDENCE.md。
- 工程锁冲突：等待当前工程操作完成；不要删除运行中的锁文件。
- 来源发生变化：创建新版本工程，再迁移可确认的旧译文；不强行修改旧快照。
- TOKEN_MISMATCH：修正译文中的控制符、变量和模板占位符；不会由模型猜测修复编号。
- FONT_GLYPHS_MISSING：更换覆盖相应字符的字体，再检查副本实际显示。
- 进程意外退出：`recover` 将遗留运行任务标为 INTERRUPTED；重新提取或从 SQLite 中已有译文继续。未完成目录不会作为成品；有 journal 的构建可明确选择“恢复构建”，逐文件核验后复用。
- 暂停/取消：在安全检查点执行；最终 COMMITTING 阶段不再接受控制请求。扫描中断可恢复，详情见 JOB_RECOVERY.md。
- 所有日志、工作副本、真实游戏快照、模型响应和 Worker 记录保留在本地 work 目录。不会上传到仓库，也不包含在便携包中。
## 0.10 指令定位与旧缓存

主页面“问题历史”上方选择“定位事件指令…”，或双击未支持指令问题，可筛选文件、事件、
插件和参数原文，查看精确 JSON 指针。待审字段可能是逻辑值，此窗口只读；新增提取规则
仍须检查实际显示消费者。CLI 使用 `--cli command-audit --project 工程目录`，返回本地报告。
盘点可暂停/继续/取消，中断后重新开始。报告含原文，请按私有工程材料保存。

本版拒绝普通字符串回写器修改事件脚本和调用身份。旧算法尚未完成的提取/构建需要重新
开始，不能继续复用旧缓存；现有工程和已完成成品可继续读取。受限 code122 字符串和
已核验的357显示字段正常使用。范围见 COMMAND_AUDIT_EVIDENCE.md。

开发者运行测试请使用 `Tools/test_rpg.ps1`。脚本为每轮创建新的pytest临时目录并保留
产物，不使用pytest的旧目录轮换清理；已有路径冲突会拒绝。不要用已有目录作basetemp。
安装版T++实测需其API在运行，可先执行 `Tools/start_translatorpp.ps1 -Headless`，再用
`AiNieeRPG.exe --cli tpp-probe`确认8.8.9。详情见COMPARISON_REVIEW_EVIDENCE.md。


## 游戏工程身份与重置后的重载（0.23）

身份信息缺失或不一致时，编辑、重置、表格任务和输出会拒绝操作，请在游戏汉化页
重新打开正确工程，再点击“送往 AiNiee 翻译”。不要通过改缓存root或工程ID绕过检查。

若提示“状态已保存，请重新加载”，说明重置已写入工程，后续缓存视图刷新未完成。
已有译文和人工锁仍保留；按上述步骤重载即可恢复规范状态。重载前旧视图不能继续
执行游戏写入/输出任务。普通保存失败会另行显示错误，不应把两种情况混同。
