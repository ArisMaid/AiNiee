# TalkList 字段排除依据（当前0.141）

本次补齐E02此前未决的actor/file/group消费者审查，未开放任何新显示字段。
TalkList.json是999条语音资源索引，不是对话文本表。来源绑定：

| 文件 | SHA-256 |
|---|---|
| data/TalkList.json | 7412147f6780d0fc95de61ccb481eb6d6988f06668661976ee3c9bef59c12966 |
| js/plugins/SH_PlaySEMZ.js | f07ea66c913b899fe8e734e0316d10931a5999248288ca5f4c9768023b096ff8 |
| js/plugins/SH_Consts.js | 5cc86552e8df83f42df7d8ab0bdfbb87ae8bccc9d7b254092755c1bafe07ad25 |

SH_Consts.js:903–905将该文件登记为$dataVoices；全插件目录搜索该全局变量，读取点
位于SH_PlaySEMZ的注册PlayVoice与全局SH_PlayVoice两个入口。未发现向显示窗口的传递。

| 字段 | 实际类型/数量 | 消费者与排除结论 |
|---|---|---|
| id | 999字符串 | SH_PlaySEMZ:164–166、217–219按严格相等筛选；身份键保持 |
| pattern | 533数值、466 null | :168–170、221–223选择指定变体；数值逻辑保持 |
| file | 999字符串 | :180、233组成talk/资源路径，传AudioManager.playSe；文件名保持 |
| actor | 533数值、466 null | 两入口未读取；无显示证据，保持元数据，不赋予翻译权限 |
| group | 999字符串 | 两入口未读取；即使含日文也无显示证据，保持分类标签 |

独立Node VM执行真实消费者源码，使用合成语音条目及引擎/音频stub：两个入口分别选择
talk/fixture-b、talk/fixture-a；Proxy记录只访问id/pattern/file，未访问actor/group。
不存在的pattern拒绝播放。该证据不宣称真实发声或覆盖未发现的动态插件注入。
当前源码SHA变化时应重新审查，不把“此版本未读取”提升为所有版本的通用承诺。

私有证据：`work/talklist-consumer-audit/80c8c1ce2e414190ab1cbe2421007eb8/result.json`。
原文件集合/hash在0.10最终审计中保持。现有提取图与profile规则均不变；源码/便携包
没有加入游戏文件、语音或私有报告。本记录在0.10软件交付后追加，不改变已归档ZIP。
