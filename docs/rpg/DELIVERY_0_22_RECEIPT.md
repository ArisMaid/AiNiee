# 0.22.0-dev 本地交付回执

2026-10-19。运行源码 `2c36e4d4d67caf7039fcd17fe56fe465b59a054b`，分支codex/rpg-localization-core。
本地目录 `dist-rpg/releases/0.22.0-dev-2c36e4d`。未push、PR或远程Release。
旧0.21封存七项checksum保持；本回执在软件封包后提交，源码ZIP对应上述运行提交。

## 交付物和验证

- 便携 `AiNieeRPG-0.22.0-dev-windows-x64.zip`：254126879字节；SHA-256 `9e0dc7061515b8e471da89e2c2549fc8c506e12d6d38986ad3e3b6f480c46ccf`。
- 源码 `AiNieeRPG-source-2c36e4d.zip`：52301494字节、818成员；SHA-256 `118c1a1643ad4624ed1bf6518225b58b39268d6ffa5d2ff529eaa8d7bfdc9357`。
- 3635软件文件逐项hash、ZIP完整性和七项checksum通过；依赖字体40项，均为Matplotlib许可内字体。
- 完整源码548 passed /207 subtests passed，包含安装版T++8.8.9；既有依赖警告1，零skip/fail/error。
- 新ZIP解压后的实际EXE26组通过。仅System32子进程PATH，使用包内Python/Node/Qt，不能代替干净机器。

## 人工译文与锁

旧源码真实子进程在文本UPDATE时退出77，保留原文本却丢失人工锁，已明确复现。0.22通过
明确人工命令在一个Store事务内接受译文、目标锁、revision、proposal/edit和content_revision。
来源/CAS、schema/capabilities、当前token/显示值均在writer内检查。普通自动结果仍不能越锁；
没有临时解锁提交。同文锁不增加文本revision，stale同文重批必须增rev，空未译行可只锁定。

新EXE实际包内模块验证人工命令、拒绝稳定、同文锁、严格类型/显式issue/普通锁、空行锁，
以及主场景分批、canonical拒绝和表格源顺序/行号守卫，共8场景。另在实际文本SQL处退出77，
所属PID 18964独立确认退出，原文本/revision/时间戳/锁保持。触发工程来源和译文保持。
该新专项经可信且故意失败的私有SDK导入钩子调用真实应用模块和GUI命令方法，未声称普通
按钮点击或成功Stev候选。既有GUI/恢复组另验。完整边界见MANUAL_EDIT_ATOMIC_EVIDENCE.md。

## 场景分批和已知上下文缺口

完整文件连续scene区段先于状态/表格选择，再应用预算；排除或未选的其他场景仍是屏障。
空scene不继承已知场景，表格恢复源顺序并拒绝bool行号，请求从SQLite真实单元复核场景。
不能修改缓存scene来混入其他场景。普通文档分批保持。

当前17716单元主库只读复核，17687待译各一次；行预算20、上文3时，旧991批中489混合，
新3173批混合0，图/译文/锁及主库hash保持。增加的是潜在请求批数，没有发送这些模型请求。
previous_items尚未进入模型payload，runner逐批完整图准备的耗时也未据此验证。D02明确
改为部分实现，详见SCENE_BATCH_EVIDENCE.md；没有把分组通过写成完整上下文完成。
另对保留的工程数据库副本测量三次20单元批构造，分别约417.4/441.4/444.9ms；没有
运行模型或整项任务，不含tokenizer，缓存和并发条件不受控。完整图被逐批重复读取是后续
准备过程的优化对象；该小样本不等于已测整个任务启动时间或性能门槛通过。

## 当前游戏完整测试构建

当前源码与新EXE各完成Stev/SExtractor两份构建，每后端六文件、16批准JSON位置、9570清单
文件并verify，另有两份输出元数据。核对实际SDK产物/sidecar、原生JSON/JS、批准图片、
显式字体/映射及所有文件集合/hash；非路由产物在两后端间字节一致，runtime not_run。

| 执行 | 后端 | 构建秒 | 清单文件 |
| --- | --- | ---: | ---: |
| 源码 | stev | 417.27 | 9570 |
| 源码 | sextractor | 213.67 | 9570 |
| 冻结EXE | stev | 382.50 | 9570 |
| 冻结EXE | sextractor | 203.77 | 9570 |

Stev完整输入9570、35903条真实ProgramData及178个JSON输出继续审计。四个音频表55重复键
仅发现，私有归并明示，成品保持原字节且拒绝写定位。源码证据 `work/current-json-builds-v21/ceb44d0edb5d483d88b76aa3c43d4f8f`，
冻结证据 `work/current-json-builds-v21/803d1aafed7f45afa73aa10f549137f1`。
副本31个人工接受示例、17685未译，明确测试构建。原9570文件（含日志/存档）、主库、图、
译文/人工锁、SDK/config均保持，没有真实游戏翻译或游戏启动。

## 审查、协作和保留的失败

新调用图/逐入口清单、接受SQL位置、副作用和后续实施见WRITE_ENTRYPOINT_AUDIT.md；
自定义JSON单位/菜单/备注、RandomTalk.help的类型和实际消费者片段见E02_REMAINING_FIELDS_EVIDENCE.md。
104个unit为空，有实际绘制入口但没有据此开放写权限；179来源hash与原基线一致。

manual deepseek-worker2400秒上限、513.64秒completed/verified:false，3文件，零guard拒绝/
保护变化/协议错误；Codex核对15个after hash及34次read/grep路径。Codex补测并修正None、
空行锁无关token错误和显式阻断issue。scene worker262.385秒，一次目录grep被拒按失败交接；
Codex核对15hash后补修空scene与bool。审计草案772.72秒，3次守卫拒绝按失败交接；14hash/
249次read/grep复核，未直接采信草案。没有向编码worker发送游戏文本或凭据。

首轮完整回归1失败是旧fixture将跨场景目标准备成单批；现在保留全部目标、按真实分批对每批
验证dataset变化不达供应商，18项专项后完整548/207通过。产品场景守卫没有放宽。新私有驱动
前两次丢失控制符反斜杠，修正驱动后实际应用/新EXE通过，未改产品检查。所有失败日志/暂存保留。

## 剩余范围

逐项状态23已实现/10部分/1用户后置；完整计划与P0未完成。D02据实改回部分，旧0.21的
24/9/1只是当时快照。剩余A03、D02、E02、E03、E04、E05、F02、F03、G06、H02；其他游戏
按用户决定后置。实际模型、完整自然路径、全游戏排版/图片质量、干净机器和远程CI仍未验收。
包无游戏素材、工程/译文、用户字体、截图、凭据或worker日志；没有批量删除、远程发布或
把局部通过当作全计划完成。目标继续推进。
