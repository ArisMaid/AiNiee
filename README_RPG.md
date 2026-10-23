# AiNiee RPG 工作流

本分支在 AiNiee 上增加 RPG Maker MV/MZ 工程的扫描、提取、翻译任务、校对、
受控回写、字体和图片处理、补丁及构建恢复。原生适配器决定可写位置；可选工具
按各自已验证的入口接入，不承诺任意引擎、插件或工具版本都可直接使用。

当前版本为 **7.2.4.1**，增加外部工具管理与按需配置。
Windows 便携版与对应源码见 [Releases](https://github.com/ArisMaid/AiNiee/releases)。
旧0.41封存包及其验收记录保留原身份，不作为新版 EXE。

- 新增入口：[外部工具配置](docs/rpg/EXTERNAL_TOOLS.md)、
  [7.2.4.1 发布说明](docs/rpg/RELEASE_7.2.4.1.md)、
  [工具专项验证](docs/rpg/EXTERNAL_TOOLS_EVIDENCE_7.2.4.1.md)。
  缺少工具时支持“一键下载配置”或“选择已有安装”。

- 使用入口：[用户指南](docs/rpg/USER_GUIDE.md)。便携包解压后运行
  `Start-AiNieeRPG.cmd`；启动日志位置和离线诊断入口见包内说明。
- 开发入口：[开发计划](docs/rpg/DEVELOPMENT_PLAN.md)、
  [实施状态](docs/rpg/IMPLEMENTATION_STATUS.md)、
  [预发布源码同步说明](docs/rpg/PRERELEASE_SOURCE_SYNC.md)、
  [工作区目录与开发环境](docs/rpg/WORKSPACE_LAYOUT.md)。
- 验收入口：[0.41 P0 审计](docs/rpg/P0_ACCEPTANCE_AUDIT_0.41.md)、
  [最新启动器交付回执](docs/rpg/DELIVERY_RECEIPT_0.41_LAUNCHER.md)、
  [能力范围](docs/rpg/PORTABLE_SCOPE.md)、[沙盒验收](docs/rpg/SANDBOX_ACCEPTANCE.md)。

当前游戏 P0 已按用户批准的原版语法基线例外接受；999 条记录包含演示译文和
原文锁定，不代表全游戏翻译完成。真实 DeepSeek 翻译质量尚未验收，H03 的其他
真实游戏/版本验证由用户延期。0.40 有直接 Windows Sandbox 证据；0.41 对未变
组件复用该证据，并完成本版专项检查，不声称新做过 0.41 干净来宾验收。

本地开发使用源码外的 Python 3.13 环境与 `requirements-rpg.lock`；JS 分析使用
Node.js 24.16.0 和 `Tools/package-lock.json` 锁定的 Acorn。依赖、输出与缓存的
中文分类位置由 `Tools/rpg_paths.json` 约定，首次安装方法见工作区说明。
从仓库根运行 `Tools/start_rpg_dev.ps1`。需要验证修改时，按修改范围运行现有检查，
完整既有 RPG 检查入口为 `Tools/test_rpg.ps1`，不要求每次文档迭代重跑。

Translator++、RPGMTL、SExtractor、Stev 外部来源和 OCR 可由工具管理按需下载配置；源码仓库和
软件包不包含游戏、私人工程、存档、用户字体、密钥或模型响应。
许可和版本固定值见 [第三方说明](docs/rpg/THIRD_PARTY_NOTICES.md)。
项目保留 AiNiee 的 AGPL-3.0 许可及版权声明。
