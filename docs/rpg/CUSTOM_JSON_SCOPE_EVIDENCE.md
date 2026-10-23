# 当前自定义 JSON 字段收口（0.31源码）

2026-10-21，Codex。范围为计划§9.2中的当前0.141自定义表、资源配置和E02任务。
按字段批准/排除、消费者和正反例对账，不再用“可能还有其他字段”作无界完成条件。
不把E02收口扩大为所有JS动态文字、全部运行分支或其他版本通过；这些各有任务。

## 当前文件与提取图

以0.30实际新EXE工程的一致快照、同一完整输出和当前profile逐位置比较，记录来源
SHA与规范profile hash。每个批准非空值与实际单元原文/指针一致，没有额外或缺失
位置；输出的非批准JSON值保持。统计包括英文显示值，不以日文检测决定权限。

| 文件 | 当前记录数 | 批准非空显示位置 | 逐项保留边界 |
| --- | ---: | ---: | --- |
| RandomTalk | 690，含null | 686 | id、tickerType、voiceId、pattern、help；3个空message |
| EroText | 170，含null | 159 | id、extasy、cutInType、part、cloth、exp、tickerType；空消息 |
| HandleName | 160 | 160 | 只选每行索引0，形状/索引保持 |
| SH_NpcName | 117 | 262 | 分组键及3个actor[n]引用；空名称/称号/关系 |
| UniqueParams | 105，含null | 108 | id/varId、数值/布尔配置与comment；104个unit当前全空 |
| CommentList | 93 | 73 | type及20个空comment |
| SH_Nuiit | 118 | 233 | tag、2个[なし]及空消息；[word]和检索零语义保护 |
| TalkList | 999 | 0 | id/pattern/file语音索引，actor/group元数据 |
| BgmList / BgsList / BgvList / SeList | 84 / 47 / 109 / 104 | 0 | 资源键、音频文件与参数映射，整份保留 |
| ItemCreateData | 1 | 0 | id/price、材料数量与item/armor类型代码、目标ID |

八类自定义表合计1681个显示位置。其余数据不是“漏提数”；三条角色引用和两条
精确哨兵是已选字段内的正式排除，其他列根本没有显示写入权限。所有表与当前
完整输出逐值核对，只有EroText的1个既有人工样例和SH_Nuiit的2个既有样例发生
显示值变化，其他已批准但未译位置继续保留原文。不能以未译等同提取缺失。

dataEx另有TrpParticles和TrpParticleGroups两文件，分别11组/1组；总计73个
字符串叶，均无CJK，另有数值、布尔与null。TRP_ParticleMZ/Group将它们注册为
粒子/指令配置，Editor写回也引用同一资源。当前不是玩家剧情文字表，不开放
配置键/资源名；源及完整输出的整文件字节相同。不是按“没有日文”普遍豁免资源。

## 消费者与正反例依据

| 领域 | 实际来源链 | 边界证据 |
| --- | --- | --- |
| 随机消息 | SH_Sandbox.generateRandomMessage；SH_BenriFunctions.SH_GetRandamTalk→实际公共45脚本及Map122 | 只显示message，tickerType分派；原help读取Proxy反例、当前图与非显示列保持 |
| 条件消息/衣物 | SH_BenriCommands.RandomEroAction取message/messageCloth，替换{cloth}→原Ticker | id/part/cloth/cutInType是筛选、计算或资源选择；数值不改，{cloth}保护；0.30实际衣物消费者与原字段差异记录已验 |
| 随机用户名/评论 | SH_RandomHandle取首列；SH_RandomComment按type筛选；uniqueComment/randomComment组装文字交LCM | 已追踪调用中用户名用于显示及显示变量，不作资源文件或外部身份键；type不改，无同文自动合并 |
| NPC显示名 | shimo/SH_GameSystemParam.SH_npcName按分组键读取name/nickname/ship，交setName/setNickname/setProfile | 精确actor[n]是演员引用，服务提取正式过滤3个；分组键保持；当前其他非空显示值有定位 |
| 自定义属性 | SH_AddParameter显示name/message；Scene_Equip显示name；SceneCustomMenu Scene6/states2读取unit | id/varId/menu/max等用于运算/筛选。现有真实配置片段已验证非空单位绘制、空值不绘制、menu=0不绘制，comment未读 |
| 手机随机消息 | 原tag筛选/SH_GetNuuitData→公共1968→SH_Nuitter→DTextPicture | tag保留；[なし]/[stamp]排除、[word]保护及searchWord数值零类别保持；0.30完整输出真实9条池抽样和模板显示已验 |
| 语音和音频 | TalkList→PlayVoice；其余四表→loadBgmData/SH_LoadBgsFile2/SH_LoadSeFile→AudioManager | 名称用于资源寻址。语音两入口真实源码VM读取仅id/pattern/file，错误变体不播放；全部配置输出保持 |

以上源码消费者均来自当前捕获源并有hash，已有VM记录的源文件重新核对一致，
没有重复运行旧用例。这里只依据已追踪的当前入口批准/排除，不证明未来版本或
任意动态注入永远不读取元数据。UniqueParams.comment的两条非空文字、RandomTalk
help及语音group等按已审查范围保留；不存在“因为含日文就送翻译”的分支。

现有消费者基础见PROFILE_EVIDENCE.md、E02_REMAINING_FIELDS_EVIDENCE.md、
TALKLIST_EXCLUSION_EVIDENCE.md和NUIIT_EVIDENCE.md；旧文档中的pending与计数是
当时阶段快照。0.30原装显示/运行另见NOTE_FOLLOWUPS_EVIDENCE.md及
FULL_OUTPUT_RUNTIME_EVIDENCE.md，不把静态或VM证据替代原装运行。

## 补齐单位默认规则

计划要求逐项核对显示单位，实际消费者已明确，但原默认profile漏了unit规则。
0.31只增加parameter-unit：data/UniqueParams.json的/*/unit，复用既有JSON选择、
存储、提交、原生回写及当前SceneCustomMenu/插件参数指纹。不增解析器、格式、
能力标记、底层约束或恢复机制；提取v6和写入v12保持，由profile hash区分输入。

一次必要的源模式冒烟使用当前规则和两条属性数据：非空unit产生单元，空unit不
产生；ID、menu、varId、comment不成为单元。原文整字节往返、人工提交/锁、真实
BuildService构建及独立verify通过，只有/1/unit由“点”变为“点数”，所有兄弟
字段保持。这是字段/写入边界证据，不是当前游戏存在非空单位或已验其全体布局。

当前完整工程另作一致备份，实际默认重提取约10.51秒。18386完整图、716接受记录
及锁、16个属性名称原文锁、文件表、来源manifest、字体及能力列表全保持。104个
unit均为空，所以没有人为制造新待译单元。新规范profile hash为
f91f687bac9337f7ae55203d04dd6fa923707609ddcfc842a14eb6de42b902d0。
0.30工程、原主库及封存输出保持；尚未生成0.31便携包或新完整游戏副本。

此字段增量验证时为0.31源码候选、当时冻结交付为0.30；后续0.31冻结见
DELIVERY_RECEIPT_0.31.md。旧版在默认规则里没有单位项；
需要该项时使用后续包含规则的版本，或显式选择新版profile，勿手改已登记源快照。
单位布局继续遵循简短用词与具体窗口检查，当前不因空字段补做全游戏运行。

## 注册对账、结论与证据

174条插件登记中168条启用，仍符合计划基线。selenoxia/Scene_Mission重复登记，
所以168条对应167个不同启用脚本文件，不是漏扫描。没有为此重写注册表、加载顺序
或去重原游戏配置。消费者查找另包含178份data JSON与解码后的启用插件参数，
不能漏掉参数内的SceneCustomMenu显示脚本。

E02按原任务“当前游戏各自定义JSON消费者跟踪与profile、字段批准/排除依据与
正反例”已实现（源码与当前0.141字段范围）。不以unit全空替代非空行为证据，也不
把其他JS来源、图片或未来游戏交给此任务无限扩张。E03仍有明确待补字段，例如
SH_EventExp中的固定Ticker显示提示，尚未据此次盘点宣布已支持。完整P0/profile
和A01–H03仍未完成，当前28已实现/5部分/1用户后置。

私有证据：

- work/e02-current-scope-v31/4e14590da7aa4d29a28cdd682ddf62ec：十三表、图/输出对账，消费者及参数定位、dataEx与历史消费者源hash复核。
- work/parameter-unit-v31/bc07e1b367144f898a212dadcb6ff8ff：非空/空单位及实际构建，只改变一个unit叶。
- work/e02-profile-current-v31/c430e77dd62f4ddebbbf7181433bed92：完整当前工程重提取与716记录/锁保持。

私有驱动初次将规范profile摘要当作原YAML文件SHA比较；按既有ExtractionService
的规范JSON摘要核对后通过。单位驱动初次在完成构建后调用不存在的service.verify，
改用已有BuildService.verify，直接复用完成的提取和构建，没有重跑或改产品绕过。
初次记录保留，错误不计为游戏缺陷。没有新增单元/回归套件、整套重复、模型请求、
编码worker、批量删除或私有素材发布。
