# RPG便携包能力范围

本便携包用于AiNiee的RPG工程流程，不是完整AiNiee开发环境。当前已核验发行物为
0.41，实际EXE范围见DELIVERY_RECEIPT_0.41.md；3664软件文件、7156嵌入模块，
设置四名称实际EXE往返/旧图升级及源码完整输出核验通过。旧封存包不自动
获得后续新增能力；本版没有重复完整EXE游戏构建，源码/SDK/原装运行分别报告。

| 范围 | 当前证据/约定 |
| --- | --- |
| RPG核心 | MV/MZ标准数据及已批准规则；当前MZ游戏实际EXE提取/完整构建通过。新游戏/未审插件不由此获得兼容声明 |
| Node/JS分析、Qt、图片/字体基础 | 核心运行依赖随包；不是系统Python/Node安装器。实际ZIP自检/Qt证据见版本回执 |
| 模型接口 | 复用AiNiee接口配置；不是内置离线模型。真实DeepSeek语言质量尚未验收 |
| Translator++ | 不随包，官方8.8.9独立安装/API桥接已测；其他版本未测 |
| Stev/RPGMTL/SExtractor与OCR | 可选来源/程序另装，按对应支持清单选择；游戏字体/私有资源不随软件包 |
| BabelDOC PDF结构保持翻译 | 便携包没有BabelDOC及其PDF读/写入口；需要完整AiNiee环境，不作为本包功能承诺 |
| MTool的AI代码识别过滤 | CodeTextFilter类在包内，Magika不在；该类只支持MTOOL，RpgGame不走此分支。需要该MTool功能请使用完整环境 |
| 其他普通文档格式 | 某库/界面存在不等于该工作流已验收，本RPG发行回执不授予普通文档全功能声明 |

打包配置明确排除8个依赖族：torch、tensorflow、spacy、babeldoc、magika、onnxruntime、
pytest、scipy。前六及scipy不作为本包的本地推理/科学计算环境，pytest是开发测试工具。
这不是说API翻译需要这些库；也不声称其他外部应用或用户单独安装的服务不可用。

对封存0.26实际EXE只读检查嵌入PYZ模块表：7154条模块名，以上8族各0；BabelDOC
PDF读/写入口各0，CodeTextFilter存在。该检查没有执行被冻结模块，也未改EXE。
模块表只是范围证据，不代替普通文档行为验收。证据保留于
work/portable-scope-v27/0d993443ce694bf79e65e3c1004e8005/result.json。
后续0.27实际模块表同为7154，8族各0，BabelDOC入口仍无、CodeTextFilter仍在；额外
只读核对见work/portable-scope-v27/new027-module-scope.json及交付目录DELIVERY.json。
0.28实际嵌入7155模块，8族仍各0；新增备注能力和诊断的实际EXE流程见0.28回执。

使用SOP：本包从“游戏汉化”工程入口工作；涉及上述未提供能力时转到完整AiNiee
环境，不在便携目录内临时安装或混装依赖。先备份工程，新版在副本验证。未知候选、
图像文字和组合显示按各自说明人工复核，不通过改后缀或开关绕过能力边界。

0.40已在实际离线Windows Sandbox完成合成自检、GUI检查及正常窗口确认，接受
范围限定于SANDBOX_ACCEPTANCE.md列明的启动SOP；远程CI仍未运行。本机仅
System32 PATH不替代该来宾证据，没有做过的环境/版本/格式继续列为未验证。
0.41仅Version模块语义变化，其余7155模块与RpgApp入口一致，310原生/字体组件
字节相同；本轮复用这些未变组件的实际0.40环境证据，并独立执行0.41数据流程。
未重新运行0.41干净来宾，不把组件比较改称该版本来宾实测。
工具、源码和公开日志不包含游戏
素材、工程、原存档、真实响应、凭据或私有截图。软件不会自动上传补丁。
