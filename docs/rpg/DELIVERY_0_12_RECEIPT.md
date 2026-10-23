# 0.12.0-dev 本地交付回执

源码94b3ad3；3624软件文件、746源码成员、七项checksum；DELIVERY为ready。
本地目录dist-rpg/releases/0.12.0-dev-94b3ad3，无push、PR或远程Release。

- 便携ZIP253893330字节，SHA-256
  `1a15d309ab213810c49def6fffbf37753c4569c0ca0785bb498ad5806c888d98`。
- 源码ZIP52062625字节，SHA-256
  `7896aecb3d296615c61a5269b182fb0585f62033146cb3c59e2bcec0264a3221`。

G04新增完整原文/locator、原生角色/codec/双hash、实际JSON字段类型冲突和只读查看器。
报告128MiB上限、SHA绑定；SQLite任务仅摘要，CLI完整结果保持。大地址组界面明确
预览前100项，保存报告完整；未知位置不推断类型/权限，旧报告缺信息提示重新比较。
字段类型反例涵盖非字符串和无法解析的指针；400万逻辑引用仅2000次实际解析。

当前游戏四组对照覆盖不变，声明位置类型检查完成且冲突0；meta/译文/路由保持。
最大报告14897800字节、任务结果1053字节，25989行/10个codec筛选及恢复通过。
私有对照work/comparison-evidence-current-game/20d68d9fb993422e93e5d4a293ec228d；
源码Qt大报告截图work/comparison-dialog-current-game/34f26df0b4934d2a9302c3761bed4705。
报告和截图不随包发布。

最终保留式完整回归326 passed / 207 subtests，含安装版T++8.8.9。此前一次API进程
未运行造成的失败、恢复后的专项及最终全量日志均保留。Tools/test_rpg.ps1以新的UUID
basetemp和all策略保留每轮；完整回归及上一轮四个临时fixture均在work中保留。

新解压EXE仅System32 PATH完成4组当前范围验收：自检、17716行GUI/比较窗口、三后端
共享地址/完整注释/紧凑任务/hash与数值字段冲突，以及CommonEvents编解码注释/回写/
上游坏事件拒绝。4000条歧义、2个编码注释和1个真实数值位置冲突均通过。
解压根work/extracted-package-check/c0c17cc6bab2413298d6847ae36e2910。
新窗口合成截图已检查，按钮链和大列表由源码Qt证明；不宣称完整桌面或自然游玩。

23个核心源文件与0.11 f636725逐字节一致，清单在EXTRACTED_PACKAGE_CHECK.json。
旧版本14组恢复/进程故障证据单独保留，不算作本版新EXE重复执行。软件验收后hash
以及旧格式1/profile4只读兼容通过。原9570文件集合/hash与原profile4 DB保持，审计：
work/final-v12-original-audit/c73b31c3d18244178e44ed908404b9a6/result.json。

DeepSeek完成注释纯函数与查看器，guard均无拒绝，受保护文件未变；Codex审查修正并
负责存储、类型核对、GUI接入、独立测试与交付。旧0.11包保留。
当前17项已实现、16项部分实现、H03用户后置；本回执不表示全部A01–H03完成。
真实翻译和其他游戏/版本后置，完整自然游玩、全游戏排版、远程CI和干净机器未验收。
