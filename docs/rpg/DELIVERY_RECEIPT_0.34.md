# 0.34 本地开发交付回执

2026-10-21，Codex。封包提交851538e834076acc74a904d7aa82f527add1ebee，
分支codex/rpg-localization-core。已完成本地Windows便携交付；完整A01–H03及P0
仍未完成，保持28已实现/5部分/1用户后置。干净Windows验收等用户启用Sandbox。

发行目录：dist-rpg/releases/0.34.0-dev-851538e。

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.34.0-dev-windows-x64.zip | 254391305 字节 | 50424e9b9a069497d3d97d361327fae053505ec4c799c199a0c21aab18a15c43 |
| AiNieeRPG-source-851538e.zip | 52590247 字节 | 9a311699a4d2e02576ba8ec9569e667e9dd368c1c93cb1c487dc7ff7403ef3d7 |

3657软件文件、888源码项、7份封存校验通过。实际EXE包含7156模块，8类既定
排除依赖均0；40份随包字体全属Matplotlib，不含私有游戏字体。源码与便携包
私有路径、凭据及原游戏文件hash审计通过。0.33七份封存校验和保护主库保持。
没有push、PR或线上发布。解压后启动AiNieeRPG.exe。

## 本次实现与源码证据

一条现有AST规则新增SH_Sandbox的49个显示位置：9个随机标点候选和40个部位
显示词。12个部位身份键、一个空值、4个纯标点候选及消息组装/随机逻辑保持。
没有新编解码、数据库格式或能力号。实际SDK提取、原文整字节往返、人工提交/
锁、构建/verify及AST/全部未批准字节审计通过。原函数/随机/词语助手的533组
受控组合和10个原事件块VM通过；样例为中性词，非正式翻译或内容质量验收。

另对1008个CJK候选登记保留依据：公式别名、Keke几何/动画指令、TRP编辑器、
预设注释、测试命令、诊断及已由参数覆盖的源码默认值。不因语言检测授权写入。
结合382个既有技能树身份节点，1773个候选中另383个CJK与851个其他含空白
候选仍须分别审查。9个SH来源没有证明显示入口，仍保留候选。详见
E03_FOLLOWUPS_EVIDENCE.md；E03保持部分实现。

完整工程18559→18608单元，原889接受记录/锁与整个旧图保持，49条样例后共938。
16条属性原文锁、文件表、字体设置和能力集保持；静态缺字0。完整9570文件
源码构建约179.27秒，独立verify约12.63秒，SH_Sandbox与既有规则合并写入审计
通过。profile摘要37d075078da00d00458fd683d39a9527f03a2069ebd2b54ff13539a7932d8113。

同一完整输出另运行原装Game.exe/NW0.48.4；实际13种标点、12类首值与VM一致，
原公共262经原command355/Ticker显示中性组合。样例约89.73×16px，在原
1016×31px位图内，截图已查看。明确使用私有存档、固定帧、随机数及临时台词
fixture，不是自然剧情或全部组合实机排版。首次私有观察误用隐藏窗innerWidth
失败后保留，按原位图核对后通过；未改游戏程序/窗口。最终退出0、无捕获异常/
console.error，输出hash保持；离线manifest仍为runtime_not_run。

## 新ZIP实际程序验收

从已生成ZIP另解压EXE，PATH仅System32，使用内置Node/Qt和隔离用户/日志目录：

| 操作 | 结果/耗时 |
| --- | --- |
| 离线自检 | 通过，约1.14秒 |
| 实际Qt工程页面 | 18608行/938记录，约7.08秒，截图已查看；原工程数据库hash保持 |
| 完整源码游戏输出独立verify | 通过，约11.70秒；不是新EXE重新构建整份游戏 |
| 49字段SDK重提取 | 通过，约0.55秒；全部旧单元、49接受记录/锁保持 |
| SDK构建/独立verify | 通过，约0.69/0.33秒，脚本输出与源码SDK整字节一致 |

实际使用后软件hash与清单保持。此本机隔离PATH验收不是干净Windows或远程CI
证据；未运行provider，未新增单元/回归套件或重跑整套。外部工具和游戏素材不
随包分发。ZIP中的说明在封包时仍写“最新便携0.33”，封存后不回改；最新交付
结论以本回执和本目录DELIVERY.json为准。

私有证据定位：work/current-random-display-checkpoint-v34.json（源码完整副本）、
work/random-display-runtime-v34/01ff666f729649aca6b9448380f08249（原装运行）、
work/extracted-package-v34/5b8acfe6ef43460591150dbc8547147b/evidence（实际ZIP程序）、
work/package-build-v34.log和work/package-v34-finalize.log。

本地发行目录的PACKAGE_MANIFEST.json、EXTRACTED_PACKAGE_CHECK.json、
CURRENT_SOURCE_CHECK.json、SOURCE_AUDIT.json、DELIVERY.json及SHA256SUMS.txt
提供封包证据。未知来源、后续图片/布局范围、真实翻译及多游戏各自另验；当前
版本的可运行与已列明流程不扩张为完整游戏汉化或全部计划完成。
