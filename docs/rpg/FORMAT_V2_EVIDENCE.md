# 工程格式 2 验收

当前源码 0.2.0-dev；现有 0.1.1-dev 二进制与 ZIP 校验值保持不变。

## 实现与兼容性

新建工程使用格式 2。旧格式正常打开、只读和普通编辑保持格式 1。高级能力首次启用时，
备份旧库与升级遵循 FORMAT_V2_CONTRACT；备份失败拒绝写入，后续失败则回滚版本、配置、
单元和 revision。能力声明单调增加，未知能力和 bool 版本拒绝；长连接每次写入重核门禁。
字面占位符和显示值守卫的 profile 使用格式 2，旧 profile loader 会拒绝。

Codex 审查补充了提交事务内的规则校验，以及只读冻结库存在非空 WAL/journal 时拒绝使用。
二者分别防止缓存旧校验器绕过新规则、以及 immutable 连接遗漏 WAL 记录。

## 独立测试

完整本机回归：84 passed / 59 subtests，包含实际安装的 Translator++、三个实际第三方后端、
Qt 流程、文件级恢复与新增格式/字面标记用例；记录在私有 work/acceptance/
rpg-format-v2-20261016.xml。随后新增的备份打开失败与重试保留用例另行运行记录。
这不是新二进制包或当前游戏新增显示路径的运行验收。

## DeepSeek 交接记录

使用 deepseek-worker，deepseek-flash / reasoningEffort=max / 无 maxTokens 覆盖。
本轮 project-format-v2 的结果为 policy_violation，verified=false，不能算作成功交接。
两次目录级 grep 和一次 todo_write 被守卫拒绝；没有放宽权限或重复重试。
允许的编辑仅指向 ProjectStore.py。受保护测试的快照变化来自 Codex 同时升级测试配置，
这是调度错误；守卫日志未发现 DeepSeek 写入该测试。所有日志和先前快照保留在私有 work。
Codex 接管代码，审查备份事务路径，补充上述保护并独立执行验收。
