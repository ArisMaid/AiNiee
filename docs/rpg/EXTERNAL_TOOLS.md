# 外部工具配置（7.2.4.1）

在 RPG 工程页面切换到“工具与恢复”，打开“外部工具管理”。无需先创建工程。
选择工具后可看到固定版本、下载体积、来源、安装位置和检查结果。

- **一键下载配置**：下载固定版本，验证 SHA-256，再展开到独立工具目录并保存路径。
  首次使用 Translator++ 或 OCR 时，自动准备解压组件；OCR 同时配置日文、英文识别数据。
  无需先安装 Python、Node、7-Zip，也无需系统安装 OCR。
- **选择已有安装**：选择可信的工具目录。Translator++ 必须为 8.8.9；OCR 必须为
  Tesseract v5.4.0.20240606，目录内有 tessdata/jpn.traineddata 和 eng.traineddata。
  三种 SDK 的关键入口必须与清单版本一致，换行符差异可接受。版本不符时使用一键配置。
- **检查配置**：重新检查路径与支持版本。工具被移动或升级后，在这里重新登记。
- **启动并检查 T++**：启动选定安装并检查本机 API。已运行的同一安装会直接复用。
  若 22883 端口被另一安装或程序占用，请关闭该程序再重试；不会强制结束用户进程。

工具不包含在应用 ZIP 中。首次下载需要能访问 GitHub、codeload.github.com 和
raw.githubusercontent.com；网络失败可重试或选择已有安装。不读取浏览器登录态，
不需要在 AiNiee 中提供 GitHub 凭据。Translator++ 本地交换不需要会员或翻译 API Key；
模型翻译仍需在 AiNiee 中配置自己的平台和模型。

| 工具 | 固定版本 | 配置后的使用方式 |
| --- | --- | --- |
| Translator++ | 8.8.9（约 211 MiB 下载） | “导出并送往 T++”和在线导回时自动启动、检查本机 API；也可手动交换 .trans |
| Tesseract OCR | 5.4.0.20240606（约 48 MiB，加日文数据） | 图片窗口自动填写程序和 tessdata 路径；识别候选仍需人工校正 |
| RPGMTL | 0fa346b | 文件后端对话框自动填入目录；批准位置和候选校验后调用 |
| SExtractor | 8d8d976 | 同上，仅开放已实现的 RPGMV/MZ JSON 接口 |
| StevExtraction | AiNiee 基线 7bbb06b | 同上，通过私有副本运行并核对输出 |

缺少工具时，Translator++ 和 OCR 的功能入口会打开此配置流程；后端设置也提供
“下载 / 配置工具”按钮。完成配置后返回原功能继续，不自动改变已登记的文件路由。
原生后端继续作为默认选择。Translator++ 的原生完整游戏导出存在已记录的地图遗漏，
本集成仍以 AiNiee 校验后的副本构建为最终输出，不扩大其他引擎和格式的支持范围。

便携版默认将工具放在用户数据目录下的 tools，路径配置为 external-tools.json；
标准启动时通常位于程序旁。以 DataRoot 启动时配置和工具随该数据目录隔离。
源码运行则放在仓库外的“外部工具”和“开发记录/工具配置”，不混入源码发布。
高级诊断可设置 AINIEE_EXTERNAL_TOOLS_HOME 和 AINIEE_EXTERNAL_TOOLS_CONFIG；普通用户无需设置。

取消下载会保留 .part 文件和安装现场；当前网络读取或解压步骤结束后响应取消，
期间请等待按钮恢复。解压与校验完成前不会将工具登记为可用。
失败现场位于工具目录的“安装现场”，下载包位于“下载缓存/7.2.4.1”。
已有同版本安装不会被覆盖；损坏时可选择另一个完整安装，或自行移出该版本目录后重试。
不提供静默清理、自动升级或批量卸载，避免误删已有工具与诊断证据。

下载来源与完整 SHA-256 固定在 Resource/ExternalTools/catalog.json。
解压组件为官方 7-Zip 26.05 x64 MSI，仅执行管理展开，不向系统安装服务或注册文件关联。
工具目录含独立软件的许可证，使用和再次分发时遵守各自许可。

命令行诊断：

```powershell
.\AiNieeRPG.exe --cli tools-list
.\AiNieeRPG.exe --cli tools-install --tool translatorpp
.\AiNieeRPG.exe --cli tools-select --tool ocr --path 'D:\Tools\Tesseract'
.\AiNieeRPG.exe --cli tools-start --tool translatorpp
```

命令返回成功表示本次操作完成；tools-list 中每项的 ready 表示该工具当前是否可用。
配置成功与游戏翻译质量、全流程游戏运行验收是不同结论。
