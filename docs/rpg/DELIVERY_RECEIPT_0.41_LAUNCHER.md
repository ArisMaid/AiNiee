# 0.41 启动入口补订交付

2026-10-23，Codex。本地交付目录：
dist-rpg/releases/0.41.0-dev-launcher-44261db。
包装/源码提交44261dbf2519c5ca84c57465e4d5d7bd5dd29d43；
EXE仍来自a1640f997cd57ae92d9c984fe2512f396fb075b9，未重新冻结或构建游戏。

| 交付物 | 字节 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.41.0-dev-launcher-windows-x64.zip | 254448072 | fc98365392f0d08ef29700c4096fa9ca1dbd55e64932a8941ebd7d4fdbb024fd |
| AiNieeRPG-source-44261db.zip | 52678648 | d8a7083c08305edb6b7db601a595a2e6e0c44d56f484243ded385684bb409ab0 |

完整解压到可写本地目录后，双击Start-AiNieeRPG.cmd。日常入口允许模型接口，
保留既有配置/缓存位置；独立离线诊断需显式指定Offline/DataRoot。配置提供商
及模型的步骤仍由AiNiee完成，本轮没有请求真实模型。日志在Logs/launch独立
编号目录；若只出现控制台，保留该目录的startup.stdout/stderr和startup-info。
脚本仅记录已创建进程，gui_confirmed保持false，不替用户确认主界面。

补订只新增CMD/PS1两个文件，更新使用说明、沙盒验收、实施状态和条款复核四份
文档；其余3660份既有文件逐项SHA相同，包括EXE、全部内部运行依赖及profile。
当前软件3666文件、源码908成员，6项封存摘要、ZIP CRC及逐文件hash通过。
软件和源码的游戏内容/私有工作文件/凭据审计通过；原封存0.41的7项摘要保持。

| 本轮验证 | 结论 |
| --- | --- |
| 实际Windows PowerShell5.1语法与三种调用 | 默认、独立离线/工程参数、CMD入口通过；父进程环境还原 |
| 中文/空格/&/!及工程路径尾部反斜杠 | 实际原生参数探针保持，stdout/stderr日志留存 |
| 方括号路径 | 工程参数支持；程序/日志目录明确拒绝并提示改目录，采用SOP处理PS5.1通配解析限制 |
| 宿主实际0.41原生窗口 | 正确标题、非零句柄、Responding及简中初始化；stderr为空 |
| 检查结束 | 只清理所属测试Job；不是正常退出或本轮人工视觉确认的证据 |
| 沙盒 | 0.40的实际来宾及用户确认保持；没有重跑0.41来宾，新脚本只在宿主验证 |

此前原生探针已经观察到主窗口，但误把关闭请求当作立即退出，最终超时。源码
实际有退出确认弹窗，该失败保留。其他早期探针失败亦保留，没有将失败报告
的passed字段改为true。最终独立索引为work/portable-launcher-checkpoint-v41.json、
work/portable-launcher-native-checkpoint-v41.json和
work/portable-launcher-delivery-checkpoint-v41.json；原始私有日志不随包。

原0.41新增4名称的实际游戏证据及其余8项EXE检查继续以
DELIVERY_RECEIPT_0.41.md为准，不因包装变化重复运行。封包时P0判定仍开放，随后
用户接受两处原版语法基线例外；正式决定见P0_ACCEPTANCE_AUDIT_0.41.md。原
DELIVERY.json的false字段保留为封包快照。真实翻译质量与H03多游戏验证按用户
决定后置，整体目标未标为完成。
本收据为封包后的交付说明，单独保存在当前源码目录，不重写已封存的源码ZIP。
