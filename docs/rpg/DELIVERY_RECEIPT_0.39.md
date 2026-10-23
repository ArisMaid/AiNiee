# 0.39.0-dev 本地开发包交付记录

2026-10-23，Codex。运行/源码提交3f54f7ddd3f5b6c1d4a87ba1e7b877ab9588f530。
目录dist-rpg/releases/0.39.0-dev-3f54f7d。仅本地交付，没有push、PR或在线发布。
完整目标未完成；2026-10-23追加独立F03验收后为33已实现/0部分/1用户后置H03。

| 交付物 | 字节 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.39.0-dev-windows-x64.zip | 254431266 | ff1517d4d0ebdc0a4ac2085498be19d00de0b83b83b7b57240d9cdbbde8666c9 |
| AiNieeRPG-source-3f54f7d.zip | 52645605 | 6a4070abda2def9614c7ec98dd38af0f366d69e1d2410e6e3974776171397b0b |

## 本版变化与源码验证

补齐初次请求后最多两次重试：表格只重发失败ID，保留首次marker/版本；游戏主
翻译/润色最多三轮，仍允许用户更低设置。71项现有专项通过；当前工程备份中的
11个真实job及实际主控制器6个job验证部分成功、持续失败、人工冲突和次数限制，
均使用本地响应，没有调用提供商。见FAILED_RETRIES_EVIDENCE.md。

新工程持久记录静态入口/核心/标准缺项/加密证据；NW版本静态阶段标未测，现有
原装0.48.4证据与当前运行二进制hash相符。当前真实MZ报告、MV www合成、持久化
重开/提取、冲突核心拒绝及3项既有适配器检查通过。摘要按9570文件/1804940725字节
计算1.68GiB资源基线，实际Qt构建/Stev按钮提前说明额外副本和历史目录空间；原
工程保持，未物理悬停。见SCAN_EVIDENCE.md。

原计划12.4按用户避免底层过设的约束采用既有一次请求协议与父作业职责；已经逐项
对照并登记实施决定，不宣称原流式消息集合兼容。见WORKER_PROTOCOL_DECISION.md
与REQUIREMENT_COMPLETION_AUDIT.md。没有新增通用队列、空间预约或清理框架。

## 解压ZIP中的实际程序

3663软件文件、901源码成员、7156 PYZ模块及7项校验和通过。新增6份公开说明随
便携包提供；8类明确排除依赖数量均0，40字体均为Matplotlib附带字体，没有游戏
字库、素材、私有DB或凭据。旧0.38封存、当前工程DB和受保护主库保持。

| 动作 | 结果 | 秒 |
| --- | --- | ---: |
| 离线self-check | 通过，含实际Node解析 | 1.24 |
| 当前工程GUI | 18659行、989记录、控件可见，主页面截图已看 | 7.72 |
| 0.37完整游戏输出verify | 通过 | 19.16 |
| 合成目录scan | 识别证据、字节/文件数正确 | 0.46 |
| 合成工程extract | 2单元 | 0.41 |
| 新进程summary重开 | 识别报告持久保持 | 0.33 |
| 当前工程summary | 18659/989、9570文件与资源字节正确；旧识别报告明确未记录 | 0.71 |

从实际EXE提取7个变化模块的完整语义代码结构，与验收源码相同；不把文件名/行号
信息作为语义。这覆盖Version、Detector、GameBatchRunner、GameTableExecution、
GameProjectService、TaskExecutor、GameProjectPage。未声称在冻结进程中执行17份
重试请求或直接观察冻结按钮tooltip属性；源码实际请求与Qt属性、冻结代码一致性
及冻结GUI/CLI行为分别记录。

没有重复全量回归或新增测试套件，没有新完整游戏构建。完整输出仍明确是0.37，
本版请求/识别/提示变化不改变其脚本回写；实际GUI/静态校验不代表自然游玩、所有
脚本或真实模型质量通过。宿主System32 PATH隔离不等于干净Windows。

## 封包后的独立沙盒验收（2026-10-23）

F03已通过。实际Windows Sandbox的原PATH无Python/Node；本版EXE摘要与封存清单
匹配，self-check exit0/2.04秒、GUI exit0/9.11秒。合成2行工程的中文页面、日语→
简中设置及关键控件截图已查看；用户确认独立正常窗口已打开。自动offscreen
检查与正常窗口确认分开，未声称自然交互、游戏或模型质量验收。

完整诊断取得映射路径的SQLite disk I/O error；同来宾本地自检通过。包装脚本
自行WaitForExit造成ExitCode=null的误判已改-Wait -PassThru并拒绝缺失退出码。
实际PowerShell5.1的成功0/故意错误2及完整stderr捕获通过。按SOP把工程/缓存
放来宾本地，完成再回传；不改SQLite底层或路径守卫。旧失败与来宾报告保留。

来宾checks_passed=true，clean_machine_accepted仍为false；独立验收另存。
dist-rpg/acceptance/0.39.0-dev-3f54f7d-20261023含验收摘要、修正生成器及2项
checksum。原软件/源码ZIP和7项封存摘要全部保持；原源码ZIP内辅助脚本为旧
快照，重现时采用独立附件或当前Git脚本。详见SANDBOX_ACCEPTANCE.md。

当前18659单元/989接受记录的只读确定性检查通过，当前问题0；520条为历史
记录，DB未变。当前完整输出仍为0.37；没有新整游戏构建、模型请求、测试套件
或第二个沙盒。真实翻译与其他游戏按用户安排后置，完整profile未据此正式验收。

私有证据：work/v39-delivery-checkpoint.json；work/failed-retries-checkpoint-v39.json；
work/scan-evidence-checkpoint-v39.json；work/disk-gui-checkpoint-v39.json；
work/extracted-package-v39/8ffbbc7414bf462e804eb91cb1cf0461/evidence；
work/windows-sandbox-acceptance/f374971d0e2d42e79c7584c46d9bbe23/results。
