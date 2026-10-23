# AiNiee RPG 7.2.4.1

增加外部工具管理流程。无需创建工程即可检查工具，缺失时可选择“一键下载配置”或
“选择已有安装”。支持 Translator++、Tesseract OCR、RPGMTL、SExtractor 和 StevExtraction。

下载使用固定官方版本和 SHA-256；按需准备解压组件及日英 OCR 数据。
Translator++ 交换可自动启动并检查本机 API，图片 OCR 和文件后端设置会填入登记路径。
RPG 版更新检查指向本 fork，并明确选择 Windows 应用包，避免误选源码 ZIP。

下载 **AiNieeRPG-7.2.4.1-windows-x64.zip**，完整解压到可写目录，双击
**Start-AiNieeRPG.cmd**。首次需要外部工具时联网配置，已有工具可直接登记。
应用包自带 Python、Node 与核心依赖；工具和语言包按需另行下载，不需要自行安装开发环境。
详细步骤见包内 EXTERNAL_TOOLS.md。SHA256SUMS.txt 用于核对资产完整性，
另提供对应提交的源码 ZIP 和构建文件清单。

本次验证覆盖独立工具目录的实际下载配置、固定版本检查、取消与错误路径、
源码及便携版界面、核心合成往返和外部 SDK/OCR 调用。具体证据见
docs/rpg/EXTERNAL_TOOLS_EVIDENCE_7.2.4.1.md；GitHub Actions 执行发布构建及检查。

支持范围仍以 docs/rpg/IMPLEMENTATION_STATUS.md 为准。当前实际游戏仅一款，
H03 多游戏/多版本验收由用户后置；尚未完成真实模型译文质量和全游戏通关验收。
既有原版语法草稿按用户批准的来源基线例外处理。本版本不包含游戏、字体、
用户工程、凭据或私有模型日志，也不代表完整游戏汉化已完成。
