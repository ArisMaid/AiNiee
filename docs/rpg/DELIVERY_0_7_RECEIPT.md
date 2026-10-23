# 0.7.0-dev 本地交付回执

代码提交 `2baea24`。仅本地提交和交付，没有 push、PR、远程 Release 或 CI 验收。
完整开发计划仍未完成，本包也不是完整汉化游戏。

目录：`dist-rpg/releases/0.7.0-dev-2baea24/`。

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| AiNieeRPG-0.7.0-dev-windows-x64.zip | 253770082 | 9769672cc48d44aca8cbed7f4a166f087cae2a4c2e32f8c1cade9f22cba7695a |
| AiNieeRPG-source-2baea24.zip | 51946900 | 9d6e20263f9d36b4fe7ea6df9acca82774ab92283bc2c7f5c65c461182944fd1 |

3616 软件文件、700 源码归档成员通过素材/私有目录/凭据模式审计。软件文件集合和
SHA-256 在测试后再次相同；七项 SHA256SUMS 校验通过，DELIVERY 为 ready。
0.5/0.6 的旧交付没有改写。新包内含 Python/Node，Translator++、游戏和字体另行提供。

## 验收

- 最终源码回归 **202 passed / 178 subtests**，包括本机 Translator++ 8.8.9 API。
- 从最终 ZIP 新解压，实际 EXE 的 PATH 仅含 System32；自检、17706 行 GUI、迁移
  对话框创建/截图、格式 2/3、三后端与图片、构建及校验恢复均通过。
- 提取取消恢复复用 30 个 JSON，锁保持；关系确认、对账应用及两次 stale 重新校验通过。
- 实际 EXE 的两组各 4000 条迁移：暂停/继续/取消后复用 1471、新增 2529；进程终止
  后复用 12、新增 3988。旧尝试分别保持 CANCELLED 和 INTERRUPTED，新尝试完成。
  每组最终恰好 4000 条迁移提案，锁定修订和旧库 hash 保持。
- 旧格式 1 工程摘要读取 17392 单元，DB hash 前后相同。
- 当前游戏数据库图副本另经程序驱动真实 Qt 按钮：第 8 条提交后进度为 7，暂停取消
  后复用 8、新增 19，最终仅 27 条提案；完成条目的人工锁保持。该副本没有素材复制
  或构建验收，不能作为完整新游戏版本测试。
- 原 profile4 数据库 SHA-256 仍为
  `3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935`。
  原游戏 9570 文件集合与全部 SHA-256 一致。

## 证据和驱动修正

本地私有证据不进入软件/源码包：

- `work/acceptance/rpg-0.7-final.xml`
- `work/migration-recovery-current-acceptance.json`
- `work/extracted-package-check/bafdbe5f76bf4511ab975381404343c6/evidence/`
- `work/frozen-migration-recovery/ea5b47738362432ba33333921c273110/`
- 交付目录的 DELIVERY、EXTRACTED_PACKAGE_CHECK、LEGACY_COMPAT_CHECK 和清单。

首次新冻结包迁移检查完成两组恢复，但驱动使用 `with sqlite3.connect(...)` 后未显式
关闭旧库连接。Python 的连接上下文只处理事务，后续回收连接触发 WAL checkpoint，
使主文件 hash 改变。驱动改成只读 URI 并用 closing 显式关闭，整轮从 ZIP 重新解压
通过；应用包未变。单独 SQLite 复现证据在
`work/sqlite-connection-proof/f4bc75daa95a4fb69b0915e3fe70ac57/`。失败目录及输出保留。

DeepSeek 生成纯提案校验模块草稿，但两项调用被 guard 拒绝，交接记录为失败；Codex
审查所有产出并编写独立测试后才集成。任务控制、恢复、事务、GUI、CLI 和验收由 Codex
完成；没有放宽 guard。具体来源和边界见 MIGRATION_RECOVERY_EVIDENCE.md。

## 尚未完成

外部 worker 的完整进程树终止、剩余插件规则、完整自然游戏路径及全计划收口继续。
Windows Job Object 草稿已由另一 DeepSeek 任务完成并独立测试，尚未接入应用，也不在
此包内。真实模型、第二款游戏、其他真实版本及独立干净机器未验收；其他游戏按用户
要求后置。当前游戏仍有 17679 条未译。
