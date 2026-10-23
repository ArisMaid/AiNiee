# 已审计方括号占位符契约

Codex 已确认当前体验版 SNS 的 `message` 进入 CommonEvents 1968 的变量 1913，再由
DTextPicture 显示。114 条消息包含 `[word]`，消费者按此固定字符串替换显示词。另有两条
`[なし]` 哨兵将由提取规则排除，不能作为普通译文。DeepSeek 仅修改
`ModuleFolders/Domain/GameProject/TokenPolicy.py`；Codex 负责 profile、服务、提取、测试与交付。
不得修改其他文件或执行命令。可读本契约和现有 TokenPolicy、测试源码；目录搜索用 glob，
grep 只能指向单个明确文件。不读私有游戏内容、凭据或 worker 日志。

## 最小扩展，保留现有 API

1. `TokenPolicy(custom_commands=(), policy_id='rpgmaker-v2', *, literal_tokens=())`。
   新参数只接受 list/tuple（默认空 tuple），最多 64 个、唯一的字符串。
   每个必须完全匹配 ASCII 方括号标记 `\[[A-Za-z][A-Za-z0-9_]{0,63}\]`。
   拒绝 None、普通字符串、空字符串、重复值、bool、正则式、带反斜杠/换行的内容。
   校验错误抛 ValueError。显式规则才生效，默认不改变旧行为；不硬编码当前游戏的 `[word]`。
   保存不可变 tuple 属性 `literal_tokens`。不要放宽已有未知反斜杠控制符拒绝。
2. scan 把配置的精确、大小写敏感标记作为一个完整 ControlToken（command=`literal`），
   start/end 必须精确；重复、顺序和位置仍按原有 raw 序列验证。与 if/en 完整条件、模板、
   反斜杠控制参数互不拆分。允许最长优先匹配，但仅完整字面量，无正则执行。
3. `ProtectedText` 末尾新增默认空 tuple 的 `literal_tokens` 字段，以维持旧构造兼容。
   protect 将本实例的 tuple 传入，标记仍使用现有 UUID 占位符。
4. restore 除了现有检查，还拒绝模型直接插入任一配置的原始方括号标记；检查必须在移除
   全部合法 UUID marker 的剩余文本上进行，正常恢复的 token.raw 不应被误报。
   复用 UNEXPECTED_CONTROL_CODE 或语义明确的稳定 issue code。也必须拒绝源文没有但配置
   中存在的标记被模型插入。返回 issue，不抛异常。合法输出完整恢复原始字面量。
5. validate 沿用完整 token.raw 序列校验，不允许丢失、重复、改大小写或重排 literal。
   不改变其他字符或自动修复模型输出，不改变 policy_id 默认值，不在模块中操作元数据。

Codex 将独立验证：默认不改变普通 `[word]` 文本；显式配置后 protect/restore；源文多个
literal 与 \V[1]、en(...) 混合；缺项/重复/变形/调序；原始标记注入；构造参数坏类型；
ProjectStore/CAS、OpenCC、场景批次与 profile 规则集成。未来再扩展其他语法需新证据。
