# 兼容后端的已测能力

日期：2026-10-19。默认回写仍为原生 JSON/JS 适配器。RPGMTL 使用独立进程内存 API，
0.20 的 SExtractor 使用真实 main_extract 导出/导入；0.21 的 Stev 构建使用整目录
ReadGame/ProgramData/InjectGame，单文件候选/比较仍为内存 API。
不启动第三方 GUI，不代表支持其全部引擎和文件格式。

| 后端 | 固定来源 | 实际调用 | 已测 JSON 能力 |
|---|---|---|---|
| StevExtraction | AiNiee 基线 7bbb06be33f5968f0723a5200a150d895d4fa5fb 的 jtpp.py/config.yaml | 构建 ReadGame → ProgramData → InjectGame；单文件 __ReadFile / __WriteFile | 完整工作副本、真实目录输出及原生批准位置；重复原文不同译文、MZ 选项及批准的 357/122 |
| RPGMTL | MizaGBF/RPGMTL，0fa346b020e439fd392027f735107a283c9836d9 | plugins.json.JSON.read / write；plugins.javascript.Javascript.read / write | 数据库、逐 occurrence 本地译文、MZ 选项关联、批准的 357 字段与指定 JS 文字 |
| SExtractor | satan53x/SExtractor，8d8d976fd04ae54e7c677705af937273d04a376a | mainExtractJson → mainExtract → parse/replace/write | RPGMV 的已批准 JSON 完整叶、数组、真实列表导入；BOM/CRLF、MZ 选项及批准的 357/122 |

所有后端的变更均来自原生批准的 pointer。不会传递原游戏根路径。Stev构建复制完整
清单到work并调用真实ReadGame/InjectGame，其余候选/后端仍按单文件bytes工作。
不调用完整项目保存、自动插件加载或Patch/Fix脚本。
SExtractor 的 mainExtract 仅访问新建的单文件 work 副本和捕获配置；导入输出白名单
及完整语义须由父子两侧检查。第三方输出不直接写入游戏或最终发布目录。

## 回写选择与定位

1. `backend-candidate` 只使用 SQLite 中当前有效、已接受的译文，并验证原始 occurrence
   哈希。生成的输出与原生批准写入计划必须语义完全一致。
2. `backend-route` 先在该文件上完成真实候选往返，再记录工具代码及指定配置的指纹。
   该文件必须已有实际变更的接受译文。GUI 中也可通过“文件回写后端”设置。
3. 构建时冻结路由；对选定文件调用实际后端，核对源码指纹与语义差异，记录 writer
   和 sidecar 哈希。失败保留 staging，不自动降级或改用其他后端。
4. 选回 native 可清除该文件的路由。来源、位置或后端源码改变后需要重新验证。

RPGMTL 使用携带 pointer 的字符串跟踪其真实 read 遍历，每个 occurrence 分配独立
全局 ID，并只填本地译文列，不通过全局同文传播。数据源不是用字符串相等来猜位置。

SExtractor 原表不提取 402 标签且缺少 357。桥接仅在新进程内临时启用这两个已审计
代码，并按请求的批准字段名配置其读取规则。实际 ctrl 仍须证明完整字符串的位置，
回写后必须与批准的 JSON 修改完全一致。工具源码文件没有被修改。

## 明确限制

- Stev 合并文本、子串或无法唯一证明地址的记录拒绝回写，不猜测列表删除。
  0.21整目录实际ProgramData保留标签/code/名称来源，同文分轮注入；四份含重复键的
  音频表只作发现，SDK私有归并登记而成品copy原字节。config.yaml纳入路由指纹，
  旧路由需重选。安全配置/编码/禁用清理边界见STEV_PROJECT_EVIDENCE.md。
- 0.11已桥接RPGMTL CommonEvents虚拟子工程，逐文件候选仍是必要条件；上游空355
  首行+655等不一致在含目标子工程时仍拒绝，见RPGMTL_COMMON_EVIDENCE.md。
  0.13增加指定JS文字桥接，先证明SDK的原始源码区间，再用Acorn证明完整AST、译文值及
  区间外字节。模板/正则不获得翻译权限；plugins.js特殊注册表仍拒绝本桥接。
- SExtractor 只接受可证明 whole-leaf ctrl 的规则；默认 RPGMV 主入口完整列表导入。
  不开放任意正则、其他引擎或通用 JSON 回退。原空变更透传已改为真实两阶段语义往返；
  旧路由需重做含 engine.ini 的证明。详见 SEXTRACTOR_MAIN_EVIDENCE.md。
- 旧只读覆盖比较仍会把 RPGMTL 的同文多位置记录报告为歧义，不自动合并写入。
- 本文原始验收是合成来源的真实第三方 API 往返。0.19 增加当前游戏受限 JSON 候选、
  路由与构建审计，见 BACKEND_CURRENT_GAME_EVIDENCE.md 及本版回执；不代表全部场景运行通过。
- 子进程用于隔离解释器状态和环境，不是对不可信工具源码的操作系统安全沙箱。

验收文件：`tests/game_project/test_backend_write_acceptance.py`。检查包括 BOM/CRLF 输入、
同文不同译、102/402 对应、357 的 text 与 resource 分离、原目录及上游源码哈希不变、
空工作 cwd、三种后端的独立构建、后端源码变化导致构建拒绝。只读比较验收另见
`test_compatibility_acceptance.py`。具体工作记录和私有游戏数据不随仓库或便携包分发。
