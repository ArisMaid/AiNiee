# 0.19.0-dev 本地交付回执

日期：2026-10-19。运行源码提交 `7a5019178a91bcf908dbca5e75071ee184515404`，分支 codex/rpg-localization-core。
本地目录 `dist-rpg/releases/0.19.0-dev-7a50191`。未push、PR或远程Release，旧版保留。

## 交付物

- `AiNieeRPG-0.19.0-dev-windows-x64.zip`：253990462字节，SHA-256 `c7d9ea78bf1d4c3c95d6d6f402b1d85beb8b13d1a58549c40c171efad7b6533e`。
- `AiNieeRPG-source-7a50191.zip`：52195763字节，791成员，SHA-256 `bddaf125c1a344cefcff80a10d9e7463eed2a16312c85ce1e0b1bf17ced6205a`。
- 3629软件文件逐项SHA清单、七项交付checksum及ZIP完整性通过。
- 新ZIP实际解压EXE自检、GUI及21组专项，共23组通过。子进程PATH仅System32，使用包内Python/Node/Qt。
- 源码491 passed /207 subtests passed，含安装版Translator++8.8.9，一条既有依赖弃用警告，零skip/fail/error。

## 修复与当前游戏验证

SExtractor原规则转换只看末级下标，当前游戏System菜单数组无法定位。0.18 EXE六文件
候选矩阵中Stev6通过、SExtractor5通过/1拒绝，失败保留。0.19改为沿原文确定最后字典
字段名，仅启用可表达字段；真实ctrl、whole-leaf证明及完整批准差异保持。7项新验收
先3失败/4通过，修复后连同原后端/事件专项17通过，根数组与数字键等仍拒绝。

源码和新EXE各做Stev/SExtractor两个当前游戏完整测试构建。每个后端六个明确路由文件、
16个批准JSON位置，含Items、Skills、System、地图、公共事件及SH_Nuiit。核对实际writer、
上游源码指纹、sidecar hash与来源、原生预期语义、显式System字体、原生JS AST、批准图片
字节、字体/映射及所有文件集合/hash；两个后端非路由输出逐字节一致。verify通过，runtime not_run。

| 执行 | 后端 | 构建秒 | 清单文件 |
| --- | --- | ---: | ---: |
| 源码 | stev | 263.70 | 9570 |
| 源码 | sextractor | 275.34 | 9570 |
| 冻结EXE | stev | 284.12 | 9570 |
| 冻结EXE | sextractor | 296.61 | 9570 |

主工程17716单元/29接受译文不改；各独立副本添加2个人工Items样例并锁1条，共31接受，
17685未译，构建明确使用 --test。原9570文件（含构建排除日志/存档）、主DB、图/译文/
锁、上游Python均保持；没有模型请求或游戏启动。清单9570另加2个元数据文件；构建保护
集9568加2个显式字体相关新文件，不能与原游戏9570集合混淆。

源码首轮驱动错误地隐藏已安装Node，两构建JS_BACKEND_NOT_READY失败；保全通过，
staging保留。修正源码PATH后在新UUID工程完整重跑；冻结EXE仍为System32-only。
源码证据`work/current-json-builds-v19/73a2e0c184374fe0aa07aabcfd2397ab`；
冻结证据`work/current-json-builds-v19/e55455c403214edd8665696c5d60ed76`。
新EXE既有小窗口原生Qt事件、菜单、隐藏底栏拒绝、迁移/任务恢复/JS/进程/存储组均重跑。

## 协作与剩余范围

使用deepseek-worker，deepseek-official/deepseek-flash/max，无maxTokens覆盖。
单文件900秒上限、225.767秒返回；目录grep被guard拒绝一次，policy_violation按失败交接，
授权文件外无写入，保护文件保持。Codex接管审查、测试、构建与交付，未放宽guard。

总表保持22已实现/11部分/1用户后置，目标active。G01/G03仍部分：当前内存API与原整
目录CLI/ProgramData设计存在明确差异，不能用受限JSON L2代替整任务。完整自然游玩、
真实翻译、排版/图片质量、其余失败/运行验收、干净机器与远程CI仍待；其他游戏按用户后置。
软件/源码包无游戏素材、工程/译文、用户字体、截图、凭据或worker日志；含Matplotlib
依赖40字体及许可证。没有批量删除。详细范围见BACKEND_CURRENT_GAME_EVIDENCE.md。
