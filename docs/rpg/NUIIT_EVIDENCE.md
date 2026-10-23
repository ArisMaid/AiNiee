# SH_Nuiit 显示字段接入证据

适用版本：selenoxia test 0.141 / MZ 1.7.0 / gameId 33872391。规则仅匹配配置中声明的脚本及 CommonEvents SHA-256。游戏素材与完整台词均保留在本机，不随软件包分发。

## 显示路径与提取边界

`SH_Consts.js:916` 注册数据对象。`shimo/SH_GameSystemParam.js:3167–3181` 按 tag 选择行，将行数组存入变量 1901，将首行 searchWord 存入变量 1938。tag 是匹配键，不提取。

`CommonEvents.json` 的公共事件 1968 / list 20 将所选行 message 写入变量 1913；list 22 将 `[なし]` 作为无结果哨兵判断；list 31 调用 `SH_Nuitter()`；list 32 交给 DTextPicture 显示变量 1913。因此 message 可译，但精确哨兵值必须排除，译文也不得生成此值。`[stamp]` 被保留为资源标记，包含它的行排除，译文不得引入它。

`SH_Sandbox.js:93–106` 中的 `SH_Nuitter()` 将 message 内的 `[word]` 替换为变量 1938，再换行并保存显示结果。118 行中 114 行含 `[word]`，2 行 message 恰好为 `[なし]`。仅声明已经观察到的 `[word]` 为不可翻译字面占位符；数量、大小写与顺序必须保持。

公共事件 1965 / list 22 与 1970 / list 3 将变量 1938 用于搜索标题显示。脚本的 `!= 0` 同时决定是否启用替换，因此 searchWord 翻译必须保持原字符串经 JavaScript Number 转换后是否等于零的结果。代码不执行任意 JS，仅实现所需的字符串数值语法，并用 Node 作为独立对照。[ECMAScript StringToNumber](https://tc39.es/ecma262/multipage/abstract-operations.html#sec-stringtonumber) 是这一守卫的规范依据。

## 格式与验收

配置格式升级为 2。工程要求 `literal_tokens_v1` 与 `display_value_constraints_v1`；旧版应用必须拒绝打开此工程。首次对旧格式启用时，数据库备份与升级采用 FORMAT_V2_CONTRACT 约定。独立的新工程用于当前游戏实测，原 0.1.1 工程保持原状。

专项测试覆盖占位符往返、增删与原始标记注入拒绝、哨兵和资源标记排除及目标值拒绝、数值零守卫、事务回滚和捕获源文件被改动时拒绝提取。

独立工程 `selenoxia-0141-sns` 已提取 233 个新增单元：115 个非空 message、118 个 searchWord；
另有 1 个空 message，2 个精确哨兵排除。总单元 17625，保留 17 条先前演示译文，并新增
2 条显示演示。原格式 1 工程数据库 SHA 未变；旧 0.1.1 EXE 拒绝新工程并返回 expected
schema_version 1, found 2。GUI 显示全部 17625 行，122 个字体家族及 624 个墨迹像素检查通过。

构建 `22bcefc453bf4cf5ac02d0dd1feb3dbb` 在加仪器前通过完整文件 hash 验证，只改目标行
的两处文本，其余 SH_Nuiit 字段与结构一致。随后仅在该私有副本附加测试入口：通过真实
标签过滤函数得到 9 行候选，经真实随机抽样函数选取单个指定行，再由实际公共事件 1968
运行至 DTextPicture。图片对象文本为“塞雷诺克西亚是什么？”，120×54 像素，解释器完成且
无脚本异常；标题、整屏和文字位图均已检查。私有证据为 work/nuiit-runtime-evidence.json、
nuiit-screen.png 和 nuiit-caption.png。仪器使用固定 tick/focus，并隔离开场解释器，
因此不能当作自然游玩、随机剧情全分支或完整游戏汉化验收；加仪器后的副本也不作发行包。

实际 DTextPicture 明确使用 HSJP-Regular，原字体缺少“亚、诺”。后续构建
d7dd8019f8bd4a30a8e95154f245fdf2 已显式映射四个字体名称至捕获的简中字库，实际原生
加载 URL、loaded 状态、中文截图及已接受译文缺字检查均通过，见 FONT_ALIAS_EVIDENCE.md。
