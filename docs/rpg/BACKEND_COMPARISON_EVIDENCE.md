# 持久化后端比较与界面任务控制

2026-10-18，0.9源码增量。CLI `backend-check` 与新 GUI“比较后端提取…”共用
BackendComparisonService；结果保留 counts/native_only/backend_only/overlap/ambiguous。
比较只读取工程捕获的 JSON，先限制字节并核验来源 SHA；数据集变更拒绝发布过期报告。

每次比较创建 BACKEND_COMPARE 任务，持有 ProjectLock、JobLease，支持暂停/继续/取消。
COMMITTING 后保存带 job_id 和 dataset_revision 的独立 JSON 报告，再完成任务记录。
报告为参考，不导入译文、不改变路由、不使额外字段自动获得写入权限。
中断保留已有产物，重新比较创建新尝试，不假装恢复第三方内部计算。

GUI 设置回写后端原先未转发候选任务 ID，控制按钮不能作用到该执行；现通过
configure_route 的 on_job 传到候选服务，主页面已有任务控件可正确控制。

DeepSeek 通过更新后的 deepseek-worker 实现比较服务初稿，106秒完成，guard无拒绝、
受保护文件无变化；Codex审查时补上报告本身的job_id，并负责 CLI/GUI 接入和独立测试。
专项7项通过：三个实际固定后端、取消前不派发、取消后不发布、数据集改变、捕获篡改。
Qt完整专项8项通过，其中新增比较入口取消/成功和路由任务控制两项。
首轮数据集测试误用相同集合（存储按设计不递增修订），修正为真实集合变化后通过。

源码完整回归246 passed / 207 subtests（含安装版T++）。新ZIP实际EXE的大重复报告、
两处显示字段及各恢复/进程故障验收见 DELIVERY_0_9_RECEIPT.md。

## 实际游戏的重复地址膨胀

真实 Items.json 为695193字节，RPGMTL产生3039条记录、3989663个逻辑候选地址，
最大歧义1997个。原响应89988329字节，正确触发16MB限制。新增可选共享地址池，
响应降到529673字节，记录数和全部逻辑地址不变；16MB边界保持。
内部复用来源索引的地址列表，避免编码前也产生二次方数量的引用。
报告同样使用共享组，保持多地址歧义，不能因此授予写入权限。格式见 COMPAT_CONTRACT.md。

DeepSeek实现纯 ExtractionPointerPool，103秒完成，guard无拒绝、受保护文件无变化；
Codex负责序列化/父进程验证/比较报告接入及真实膨胀诊断。独立专项21 passed / 11 subtests，
包含真实RPGMTL的2000条同名样例、共享引用、全部地址保留、畸形引用/版本拒绝及既有回写。

修正后当前游戏 Items 三个实际后端均完成比较，接受译文和content_revision不变：

| 后端 | 原生位置 | 后端记录 | 重合 | 原生独有 | 后端额外 | 歧义 |
|---|---:|---:|---:|---:|---:|---:|
| Stev | 727 | 3039 | 727 | 0 | 2312 | 0 |
| RPGMTL | 727 | 3039 | 664 | 63 | 253 | 2122 |
| SExtractor | 727 | 727 | 727 | 0 | 0 | 0 |

计数是地址/记录，不是已验证的新增显示文字。旧工程DB保持不变。
私有证据：`work/profile5-backend-comparison.json`、`work/profile5-pointer-pool-proof.json`。
