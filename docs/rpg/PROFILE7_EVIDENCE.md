# 当前游戏 profile 增量7：显示字典与函数内静态文字

2026-10-20，Codex；0.26源码。范围为当前0.141/MZ1.7.0/game_id33872391。
本增量尚未生成0.26便携包；已封存0.25及原游戏、旧主工程保持。

## 字段批准与排除

只读盘点SH_Consts中的对象定义、函数引用、实际公共事件表达式和多层JSON编码的
SceneCustomMenu参数。最终82个非空单元已有提取、存储、回写和消费者证据：

| 来源 | 单元 | 实际消费者与边界 |
| --- | ---: | --- |
| sh_var.result的expStr/getExpStr/getSpStr | 3 | SH_GetBattleResult及SH_MissionResult中的Ticker调用；ID和奖励计算保持 |
| sh_var.strm的channelStr/firstBonusStr/suparChatStr | 3 | SH_NewSubscribers和SH_SuperChat的Ticker；269/395变量索引保持 |
| sh_var.labo各项目的name | 14 | 公共事件1939/1946读取648选择的项目name/price；price与对象键保持；limit的“-”作为显示分隔符按SOP原样保留 |
| sh_var.profile的明确25字段 | 25 | 公共事件16的六项批准默认资料，及SH_MakeProfile的喜欢/技能；变量由Scene_Heart的实际drawTextEx或SH_CM_ProfText布局函数读取 |
| sh_var.heroineStates的字符串base | 4 | SH_HeroineStates→SH_Profile→已启用SceneCustomMenu实际ItemDrawScript→drawTextEx；数值base、skillTag及AltOnly保持 |
| sh_var.heroine四组声望字段 | 31 | SH_NowPopularityRank按0–7索引选择rank/lustRank/reactionRank/badReactionRank；空值跳过，weak/strong等未读字段排除 |
| SH_Profile中args.name模板的静态姓名前缀 | 1 | 同一实际菜单绘制脚本；两次SH_HeroineStates调用和中间空格保持 |
| SH_NowPopularityRank的lastWord静态绑定 | 1 | 原函数组合称号；前、中、尾词组合及条件保持 |

sh_var.profile的prof3_2/prof4_2/title2、未读的后续喜欢/技能/弱点字段均保持候选。
school在原型中曾纳入，复核只证明赋值变量282，尚无显示消费者，因此最终移回
候选；不以字段名称或日文检测授予回写。profile准确列出25字段；声望规则准确列出四组32键，其中一项
空字符串不生成单元。heroineStates只选字符串base，不选技能标签或数值。

消费者原代码未定义cond.bad_popularity0–7，不能把源函数的全部坏声望索引当作当前
默认运行分支已通过。本轮未修改该游戏逻辑。Node消费者证明用显式合成阈值运行
原函数的八种字段选择；原装引擎只观察默认rank0/lustRank0，其他状态仍需后续运行。

新增SH_BenriCommands、SH_AltMessageAndWindow、SceneCustomMenu和Scene_Heart消费者SHA指纹，
定义文件、SH_BenriFunctions、SH_GameSystemParam、CommonEvents、plugins.js沿用
已有完整指纹。详细原文/完整配置和片段仅保留本机work，不进入源码/软件归档。

## 具体实现

80个字典值完全复用现有对象路径和property_fields。另给现有函数作用域规则增加
static_text:true：只选择明确函数直接绑定的静态字符串，或明确对象字段的模板静态
片段；不递归进入模板表达式、回调、带标签模板或任意调用。

沿用JS UTF-8字节范围、原文件hash、独立AST及非批准字节审计。模板片段标记为
node_kind=template-part；编码时转义反引号、反斜杠、换行及`${`，不重写动态表达式。
姓名前缀的两个演员读取调用和称号的组合计算均保持。没有新增物理表或通用JS执行器。
新能力js_display_fragments_v1由profile/单元存储自动声明；0.25实际EXE明确拒绝，
工程数据库hash保持。老工程用当前源码新提取，旧中断提取不续用。

人物反应中的`{self}`等已有模板占位符由既有TokenPolicy保护，不扩展保护框架。
六项原有实际换行使用已有preserve_newlines约束。实验室分隔符的原样保留采用SOP，
不建立新的符号分类或强制复制状态。

RPGMTL普通字符串实际写回80项通过，AST、逻辑值及所有非批准字节保持。其转义形式
与原生编码可不同，因此不声称整个文件字节相同。含模板片段的JS文件本版要求原生
回写，第三方候选在调用SDK前明确拒绝，不自动降级或增加未验证兼容层。

## 已执行的实际流程

- 当前两份JS经真实提取→SQLite人工锁定中性中文样例→原生回写→重新提取，82单元
  的ID和值一致；原有136个JS单元保持，零翻译字节一致，写入所有权无重叠。
- 全文件AST/非批准字节审计通过；含反引号、`${...}`、引号、反斜杠和换行的前缀
  保持文字，实际函数执行未产生注入。改动未批准的动态表达式由独立审计拒绝；
  删除已有`{self}`的人工提案被拒绝，旧接受值和人工锁保持。
- 消费者Node VM执行实际奖励/直播/资料/声望函数、任务提示语句、28次实验室表达式
  和真实菜单参数绘制片段；另执行Scene_Heart实际绘制语句及SH_CM_ProfText布局函数。
  批准资料25字段读取集合与profile一致，school保持候选，计数器/价格保持。
  使用引擎stub与合成状态，不作为原装引擎或自然玩法证明。
- 完整当前工程SQLite备份实际EXTRACT任务：17730→17812单元，18278→18360位置；
  全部旧单元完整图、29条译文/锁、9570文件表及来源manifest保持。原型83条的任务
  已完成并保留；复核排除school后，按实际规则变更发起新提取验证最终82条。
  新82在该完整备份中未翻译；中性样例只在独立子集/运行副本中。
- 旧0.25程序拒绝新能力，数据库保持。最初私有驱动只检查stdout，而CLI正确把拒绝
  放在stderr，故断言失败；核对后复用COMPLETED提取结果审计，没有重跑提取。
  RPGMTL最初私有断言错误要求与原生全文件字节相同；独立AST/批准范围审计已经通过，
  后续明确区分合法编码差异并复测该单个SDK调用，未改产品规则放宽未批准字节检查。

## 原装引擎显示范围

独立复制已核验0.25测试构建，使用0.26源码回写器将新82中性样例与已有译文合并到
两份JS。运行游戏自带Game.exe/NW.js，复用已验存档、隐藏tick及受控入口，退出0。
不是0.26 EXE、0.26完整BuildService构建或自然用户流程。

| 观察项 | 结果 | 限制 |
| --- | --- | --- |
| 姓名前缀+昵称+姓名 | 实际菜单ItemDrawScript在原生Window_Base绘制，24号字、324px/660px | 新建测试窗口，非完整Scene_Menu2打开路径 |
| 直播提示与投币提示 | 调用实际SH_NewSubscribers/SH_SuperChat，原生Ticker为215px/111px，计数100→115 | 真实项目1501、受控变量状态，不代表完整直播自然流程 |
| 声望称号尾词 | 实际SH_NowPopularityRank(0,0)输出并由原生drawTextEx绘制，216px/660px | 非原SNS窗口/全部条件分支 |

三张窗口截图已人工查看，示例文字无可见缺字、截断；字体状态loaded，无捕获异常。
不把这些少量中性样例扩张为全部82文本、全游戏排版或DeepSeek语言质量验收。
原型83的截图/报告/两份JS另存保留，最终82只复用已退出的仪器副本，更新两份JS，
没有重复复制整个游戏或删除旧现场。最终三组显示复测及截图查看均通过。

证据位于work/sh-var-inventory-v26/0cfb87f9cb7448819e225bdf4b45a5d9、
work/profile7-source-v26/8e96770cb5d64da8b3ea0d4a117fae8b、
work/profile7-current-project-v26/6ee3fb2cec54479384163299a417419f、
work/profile7-rpgmtl-v26/3dd095e20ef04fbebeca24b29737d101及
work/profile7-native-v26/2918ed1c725d429aa7b385e464d65928的result.json。

本轮未新增单元/回归测试或重复整套；未请求模型、启用编码worker/子代理、批量删除
或公开私有素材。其他动态脚本、序列化插件参数、完整字体/布局和自然路径继续推进，
E02/E03、完整P0及总目标保持未完成，任务统计仍24/9/1。
