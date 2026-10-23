# 场景上下文与每轮工程图准备

2026-10-19，0.23源码增量，Codex独立审查。完整计划仍未完成，D02保持部分实现。
本记录不能代替真实模型、自然游玩或新冻结程序验收；0.22封存包保持原样。

## 实现边界

- GameBatchPreparation每次准备轮次读取一次完整图、检查一次写入所有权。元数据和图在
  同一SQLite读取事务取得；保留工程OS锁，同时覆盖直接ProjectStore写入者的并发。
  主翻译、校润和表格操作共享本轮对象，新轮次重新创建，不存全局缓存或信任标记。
- root、工程身份、dataset、profile、token、目标语言、schema/features、adapter签名在
  每批准备、请求之前和提交之前复核。译文、人工锁和revision每批重新读取，保留既有
  source/CAS/控制符/取消/租约与逐项提交边界；不因人工改译使来源图缓存失效。
- 从完整文件的规范单元顺序划分连续scene区段，包含空scene和a/b/a。增量提取保留的
  全局seq可能交错文件，因此先按主文件分组；快照查询和批次单元均返回独立副本。
- 只读前文使用pre_line_counts或polishing_pre_line_counts，默认10、上限32；后文
  game_following_line_counts默认3、上限8。来源是规范源文，包括已译/锁定邻接单元，
  传入previous_items也必须通过root、ID、source_hash、区段和先后位置校验。
  “前后”表示源文件顺序，不保证条件分支的实际执行顺序。
- 仅101、连续401、紧接102且层级一致时，原生提取器保存choice_question_pointers。
  不靠日文语义、最近台词或选项文字猜测所属问题；嵌套选项各自解析。stable ID、
  source hash与可写occurrence不变。原生adapter升为1.1.0，提取checkpoint算法升为
  rpg-extraction-choice-context-v3，旧算法中断记录明确拒绝复用。
- 参考消息与最后一条待译ID字典分离。每条参考源文最多2000字，前后文/问题合计最多
  6000字，问题最多8条；仅参考可截断，目标文字及控制符不截断。参考ID不要求返回，
  多返回参考ID仍拒绝；marker指令只约束目标text。requested/reference/output/reusable
  分项估算，完整请求含全部消息与system，实际限流路径使用安装的tokenizer。
- 校润必须有当前source_hash对应、非stale、非空且确定性检查通过的有效译文，否则
  POLISH_SOURCE_UNAVAILABLE；不把日文源文伪装成待校润译文。

## 独立检查

先有22项上下文用例（原版21失败/1通过）；提取结构用例先2失败/10通过，再完成
直接提取、服务重提取、旧算法拒绝及真实进程中断恢复，共30项通过。

DeepSeek只修改两个许可源码文件，2400秒时限、751.389秒完成，verified:false；零
guard拒绝、零protocol错误、7个保护文件不变。Codex核对11个after hash、30次公开
源码读取/grep路径，未给worker游戏/凭据输入。Codex承担提取结构、调用入口和测试。

预审另复现三项失败：公开查询暴露可变内部单元、metadata/graph两次读取间混入新版本、
跨文件全局seq导致同文件连续区段误拆。修复后与真实TranslatorTask/PolisherTask、主轮次
准备取消、表格共享、人工原子编辑、ownership和场景旧回归联合79项通过。普通文档
提示词路径另有直接检查，未因游戏参数切换处理流程。

当前游戏的纯原生提取读取并核对178份JSON的hash，与17574个已有规范单元逐一比较
ID/source_hash/occurrence；仅在保留的SQLite副本补入只读context。279个有明确问题
来源的选项实际准备279份请求，验证456条问题参考，目标/参考ID分离。源JSON与主库
hash保持，副本有效译文/锁和jobs不变。该证据是纯提取加副本payload核对，并非完整
GameProjectService重提取、游戏运行、实译或冻结程序验收。

## 实测准备成本

当前17716单元主库只读备份，17687个待译目标、3173批，通过实际
TaskExecutor.translation_start_target准备整轮；完整图与ownership各一次，所有目标
各一次，包含真实tokenizer与上下文。实测16.461秒，不含GUI、投影、配置与过滤初始化，
在调用provider之前停止。另一次协调线程在首批准备后请求取消，主流程0.592毫秒返回；
这是准备边界的受控停止响应，不代表GUI事件或接口等待取消时延。

独立工程图准备415.376毫秒，共享后的20单元构造三次5.187/4.316/3.602毫秒。
暖缓存且未控制OS缓存，32逻辑CPU；当次性能测量未并发运行完整回归。旧版只实测三个
构造（417.4/441.38/444.90毫秒），其全批耗时曾为推算，不能称为实测23分钟或用来
宣称整轮加速比。主库SHA256保持3343edfe…38dae5，副本有效译文与jobs保持，无模型
请求、无游戏启动。

保留本地证据：rpg-context-v23-worker-handoff-audit.json、rpg-context-v23-targeted.xml；
current-question-provenance-v23/8904b1d5cf2947b29ead0301407d205f；
batch-preparation-benchmark-v23/e6a77e9e238840748897f67ea3c7b22a（均在work中）。
完整源码回归600 passed /207 subtests passed，零skip/fail/error，既有依赖警告1；
包含安装版Translator++8.8.9。耗时172.41秒，日志和JUnit为
work/acceptance/rpg-0.23-full-source.log/xml，保留临时目录
9cb9bc8ae72849a9b91d4fbc14502cac。新EXE尚未生成，不以源码代替冻结程序验收。

本轮worker已经终止；按用户随后更新的目标，后续常规实现也由Codex全程接手，不再
启动deepseek-worker。本节保留已发生交接的范围和审计，不作为后续委派安排。

## Codex后续修复：校润完成状态

继续沿真实任务入口检查发现：accepted origin=polish原先仍投影为TRANSLATED，导致
后续轮次继续校润，重建投影也无法恢复POLISHED。5个独立反例全部先失败；改为从
SQLite当前有效译文的origin恢复POLISHED，人工锁优先EXCLUDED，来源stale回到
UNTRANSLATED，新的人工改译回到TRANSLATED。无需新增列或改写译文、锁、revision。
新job即使返回相同文本也正常接受/audit为polish，下一校润轮次不会重新排入。

与真实任务准备/请求联合34项通过。最终源码605 passed /207 subtests passed，包含
安装版T++8.8.9，零skip/fail/error、既有依赖警告1，180.71秒；
work/acceptance/rpg-0.23-full-source-v2.log/xml，保留目录
32f586067e8d4e688cb0095f48d6df97。该检查仍不证明新EXE或真实模型已验收。
