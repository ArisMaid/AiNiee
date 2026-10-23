# 当前游戏的 Stev / SExtractor 回写验收

本页保留 0.19 的历史证据。0.20 的 SExtractor 真实主入口及 G03 状态见
SEXTRACTOR_MAIN_EVIDENCE.md 和本版回执；旧透传/内存限制不作为新回写契约。
0.21 的 Stev 整目录构建入口另见 STEV_PROJECT_EVIDENCE.md；本页旧单文档契约不覆盖该路径。

日期：2026-10-19。范围是当前 MZ 1.7.0 游戏的已批准 JSON 位置和人工样例。
真实模型翻译、完整自然游玩及其他游戏另行验收。源码、冻结程序和完整计划状态分别记录。

## 发现与修复

0.18 冻结 EXE 在两个独立工程数据库备份上检查六种当前游戏 JSON。
Stev 六项候选通过；SExtractor 五项通过，System 菜单数组以
`BACKEND_LOCATOR_UNSUPPORTED` 拒绝。该失败保留，没有自动改用其他 writer。

原因是规则转换只查看 JSON pointer 最后一级；`/terms/commands/4` 的最后一级为数字，
因此未启用 SExtractor 的 `commands` 字段。0.19 沿已验证的原文结构寻找最后一个字典键，
数组层不覆盖该键；只增加现有规则可表达的 ASCII 标识符字段。仍由真实上游 ctrl
证明指定完整叶节点的位置，再执行 replaceOnceImp / replaceEndImp。

这不是允许翻译整个数组或同名字段。原生显示权限、原文 hash、唯一位置、译后完整 JSON
差异与来源指纹检查均保留。根数组、数字字典键、不能表达的键仍拒绝，不按字符串相等猜位置。

独立专项测试三项先复现失败，四项拒绝边界先通过；修复后七项通过，连同既有后端与
事件编码测试共 17 项通过。包含同文不同译、嵌套数组、混合字典/数组、BOM、非字符串
保持、未请求同名字段保持、非规范下标及原文不匹配拒绝。

## 当前游戏样例与核验边界

每个后端从同一 17716 单元、29 条已接受译文的主工程备份开始；只在独立副本增加两条
Items 名称人工译文并锁定其中一条。主工程及原游戏不写入；上游 Python 源码集合固定并
在调用前后核验。没有模型请求或游戏启动。

| 文件 | 批准修改位置数 | 类型 |
| --- | ---: | --- |
| data/Items.json | 2 | 新增人工名称样例 |
| data/Skills.json | 2 | 既有已接受数据库文字 |
| data/System.json | 6 | 既有菜单 commands 数组 |
| data/Map023.json | 1 | 已批准事件位置 |
| data/CommonEvents.json | 3 | 已批准公共事件位置 |
| data/SH_Nuiit.json | 2 | 有消费者证据的自定义字段 |

候选阶段没有译文的 Items 使用逐字节透传；这证明无变更路径，不代表运行了上游无变更
writer。批准的 16 个位置只覆盖这些人工样例，不能据此计算全游戏翻译完成率。

完整构建验收使用显式逐文件路由，再执行 `build --test` 和 `verify`，核对六个后端 writer、
上游指纹、实际 sidecar hash、原生批准语义及显式 System 字体改动。未路由 JS 以原生
AST/区间检查核对，图片对已批准字节 hash，字体与映射脚本对明确输入核对。两个后端的
非路由输出须逐字节相同；每个副本检查全部输出文件集合与清单 hash。

原游戏保全核验包含全部 9570 个文件，含构建排除的 debug.log 和 save/config.rmmzsave。
构建输入保护集为 9568；显式新增字体与映射脚本后清单为 9570，另有两个构建元数据文件。
不能把两种 9570 计数视为同一个集合。数据库图、31 条人工译文及锁、主工程 hash、后端源码
hash 均需独立保持。

## 与原开发计划的落地差异

原计划 §14.1 设计整游戏 work 副本 / GameDir / ProgramData 桥接，§14.3 设计包装
main_extract.py。当前实现改用已审计的单文档内存 API：父进程只传原文 bytes 和批准位置，
worker 不接收 GameDir；Stev 读取其真实记录及地址，SExtractor 保存 ctrl 和原格式 sidecar。
新独立进程隔离全局状态、日志和 cwd，父进程验证完整结果后才交给构建 staging。

该实现避免调用上游整目录导入、清理、插件安装及自动修复流程，但不能声称原计划中的
完整 CLI / ProgramData 流程已实现或审计。空 cwd、源码 hash 和输出检查也不是操作系统
安全沙箱证明。G01/G03 继续部分实现；本轮补充当前游戏的受限 JSON L2 证据，未关闭整个任务。
任意正则引擎、其他文件格式、未批准显示字段和跨游戏能力保持原限制。

## 协作与私有证据

使用 deepseek-worker，deepseek-official / deepseek-flash / max，无 maxTokens 覆盖。
单文件任务上限 900 秒，225.767 秒返回修改；一次目录 grep 被 guard 拒绝，结果为
policy_violation，属于失败交接。只修改授权 BackendWriters.py，保护文件 hash 保持。
没有放宽 guard、回滚用户文件或把 worker 的完成文字当验收。Codex 接管代码审查与
独立测试；所有失败、请求、sidecar、输出和原始审计保留在私有 work，不随包分发。

源码实测、最终源码回归和新冻结 EXE 结果以对应交付回执为准；旧版本交付不可据此改写。

完整源码回归为 491 passed / 207 subtests passed，含安装版 Translator++ 8.8.9，
一条既有依赖弃用警告。首轮完整构建驱动误把源码进程 PATH 限制为 System32，已安装
Node 不可见，故两构建以 JS_BACKEND_NOT_READY 失败；保全审计通过，失败 staging 保留。
驱动修正为源码模式显式加入已安装 Node 目录；冻结 EXE 仍要求 System32-only PATH。
该失败不归因于后端修复，也不放宽产品的 JS 依赖检查。
