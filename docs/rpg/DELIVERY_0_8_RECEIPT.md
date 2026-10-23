# 0.8.0-dev 本地交付回执

日期：2026-10-18。交付源码 ad65b97，核心实现 e22f87c。
目录：`dist-rpg/releases/0.8.0-dev-ad65b97/`。DELIVERY.json 状态 ready。
未 push、开 PR 或发布远程 Release；旧 0.7 交付保持原样。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| AiNieeRPG-0.8.0-dev-windows-x64.zip | 253822827 | 27b342dbb359d33d4ed43362564266951ef7a55ec42f82d9c05ccf4e7964d0cc |
| AiNieeRPG-source-ad65b97.zip | 51987461 | 5a8a76fc6185dbb0aa9adfd3d5f84ce86bcd06e7996fbf85f9887dd303a29254 |

3618 软件文件与 713 源码归档成员通过素材/凭据审计；七项交付 checksum 通过。
源码完整回归 230 passed / 196 subtests，含实际安装版 Translator++。
实现边界与 DeepSeek 交接状态见 PROCESS_OWNERSHIP_EVIDENCE.md。

## 新 ZIP 的 EXE

新解压目录在仅含 Windows System32 的 PATH 下通过 11 组检查：自检、GUI、格式2/3、
旧译迁移、三后端与图片、构建/校验恢复、提取与迁移对账恢复，以及进程树故障。
实际 Stev/RPGMTL/SExtractor 回写、逐文件构建/验证和 Tesseract 调用均通过。
GUI 显示 17706 行，122 个字体家族，中文探针 624 个墨迹像素；新增 OCR 控制按钮
截图已目视核对。完整 OCR 暂停/继续/取消按钮流程由源码 Qt 测试证明。

| 故障 | 运行阶段耗时 | 最终状态 | 受控 worker/Node/下一代 Node |
|---|---:|---|---|
| 暂停请求后取消 | 1.240 秒 | CANCELLED | 三个均结束 |
| 主程序退出，随后 recover | 0.588 秒 | INTERRUPTED | 三个均结束 |
| stderr 输出超限 | 0.849 秒 | FAILED | 三个均结束 |
| 60 秒超时 | 60.314 秒 | FAILED | 三个均结束 |

四组均保持无关的自有哨兵进程存活，未发布候选。进程结束只作用于本次拥有的 Job
或验证驱动持有的 Popen 句柄，没有按名称或保存的 PID 终止进程。
构建/校验/提取/迁移检查点及锁定译文保持继续通过，详见交付 JSON 的具体记录。
旧格式1工程摘要 17392 单元，DB SHA 前后相同；验收后所有软件文件重新核对 SHA。

首轮故障验证驱动把导出文件放在来源目录的上级，被 PathGuard 拒绝。修正为独立
interchange 目录后，只重跑该组检查；已通过组的记录复核后汇总，失败日志保留。
这是测试驱动错误，没有为通过测试放宽产品路径约束。

## 当前游戏及范围

当前游戏重提取 17706 单元 / 18254 位置等价；9570 个来源文件集合与 SHA 一致。
原工程 DB SHA 前后均为
`3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935`。
27 条接受译文保留，仍有 17679 条未译。没有新增游戏运行路径验收。

真实翻译按用户决定后续交给 DeepSeek，当前未调用翻译模型。完整自然游玩、剩余规则、
远程 CI 与独立干净机器尚未验收；其他游戏/真实版本按用户决定后置。此回执不代表
完整开发计划或全游戏汉化完成。

本地证据：`work/extracted-package-check/2cc9568f598a4fbe94a5fcdc531224e5/evidence/`、
`work/frozen-process-ownership/a1638d3a2a194d9a9ad27a31721ddd57/result.json`；
发行目录的 DELIVERY.json、EXTRACTED_PACKAGE_CHECK.json、LEGACY_COMPAT_CHECK.json、
PACKAGE_MANIFEST.json 和 SHA256SUMS.txt 保存最终清单与核验结果。
