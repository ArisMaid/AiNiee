# 0.10.0-dev 本地交付回执

源码93de66c，3621个软件文件、731个源码成员、七项checksum；DELIVERY状态ready。
没有push、PR或远程Release，旧0.9交付保留。

- 便携ZIP：253861045字节；SHA-256
  `62a7e586e73ae0e1c082d04b6dc41d212402e0507fd6b87a66b0d80919ec072e`。
- 源码ZIP：52029155字节；SHA-256
  `21b6678bad89fd9a7ec6758062822a72a0ce41021b99bf39b2f616c8134ffe80`。
- 本地目录：`dist-rpg/releases/0.10.0-dev-93de66c`。解压运行AiNieeRPG.exe。

新增事件指令只读定位与执行参数回写防护，细节见COMMAND_AUDIT_EVIDENCE.md。
当前游戏153个事件文件/6432指令块全部指针回查一致，17574个JSON单元图不变；
全工程17716单元/18264位置、29条演示译文保持。未进行真实翻译。

源码完整回归294 passed、1 optional skipped、207 subtests；随后安装版Translator++
专项3 passed，补齐被跳过项目，其中2项与完整回归重叠。源码Qt覆盖6101行、筛选、
原文、只读标志、按钮与问题双击路径。

新ZIP解压EXE在仅System32 PATH下完成13组检查，包含四种进程树故障及全部既有恢复
组。新增冻结检查：四处指令块定位、脚本规则覆盖与通用选择器拒绝、两条正常显示字段
回写、逻辑字段保持，以及历史普通字符串脚本译文构建拒绝。两个界面截图已检查；
盘点对话框截图使用合成材料，实际按钮链由源码Qt证明。GUI17716行、122字体家族、
624墨迹像素，Microsoft YaHei UI。

首轮新驱动在第二次导出时复用已有rows.json，被禁止覆盖检查拒绝。修正为新的
legacy-rows.json，只重跑失败组；前12组原结果重新核对，失败日志保留。没有修改产品
检查或重建软件来掩盖失败。最终新组证据：
`work/frozen-command-audit/d57c2f55431f4310b31c5b211c0a889c/result.json`。
解压检查根：`work/extracted-package-check/59c10cfcc86848398267de85e57a9624`。

软件文件验收后SHA保持，旧格式1及profile4只读兼容通过。原9570文件集合/hash和原
profile4数据库不变，最终审计：
`work/final-v10-original-audit/7fc6080a72a84470bf0f1635d589a4e2/result.json`。
DeepSeek草稿交接被目录grep守卫拒绝，记失败；Codex接管审查修正与集成验收。

本回执不表示整个计划完成。真实翻译由用户决定后续交给DeepSeek，多游戏/真实其他
版本后置；完整自然游玩、全游戏排版、独立干净机器和远程CI仍未验收。
