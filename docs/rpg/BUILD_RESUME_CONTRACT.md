# 文件级构建恢复契约

对应开发计划 §12.2、D05、E05。Codex 负责 BuildService/CLI/Qt 集成、故障测试和交付；DeepSeek 只实现新文件 `ModuleFolders/Service/GameProject/BuildJournal.py`。不得修改其他源码、运行命令、删除文件或读取游戏数据。可读本契约、PathGuard.py、BuildService.py、ProjectLock.py。目录探索用 glob，grep 只能用于单个明确文件。

当前 BuildService 已冻结 SQLite 输入，逐文件复制/回写并保存输出清单。缺口是失败后只能重建全部文件。本模块提供每个构建独立的持久化 journal，恢复时必须实测输出 hash 才可复用，不依据“进度数”信任文件。禁止用宽泛缓存替代冻结输入或取消校验。代码使用标准库及现有 PathGuard，不操作项目权威数据库。

## API

`BuildJournal.create(project_root, build_id, descriptor)`、`BuildJournal.open(project_root, build_id)` 返回支持 context manager/close 的实例。build_id 为严格 32 位小写 hex。记录根为项目 `builds/<build_id>`（必须已存在）；文件为 `resume.sqlite3`。create 要求文件不存在，open 要求存在。路径全过程用 safe_join 验证，禁止链接、目录穿越或任意数据库路径。SQLite 连接每实例独立，RLock、BEGIN IMMEDIATE、synchronous=FULL、journal_mode=DELETE；不是 WAL，避免单文件 journal 含未 checkpoint 数据的歧义。不得覆盖已有数据库，不删除文件。

descriptor 为 JSON 字典，键必须精确为 `schema_version,build_id,project_id,output_root,source_root,test,runtime_capture,frozen_sha256,plan_digest`。版本为精确整数 1；id 为非空字符串，build_id 与构造参数一致；output_root/source_root 必须绝对路径，并通过 assert_disjoint(source_root,project_root,output_root)；test/runtime_capture 为精确 bool；两个摘要为小写 SHA-256。输出 staging 唯一绑定 `output_root/.staging-<build_id>`。descriptor 内不保存游戏加密 key。open 也重新验证所有 descriptor 和边界。暴露只读副本 property `descriptor`。

- `new_attempt(job_id: str) -> str`：job_id 为 32 hex，产生新 attempt_id（32 hex），持久化 RUNNING。不要复用旧尝试记录。
- `finish_attempt(attempt_id,state,reason='')`：state 只允许 COMPLETED/FAILED/CANCELLED/INTERRUPTED，记录审计；已终止尝试不可改状态（同状态同 reason 重复调用可幂等）。不存在 ID 拒绝。reason 字符串最多 4096。
- `record_file(relative_path, original_sha256, output_sha256, writer: dict)`：路径相对 staging、必须规范 `/`，不允许大小写折叠碰撞、Windows 保留名/ADS/链接；严格校验 SHA 和 JSON（拒绝 NaN），writer 必须含非空 id 字符串。数据库同一 relative_path upsert，每次有时间戳；不以此接口写入实际游戏文件。
- `records() -> list[dict]`：按 path 排序，返回与 BuildService 清单兼容的 `{path,original_sha256,output_sha256,changed,writer}`；changed 比较实际 hash，而不是是否存在翻译请求。读取时校验 JSON/字段。
- `reusable_file(staging,relative_path,original_sha256) -> dict | None`：先严格绑定 staging 必须是 descriptor 对应目录；reparse/hardlink 违规拒绝。若没有匹配来源 hash 的记录，或文件不存在、实际 SHA 不等输出 SHA，返回 None。只有读取实际文件 SHA 成功才返回该记录。不打印内容，不相信大小或时间戳。不对目录计算 hash。
- `retain_file(staging,relative_path,attempt_id) -> str`：只用于已存在且不准备复用的单个 staging 文件，必须有效尝试 ID、路径绑定正确。通过 safe_join 检查源是普通非链接文件，目标为 `builds/<id>/retained/<attempt_id>/<uuid>.bin`，目标不允许存在。使用同一文件系统单文件 rename，不递归、不删除、不静默覆盖。返回项目相对保留路径。在同事务/记录中保存原 rel 与保留路径、时间供审计；若 rename 成功而审计事务失败，明确抛错并保留文件，不重试移动。不存在文件或目录请求明确失败。任何时候不得接收原游戏绝对路径作为文件路径。

DB 格式自有 v1，schema marker/descriptor 验证失败则拒绝打开，不能自动重建或覆盖损坏 journal。SQL 全部参数化、读取 writer/descriptor 严格拒绝重复 JSON key 和 NaN。打开 SQLite 前验证单文件存在性，避免 sqlite 自动创建缺失库；create 用独占创建占位文件，再连接，出现错误也保留诊断。无需实现 SQLite 从句之外的锁跨进程，调用方已持工程 OS 锁；每次尝试和保留文件需可审计。

## Codex 验收与集成约定

Codex 会测试冻结输入/WritePlan 摘要、来源变化、有效文件复用、不完整或篡改文件保留后重写、未知 staging 文件拒绝、控制符失败/取消不发布、重新恢复的 attempt 历史，以及锁定译文不被覆盖。恢复仍重新验证全部来源文件和 frozen DB hash，不混用当前数据库译文。恢复后输出清单继续声明原输入 revision。外部后端代码、私有字体和批准图片发生变化时不静默复用未经复核的结果。
