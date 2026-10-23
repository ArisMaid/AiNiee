# 0.38.0-dev 本地开发包交付记录

2026-10-22，Codex。运行/源码提交febc8fcf07fd6f1be916dd31ac80629bd2ad5ab8。
目录dist-rpg/releases/0.38.0-dev-febc8fc，仅本地交付；没有push、PR或在线发布。
32已实现/1部分F03/1用户后置H03保持，完整目标active，P0未声明通过。

| 交付物 | 字节 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.38.0-dev-windows-x64.zip | 254409693 | b2e5bdd6a2f536b88518a8d69ad49d584fcc9bbf388194dadc9dd9d5eb998740 |
| AiNieeRPG-source-febc8fc.zip | 52626865 | e71e7c86e986c60cb4692edc949327519a030ee650f7bbef49be322b41679e2c |

本版只在既有GameBatchRunner中增加按权威kind选择的固定翻译指引，覆盖短UI、
名称、对话、物品/技能说明、叙述和战斗消息，共用原术语表。当前工程7类、三种
模式共21份实际请求准备通过，控制符还原、参考边界及混合类型通过；未知kind
的原始文字不进入系统提示。细节见KIND_PROMPTS_EVIDENCE.md。

3657软件文件、896源码成员和7项校验和通过；软件/源码隐私审计无私有游戏内容、
凭据或游戏字体。40字体均为Matplotlib附带字体，8个明确排除依赖族数量均0。
旧0.37封存7项校验和、当前工程DB及受保护主库保持。

| 解压ZIP中的实际程序动作 | 结果 | 秒 |
| --- | --- | ---: |
| 离线self-check | 通过 | 1.09 |
| 当前工程GUI | 18659行、控件可见，主页面截图已看 | 6.74 |
| 上一版完整游戏输出verify | 通过 | 15.91 |

从实际EXE的PYZ提取_style_guidance、_system_prompt及GameBatchRunner.__init__，
其语义代码结构与通过21份请求准备的源码一致；忽略文件名/行号信息。这是冻结
代码一致性证据，没有将其称为在冻结进程中实际执行21份请求。无模型请求或新
测试套件，未重复整套回归；请求提示不影响回写，沿用明确标记为0.37的完整输出，
没有再次构建9570文件。宿主System32 PATH隔离检查不代表干净Windows。

用户现已确认进入Windows Sandbox桌面。实际配置来宾首次运行0.37软件，ZIP和
EXE摘要匹配，原PATH无外部Python/Node；自检失败，尚未进入GUI步骤。Windows
PowerShell5.1将native stderr转换为终止错误，只记录traceback首行，完整原因
待诊断，不归因于某个库或路径。保留失败结果，并提供一次点击的诊断脚本，比较
共享目录/来宾本地目录且直接保留stdout/stderr。当前0.38尚未在Sandbox运行。

本收据与后续诊断入口在运行封包提交之后加入，不重写已封存ZIP/清单。F03和
原计划完整完成审计仍未关闭；真实模型、其他游戏及既有自然路径/SOP限制保持。

私有证据：work/v38-delivery-checkpoint.json；work/kind-prompts-checkpoint-v38.json；
work/extracted-package-v38/41cf0e7dd9174ddc97209de4847ee7bd/evidence；
work/windows-sandbox-acceptance/f374971d0e2d42e79c7584c46d9bbe23/results。
