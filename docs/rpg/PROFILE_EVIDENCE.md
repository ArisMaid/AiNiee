# 当前体验版 profile 的源码证据

来源是用户本地 0.141 目录，未将游戏脚本或台词复制进仓库。仅记录字段和调用位置。

| 规则 | 已只读核对的消费者 | 保留边界 |
|---|---|---|
| RandomTalk.message | SH_Sandbox.js:40–64，generateRandomMessage 读取 message 并组成显示消息 | id、pattern、voiceId、tickerType 与 help 暂不翻译 |
| EroText.message / messageCloth | SH_BenriCommands.js:627–635，替换 cloth 后交给 $TM.show | `{cloth}` 属于保护占位符；分类和数值不修改 |
| CommentList.comment | SH_BenriFunctions.js:2599–2620，按 type 选择 comment 并用于显示变量 | type 保留 |
| HandleName[i][0] | SH_BenriFunctions.js:2622–2626，SH_RandomHandle 取数组首项作为名称 | 数组形状、索引及其他列保留 |
| SH_NpcName.name / nickname / ship | shimo/SH_GameSystemParam.js:374–394，用于 setName/setNickname/setProfile | name 匹配 actor[数字] 时是引用，过滤后保留；对象键不修改 |
| UniqueParams.name | selenoxia/Scene_Equip.js:209，用于显示属性名 | id、varId、menu 等程序配置保留 |
| UniqueParams.message | shimo/SH_GameSystemParam.js:1236，用于显示消息片段 | 变量和图标保留 |
| Kd.words | KdConsts.js 定义；Scene_Item/Options/File/SkillTree/Mission 等以 drawText/addCommand 使用 | 只提取对象值；对象键、程序调用和资源均不改 |

SH_Nuiit.message 保留 pending：已确认数据被运行逻辑使用，但显示消费者尚需补齐。
各规则的实际运行验收仍须另记，源码证据不等同于实机通过。
# Additional audited command parameters

These rules are for the fingerprinted 0.141 game only. Code 357 args at
parameters/3 are keyed by plugin + command; resource/logic arguments remain excluded.

| Rule | Display consumer in private source |
| --- | --- |
| Ticker.show text | Ticker.js:270-271 -> TickerManager.show |
| SH_BenriCommands.uniqueComment comment/uniqueName | SH_BenriCommands.js:792-804 -> LCM.add |
| AddChoise / AddChoiseSimple text | SH_BenriCommands.js:715-739 -> SH_AddChoise |
| SH_ChoiseResouce text | SH_BenriCommands.js:968+ choice text construction |
| SH_BenriCommands2.AddRandomMessage text | SH_BenriCommands2.js:171-190 -> converted message queue |
| DTextPicture.dText text | DTextPicture.js:247-248 -> setDTextPicture |
| selenoxia/LiveComment.add text | selenoxia/LiveComment.js:106-107 -> LCM.add |

NN is resolved to actor.nickname by SH_GameSystemParam.js:1642. CRB/CRW
are color substitutions at 1621-1622. COMMON is resolved by SceneGlossary.js:2350.
Brace placeholders such as {2ndName1} are preserved, including numeric first characters.

## Choice condition expressions

MPP_ChoiceEX.js:653-680 removes lowercase `if(...)` / `en(...)` expressions from
choice labels and evaluates their contents against switch/variable data. TokenPolicy
v2 protects the complete expression as one opaque token, including an optional
legacy backslash. It follows the consumer's first closing parenthesis semantics;
the model never sees or rewrites the condition. A real Map175 choice and synthetic
plain/escaped variants were checked. Re-extraction leaves 14 units blocked on
unresolved `\R`; no guessed reset-code rule has been enabled.
