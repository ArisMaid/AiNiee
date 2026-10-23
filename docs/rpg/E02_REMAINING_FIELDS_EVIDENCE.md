# 当前体验版 E02 剩余字段复核

2026-10-19，Codex。范围限当前 0.141、game_id 33872391。此记录补充字段消费者与排除依据，
不代表 E02、完整 profile 或自然游玩验收已完成；没有更改现有 profile 或授予新写入权限。

## 来源与方法

只读盘点八类自定义 JSON 的字段类型，并解析 plugins.js 中多层 JSON 编码的插件参数；
扫描 178 个 data JSON 的实际文本引用。179 份读取来源的前后 SHA 保持。
没有执行完整插件、加载游戏、调用翻译接口或向编码 worker 发送游戏内容。

消费者验证另在 Node VM 中运行实际配置的筛选/绘制脚本片段、实际随机消息函数和公共事件
655 脚本片段；输入使用自行构造的对象和引擎 stub，Proxy 记录字段访问。VM 不是 OS 沙箱，
该结果不能替代原装引擎画面、完整程序动态路径或自然玩法的证明。

| 来源 | SHA-256 |
| --- | --- |
| data/UniqueParams.json | fbde14b76152a7d8978c4f4f87d9be38cdb07a0cbc93c3dc876972b6812b4252 |
| js/plugins.js | b9cc741342e2d7a2f0b60dc6e00757202504a770a06a6ff59d5bd3531a72938a |
| js/plugins/SH_BenriFunctions.js | badcb342bb94d917d82ab732bac46887c0a898181d514dc9b03e18b344b7b51a |
| js/plugins/SH_Sandbox.js | d51710caaa3fc062ed87661bba5864a56cee511c6a60323db8064151efefc846 |
| data/CommonEvents.json | e8e37bcfee0c74183586fda1259836b03fa3755c0370fc9b7022e7bde48e73dc |

## UniqueParams 的单位、菜单与备注

当前数组 105 项，含一个 null 和 104 个参数对象。

| 字段 | 当前数据 | 消费者与决定 |
| --- | --- | --- |
| name | 104 个字符串，1 空 | 已有 profile 显示字段；保留现有规则 |
| message | 5 个字符串 | 已有 profile 显示字段；保留现有规则 |
| unit | 104 个字符串，全部为空 | 已找到实际绘制入口；当前没有非空文字可增加到待译单元 |
| menu | 104 个整数 | 实际菜单按 menu == 1 筛选；属于逻辑条件，保持数值 |
| comment | 4 个字符串，其中 2 空 | 已核对的该菜单绘制入口不读取；暂不开放，不能推导为全程序永远不读取 |
| varId / iconIndex / min / max / hideTicker | 数值或布尔值 | 变量、图标、计算、显示条件配置；保持类型和值 |
| id | 104 个字符串，含汉字键 | 由参数查找与计算使用；不因包含汉字而成为显示字段 |

单位入口位于已启用的 SceneCustomMenu：Scene6 的 Scene_Menu2、WindowList 第 4 项 states2。
参数真实层级为 `parameters/Scene6/#json/WindowList/#json/3/#json/ItemDrawScript`。
ListScript 读取 $dataParams，FilterScript 检查 menu，ItemDrawScript 在 unit 为真时调用 drawText。
不能把没有搜索到某个 .js 文件中的 `.unit` 当作排除依据：实际消费者存在于序列化插件参数中。

三种实际配置片段验证通过：非空合成单位且 menu=1 时绘制；空单位时不绘制；menu=0 时
筛除。Proxy 未观测到 comment 访问。名称、图标、变量、单位和最大值访问均分别登记。
此证据只解决该入口的来源与分支，未开放任意插件参数文字或通用脚本修改。

后续若开放 unit 规则，须增加正反例、绑定当前消费者指纹并复核 profile/工程兼容；
不能用本版全空字段替代非空回写和实机排版证据。当前提取图和已接受译文不因此改变。

## RandomTalk.help

当前 help 仅有两个字符串记录。已核对两个消费者路径：

1. SH_Sandbox.generateRandomMessage 按 id 筛选、读取 message 并替换后组成显示文字。
2. SH_BenriFunctions.SH_GetRandamTalk 返回条目对象；实际 CommonEvents 第 45 项脚本
   29–31/37–39 以及 Map122 的 event72/page0 脚本读取 message 和 tickerType。

对实际 getter 加实际公共事件 29–31 脚本，以及实际随机拼接函数分别运行合成对象；
help 的 Proxy 读取会立即失败，两个验证均通过。记录的访问仅含 id/message/tickerType。
这支持在这些已追踪路径中保留 help 为元数据，不增加其写权限；不宣称覆盖未来动态注入或
其他版本新增消费者。原有 message 回写权限保持，id/tickerType 等身份和分派值保持。

## 证据与边界

- 字段盘点：`work/e02-field-inventory-v22/ed0bbefdec5a4cac8986e05eb37f2a70/`。
- 实际配置/函数片段验证：`work/e02-consumer-proof-v22/d09842ffc91d4e28979091ab29a5060a/`。
- 来源前后保持；模型请求和游戏启动均为 0。私有脚本、参数片段、台词与完整报告只在 work，
  软件/源码归档不包含这些私有文件。
- 其余 E02 字段、任意动态间接调用、实际非空 unit 回写和完整自然路径仍需各自证据。
  本记录不将候选升级为可写定位，也不改变 A01–H03 完成统计。
