# 任务、频道与技能提示备注（0.29源码）

2026-10-20，Codex。E03继续补当前0.141真实显示字段；最新封存便携包仍是0.28。
本轮完成源码、实际工程及受控原装引擎验证，不声称0.29新EXE或完整新副本已验收。

## 来源与字段

| 表 / 标签 | 非空值 | 已核查消费者 |
| --- | ---: | --- |
| Items.questText | 34 | Scene_Mission的MissionHelp.drawItem |
| Items.channelName | 8 | ItemSelect的VideoHelp.drawItem |
| Items.channelDesc | 8 | 同上，视频选择详情；不是stream列表 |
| Skills.hint | 100 | Scene_Heart的Window_HeartTalent.makeList，未习得分支 |

Scene_Mission.js SHA为f9c8b33adb7edc9049ae499710105821d6b270b23971c88f62da6f4a81d82280，
ItemSelect.js为fd7b55ce2fee55d4b76d9df02ce79108fbceb3d7b877ad22a45afe392e3b5e66，
均加入profile指纹；Scene_Heart.js已有指纹，保持。只开放以上显示值，数值、任务/
技能标记、频道图片和订阅者数据不变。

34个任务说明中33个有quest标记，100个hint中98个有eroSkill标记；部分数据当前
未启用，8个hint是带颜色控制的问号占位。它们仍是对应显示属性的非空值，不声明
当前每项都可达或需要改字。按SOP保留问号占位；不为当前启用状态新增规则引擎。

## 同一备注的合并写入

8个频道的名称与说明实际共用同一note。复用JSON所有权树，只有profile显式
shared_note的定位附加具体标签地址，允许两个不同值共用外层字符串；完整note、
祖先指针或重复同标签仍冲突。普通单标签备注沿用0.28地址和单元身份。

两个字段在同一个原始note/hash上定位并从后向前合并，生成一次外层JSON叶写入。
部分翻译只改变已接受值，兄弟值保留；标签、其他备注、控制符、换行与数据类型
保持。输入原始note不一致、重复标签或新ASCII尖括号拒绝，不做相似位置恢复。
迁移身份包含具体标签，运行报告也列出note_tag，两个同指针字段不会丢失区分。

新增能力note_tag_groups_v1使用现有格式2门禁，无新表或恢复框架；实际0.28 EXE
拒绝含新能力的工程且DB保持。提取算法v5，写入计划v11；旧未完成操作保留并新建。
当前Items/Skills备注选择原生回写，第三方SDK未获得本轮同等支持声明。

## 已执行的必要验证

从0.28实际EXE验收工程一致备份，真实源码重提取17918→18068单元、18616位置。
旧17918单元完整对象、231接受值/锁保持；150新字段使用人工中性样例，合计381
接受值，非真实模型翻译。原文往返保持Items/Skills字节。

- Items的50个值合并为42个note差异；Skills为100个值/100个note差异。
- 仅批准值改变，遮去这些值后其他每个字符相同；所有其他元数据键和值保持。
- 实际频道一项翻译时兄弟原文保持，两项翻译时均生效；重复同标签、完整note所有权
  冲突、原始note不一致及新分隔符拒绝。已有接受文本保持。
- 两个频道字段的迁移地址不同；实际源码CLI只读报告能精确关联两项并分别给出标签。
- 381人工样例214静态字符缺字0；这不是动态值、回退或完整输出字形通过。
- 没有新增测试套件或重复全套回归。写入边界使用实际数据的最小必要验证。

源码工程、回写与旧包拒绝证据：
work/note-groups-v29/374c6d8debd042e2b303a130206d6d22/的result.json、review-result.json、
cli-result.json及runtime/font-cli.stdout。原0.28种子库保持。

## 原装引擎的三条路径

复用已结束的私有原装Game.exe副本，先保存旧Items/Skills/采集和驱动文件。
换入实际批准JSON，不改变插件或引擎代码；使用复制存档、隐藏窗口和固定tick。

| 路径 | 实际记录 | 已确认范围 |
| --- | --- | --- |
| Scene_Mission | 临时获得并选入原物品1303 | 任务说明实际绘制，1个精确备注关联 |
| ItemSelect.video | 原ItemSelect:video命令，临时获得并选入1282 | VideoHelp绘制名称和说明，2个精确关联 |
| Scene_Heart | 选择talent分类及实际未习得技能1056 | makeList返回hint，1个精确关联，无需授予技能 |

三张截图已目视核对，指定中文样例可读、控制色和动态姓名等仍由游戏处理；进程
均退出0、异常0，读取报告前后DB保持。没有修改技能习得状态，没有保存测试库存。
这不是自然获得/选择路径、所有150项布局或完整BuildService29输出验收。

首轮视频驱动把文件夹路径当作注册名，没有触发命令而超时。核对原PluginCommonBase
后改用实际注册名ItemSelect，只补跑video和talent，未重复已通过的mission。首轮
整体result仍为false；最终closure按三个明确成功case合并，不把失败记录改绿。

私有原生证据在上述目录的native/：

- cf23e75e6625467cb91bc546ebe4fa8c/mission，保留同批失败video。
- fdf650e5d9cd48fdba96a0bbc2487821/video和talent。
- closure.json列出三项来源，截图/实际文字只保留在私有work。

六类标准表的含日文/CJK备注候选从435减为294，逐项位置/hash在
remaining-note-candidates.json；其中还有逻辑和资源配置，不把候选数当漏译数。
E03、完整P0及总目标仍未完成，计划26已实现/7部分/1用户后置保持。后续合并下一批
有依据的显示字段，再做新便携包集成；0.28封存包不包含本轮共享备注能力。
