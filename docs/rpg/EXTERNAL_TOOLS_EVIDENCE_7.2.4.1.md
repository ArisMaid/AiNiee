# 7.2.4.1 外部工具专项验证

日期：2026-10-24。验证者：Codex。使用独立工具安装与配置目录，不修改实际游戏工程。
本次保持用户要求的“小步迭代、必要验证”，没有重跑整款游戏汉化或所有历史验收。

| 范围 | 结果与边界 |
| --- | --- |
| 实际在线下载 | 五种工具全部从清单来源下载，逐包 SHA-256 匹配；未复用原有工具安装 |
| 解压准备 | 官方 7-Zip 26.05 MSI 管理展开成功，使用展开后的 7z.exe/7z.dll；无需预装 7-Zip |
| Translator++ | 8.8.9 自动启动成功；本机 API 识别版本、安装根目录、RMMVParser 和读写接口 |
| 实际交换 | 合成工程导出并打开，写入一条译文并导回 SQLite，接受数为 1 |
| OCR | 新下载的 Tesseract 与 jpn+eng 将合成图片识别为“日本語 HELLO” |
| 三个 SDK | 复用既有合成往返验收，指向新安装目录；3 项实际通过、0 跳过；重复原文分别回写、构建核对通过 |
| 配置边界 | 已有安装版本不符、坏缓存/网络失败、取消、ZIP 路径越界拒绝、安装后复用与路径持久化通过 |
| 源码 GUI | 离屏主界面和新管理窗口成功；5 种工具；“一键下载配置”“选择已有安装”存在；未打开工程可访问 |
| 更新入口 | RPG 模式使用 ArisMaid/AiNiee，源码 ZIP 排在前面时仍选择 Windows 应用 ZIP |

源码专项命令（不要求普通用户运行）：

```text
python -m pytest tests/game_project/test_external_tools.py tests/game_project/test_gui_build_controls.py -q -p no:cacheprovider
python -m pytest tests/test_version_manager_portable_update.py -q -p no:cacheprovider
python RpgApp.py --gui-check <独立证据目录>
```

便携版通过独立发布构建执行：打包后 self-check（核心合成回写、补丁、JS 解析、图片编码）、
GUI 检查（含新管理窗口）与包内容审计。发布流水线见
[RPG Windows release build](https://github.com/ArisMaid/AiNiee/actions/workflows/rpg-release.yml)。
源码 GUI 检查不替代便携版检查；以该次 Actions 的完成状态和发布资产为准。
完整下载日志、SDK 私有工作副本与界面截图在本地验收目录留存，不放入公开源码和应用包。

本机在线安装不等同于 Windows Sandbox 实测；本版不复写旧沙盒报告。
验证中模型调用数为 0；真实模型质量、多游戏/版本、任意外部工具新版不在本次接受范围。
公开校验清单记录下载版本与来源，不自动升级 SDK；用户改动入口后需重新选择支持的安装。
