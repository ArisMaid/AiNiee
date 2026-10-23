# 0.21.0-dev 本地交付回执

日期：2026-10-19。运行源码提交 `a8f46ab2d51b2dee7c733d874c51dcdf15a264b8`，分支codex/rpg-localization-core。
本地目录 `dist-rpg/releases/0.21.0-dev-a8f46ab`。未push、PR或远程Release；旧0.20封存保持。
本回执在运行源码封包后提交；ZIP源码对应上述提交，交付文件以七项checksum核对。

## 交付物与验收

- `AiNieeRPG-0.21.0-dev-windows-x64.zip`：254105730字节，SHA-256 `898fdee2153230317c04832f7ac9bec7cec5a883c548440695f21923cf8a1cbe`。
- `AiNieeRPG-source-a8f46ab.zip`：52271409字节，808成员，SHA-256 `1f059aee9ab7e5811fd2e94e5f2dd695950d303ca3bfb89f6c401a4909af769a`。
- 3631软件文件逐项SHA、七项checksum及ZIP完整性通过。
- 新增17项，完整源码518 passed /207 subtests passed，含安装版T++8.8.9；一条既有依赖弃用警告，零skip/fail/error。
- 新ZIP解压后的实际EXE共25组通过，重跑此前格式、迁移、路由、任务/进程/恢复、GUI与存储组，并新增整目录Stev和发布故障组。
- 子进程PATH仅System32，使用包内Python/Node/Qt；本机隔离PATH证据不代替干净机器。

## G01原计划整目录能力

按§14.1七项及§14.5最低条件逐项收口。构建从冻结完整清单复制游戏到work，真实
ReadGame/LabelName读取ProgramData，保留原文/地址/标签/code/名称来源；按原始地址将
批准译文分轮交给真实InjectGame，解决同文不同译。输入、上游、全部轮次文件与typed语义
由父子分别核对后只收选定文件，SDK失败不修补或降级。单文件候选仍是独立内存API。
config.yaml纳入路由指纹，旧Stev路由需重选；实际捕获源码执行不读取匹配pyc；合法“原文”不再误过滤。
编码/BOM与列表清理identity仅临时作用，自动换行、插件、水印、表格和文件名修正不调用。
工程格式2、写入计划v7保持，边界详见STEV_PROJECT_EVIDENCE.md。

新解压EXE真实两轮不同译文、未请求同文保持、零变更目录往返、缓存来源、重复键/空译文拒绝通过。
四类实际故障（额外写入、来源截断、未批准JSON变化、socket构造）均拒绝，无最终发布且译文不变。
真实InjectGame写部分文件时取消，确认所属PID 49104退出，部分输出保留，无成功报告。
新EXE配置变更阻断构建；源码专项另证明父进程不信任仅更改hash的报告。SDKguard是已审计工具的边界，不是OS沙箱。

目录发布曾出现WinError5，具体占用者未定位。现按同父目录/UUID与安全路径有限重试Windows
5/32/33，已有目标绝不覆盖；源代码真实GENERIC_READ无delete-sharing句柄短占用、持续占用
及已有目标三项通过。新EXE另实际持有staging目录句柄，短占用后发布通过，持续占用保留完整staging且无成品。

## 当前游戏完整测试构建

源码与新EXE各做Stev/SExtractor两份完整测试构建。每后端六个选定JSON文件、16批准位置、
9570清单文件另加两份构建元数据。核对实际writer/sidecar、SDK入口与配置、所有输出集合/hash、
原生JS AST、批准图片字节和显式字体/映射；两个后端非路由输出逐字节一致。verify通过，runtime not_run。

| 执行 | 后端 | 构建秒 | 清单文件 |
| --- | --- | ---: | ---: |
| 源码 | stev | 371.63 | 9570 |
| 源码 | sextractor | 204.12 | 9570 |
| 冻结EXE | stev | 382.14 | 9570 |
| 冻结EXE | sextractor | 205.19 | 9570 |

Stev实际完整输入9570、35903行ProgramData、一轮真实InjectGame输出178个JSON并核对16变更。
完整复制/审计增加耗时，上述为本机非受控缓存观察，不是跨设备性能承诺。
四个音频资源表有55个重复键：完整输入原bytes保留，SDK私有归并登记，Node JSON.parse来源
解码对照通过；这些文件仅发现、无可写定位，成品采用原字节copy。未略去问题文件或把归并藏成空白差异。

主工程17716单元/29旧人工样例保持，副本另加2 Items并锁1条，共31接受、17685未译；
明确--test。原版全部9570文件（含被成品排除的日志/存档）、主DB、图/译文/锁和SDK/config保持。
没有应用模型请求或游戏启动，未向编码worker发送游戏文本。9570清单来自9568保护文件加两份字体相关文件，不能等同原版集合。

源码证据 `work/current-json-builds-v21/052e8c3ab4a44b1f863d1442df052359`；
冻结证据 `work/current-json-builds-v21/27140098e4c14dc3a4090d6aa7237fd2`；
新EXE专项 `work/frozen-stev-project-v21/12eae526a24443d89f7aa884da9ff541`。
旧格式1/profile4只读summary及库SHA保持；0.20七项封存checksum保持。

## 协作与剩余任务

deepseek-worker使用deepseek-official/deepseek-flash/max，无maxTokens覆盖。任务2400秒上限，
1392.119秒完成，仅两个允许文件，59次调用全部通过guard；保护文件无变化，Codex核对9个hash。
交接verified:false，Codex随后完成方案/集成/审查/测试/交付，修正依赖、来源缓存、合法文字过滤、
重复键及目录发布。首轮缺ruamel、缓存/占位错误、原发布失败、错误的句柄权限/导出目录驱动等
现场保留。首个整目录检查因重复键失败，原版与主库保全通过；新UUID完整重跑，不放宽产品路径守卫。
冻结原子恢复旧驱动遗漏配置且依赖Stev旧时序，保留失败证据，改用真实SExtractor只读门控，
短占用、持续占用、异常退出、半写入退出、未知暂存五类全部通过。前20组通过证据保留，
随后只续验未完成组。GUI汇总曾误用UTF-8解析Windows本地编码，原stdout保留且与UTF-8
结果文件逐项核对一致；已通过GUI组不重复运行，后续控制器显式UTF-8。

总表24已实现/9部分/1用户后置，完整计划与P0仍未完成。剩余A03、E02、E03、E04、E05、
F02、F03、G06、H02；真实翻译、完整自然游玩、排版/图片质量、干净机器/远程CI等未验收，
其他游戏按用户决定后置。不能将本回执理解为完整游戏汉化或通用跨游戏兼容完成。

包无游戏素材、工程/译文、用户字体、截图、凭据或worker日志；含Matplotlib依赖40字体及许可。
没有批量删除文件或目录，没有远程发布。目标继续保留，后续按原计划推进。
