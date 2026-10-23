# 干净 Windows 验收

2026-10-23启动入口补订：未来构建及0.41启动补订包提供同目录的
Start-AiNieeRPG.cmd/ps1。正常入口明确windows平台、portable模式、UTF-8和独立
启动日志；默认不设离线限制，也不更换已有配置/缓存目录。按需显式指定Offline
和DataRoot才使用独立离线诊断。它采用来宾已验证的启动方式，但并非重新执行
了一轮沙盒；不能把本段改称0.41新来宾验收或首次黑窗根因修复。

Windows PowerShell5.1实际完成默认、独立离线/工程参数及CMD入口三例；中文、
空格、&、!及工程参数尾部反斜杠保持，启动日志和父进程环境恢复均通过。
发现PS5.1会将方括号目录当通配符且多次解析日志路径，启动器对程序/日志目录
中的方括号、反引号明确拒绝并提示改目录，不引入额外启动框架。工程参数里的
方括号不受此限制。之前失败的私有探针保留，最终记录见
work/portable-launcher-checkpoint-v41.json。

同一实际0.41 EXE的宿主Windows原生启动另观察到标题、非零句柄及Responding，
中文初始化完整且stderr为空。检查结束由已拥有的Windows Job清理本次测试树，
不是正常退出或新沙盒通过证明；脚本不自动将gui_confirmed设为true。早期检查
误将关闭请求当成直接退出，实际源码要求确认弹窗，该次超时失败保留。
私有索引work/portable-launcher-native-checkpoint-v41.json。正常用户入口启动后
直接返回；Windows原生重定向日志句柄由子进程继续使用，不维持额外后台日志服务。

0.40最新结论（2026-10-23）：**F03按本节所列启动SOP通过实际Windows Sandbox
验收。** 自动自检和offscreen GUI均exit0，包/EXE摘要及50个证据文件独立核对，
三张中文截图已查看。随后正常启动诊断在第6秒采样中观察到标题为
AiNiee RPG 0.40.0-dev的响应窗口，用户明确确认“已执行，主界面出现”。
最初只有黑色控制台、Esc无帮助的失败记录保留，没有追认为成功。

本次ZIP SHA-256为
8634201b8787d23bb9fed7a20ccde95ec6aacd87efab3d75f8606830fee84b6b。
EXE SHA-256为ad08c0ebeb605a9acbe909c955d8d648b7e13147937cebcb7abaa2adef63862c；
与封存清单一致，原7项封存摘要及两个受保护工程DB保持。来宾原PATH无Python/
Node，系统为NT10.0.26100.0，Networking=Disable。合成工程2行、日语→简中、
关键控件和中文624像素墨迹通过；self-check的JSON、补丁、加密图片和随包Node
解析通过。本次来宾脚本未记录精确PowerShell版本及单步骤耗时，不继承宿主或
0.39数值。原clean_machine_accepted=false报告保持不变。

私有证据索引work/sandbox-acceptance-checkpoint-v40.json；本轮原始结果在
work/windows-sandbox-acceptance-reconfigured-v40/03d326cda5734e6d81812b888419172d/results/2914caa5b3be4366b490aa78b045d85a。
正常启动诊断已在同一沙盒执行：复用已核对的程序，没有存活旧AiNiee实例；
Windows平台qwindows.dll加载、简中初始化和正常窗口均有记录，实际PowerShell
版本为5.1.26100.9711。其工作目录、用户配置及缓存使用新的来宾本地目录，明确
设置offline/portable、QT_QPA_PLATFORM=windows、QT_DEBUG_PLUGINS=1，并重定向
stdout/stderr。此次同时改变多项条件，**没有隔离首次停滞的单一根因**；验收
结论限定于这些已记录条件，不声称直接双击EXE的所有环境都已修复。

独立可交付摘要及生成器附件在
dist-rpg/acceptance/0.40.0-dev-911c508-20261023，含两项SHA-256；不含私有截图、
工程或原始日志。原来宾clean_machine_accepted=false、诊断normal_gui_accepted=false
保持，由宿主结合直接证据与用户确认另作验收。原封存软件/源码ZIP及7项摘要不改。
当前Tools/prepare_sandbox_acceptance.ps1及现有配置的未来guest.ps1已采用上述
正常启动条件，本地配置/缓存与完成证据分开，启动日志保留在来宾normal目录。
两份脚本经实际PowerShell5.1语法检查；未再次运行整套组合来宾流程。原已执行的
guest脚本另存备份，当前源码ZIP仍是封包时快照，后续重现使用此独立附件。

宿主源码的原生Windows Qt隔离探针已创建主窗口对象并进入事件循环，exit0；
15秒栈快照曾停在标题栏setTitle。探针主动抑制宿主显示，不是来宾正常窗口通过
证据，也没有据此确定沙盒根因。0.40实际正常窗口证据来自上述来宾诊断与用户
确认。以下为单独保留的0.39历史记录，未用它替代本轮0.40证据。

沙盒退出后，其本地软件、SQLite工程及缓存会重置，这是本次临时工作区的约定。
input和results放在宿主，分别只读和可写映射；每次打开配置会新建来宾本地工作区，
完成后将证据写回宿主results。异常退出时未完成的本地检查可能没有结果，可重新
打开同一配置从头运行，无需恢复旧C:\RpgLocal-*路径。保留宿主整套验收目录，
不要把SQLite工作区改回映射盘。修改映射后的WSB须在下一次启动时加载。

2026-10-23，Codex独立复核。**F03在当前0.39便携软件范围内已通过**。
实际Windows Sandbox的离线自检、GUI检查、中文截图和正常窗口确认均已取得；
不等于真实游戏全汉化、模型质量或跨游戏兼容性通过。

## 0.39历史直接证据

软件为封存运行提交3f54f7d，未重打包。便携ZIP SHA-256：
ff1517d4d0ebdc0a4ac2085498be19d00de0b83b83b7b57240d9cdbbde8666c9。
来宾EXE SHA-256：083fdf4a50a605b8c9839d4809a1d0e3f4f0dbfa8215394ccd5c1a3b2b953add。
来宾记录与宿主封存清单相符，3663软件文件和原7项校验和保持。

| 检查 | 实际观察 |
| --- | --- |
| 环境 | NT10.0.26100.0；PowerShell5.1.26100.9711；原PATH无Python/Node命令 |
| 实际沙盒 | 原配置/进程及用户桌面确认；只读input、可写results，配置Networking=Disable |
| 本地self-check | exit0，2.04秒；JSON提取/回写、补丁、加密图片和随包Node解析通过 |
| GUI检查 | exit0，9.11秒；合成工程2行、日语→简中、关键控件可见，中文墨迹624像素 |
| 独立图片复核 | 已查看gui.png、translation-view.png、text-render.png，中文无空白/方框 |
| 正常GUI | 独立启动；用户确认“已运行，正常窗口已打开” |

GUI自动截图来自offscreen检查；正常桌面窗口由用户确认。两者分别记录，没有把
进程ID或offscreen图当作自然交互证明。本轮没有物理按键全流程、模型请求或游戏
启动；自检runtime_validation仍为not_run。GUI stderr保留FreeType某face打开警告
和offscreen propagateSizeHints警告；exit0、中文截图及实际文字墨迹均通过，未将
它们隐去或扩张成所有系统字体均已验收。

来宾原result.json的checks_passed=true、clean_machine_accepted=false保持原样。
独立验收另存，未修改来宾报告使其变绿。私有证据：
work/windows-sandbox-acceptance/f374971d0e2d42e79c7584c46d9bbe23/results/fbd7199e360746bb969604d537601eb1。
独立完整索引为work/sandbox-acceptance-checkpoint-v39.json，含51个证据文件的摘要。
可交付的摘要/修正脚本在dist-rpg/acceptance/0.39.0-dev-3f54f7d-20261023，
与原sealed release分开；不携带私有工程、游戏素材或原始日志。

## 故障与修正

1. 原0.37来宾失败只留下traceback首行，完整栈已丢失；不追认该次具体根因。
2. 本轮0.39对映射结果目录做自检，完整栈表明ProjectStore.create的SQLite发生
   disk I/O error。同版、同来宾改用本地目录后self-check输出passed=true。
   这证明本次映射路径不适合作工程工作区，不声称所有共享文件系统均有此问题。
3. 首轮0.39包装脚本在Start-Process后自行WaitForExit，ExitCode却为null，误判
   上述本地成功为失败。已换为-Wait -PassThru并拒绝缺失退出码。宿主实际
   PowerShell5.1验证成功exit0、故意无效CLI exit2及1197字符stderr均正确保留。
4. 用户执行Continue-GUI-Checks.cmd，复用已校验的解压程序，新建本地证据目录，
   自检与GUI均exit0。旧失败结果保留；没有关闭现有沙盒或启动第二个实例。

采用操作约定：软件、工程、缓存和检查工作目录放在来宾本地磁盘；宿主映射目录
只收完成后的日志/结果。没有改SQLite事务策略、放宽路径守卫或增加存储兜底框架。

## 后续重现

仓库根目录可生成新配置（只准备，不启用功能或启动沙盒）：

```powershell
& '.\Tools\prepare_sandbox_acceptance.ps1' -PackageZip '.\dist-rpg\releases\0.40.0-dev-911c508\AiNieeRPG-0.40.0-dev-windows-x64.zip' -ExpectedSha256 '8634201b8787d23bb9fed7a20ccde95ec6aacd87efab3d75f8606830fee84b6b'
```

路径参数分别引用。新生成器把工作区与SQLite放在来宾本地，完成后复制证据到
映射results；使用实际进程退出码和独立stdout/stderr。每轮用新GUID，不清理旧
文件，不映射私有游戏或凭据。打开新配置前处理已有沙盒由操作者安排，不能为了
检查而擅自关闭用户实例。原配置字段参考Microsoft的Windows Sandbox WSB说明。

原0.39源码ZIP内的生成器是封包时快照，仍包含旧映射工作区约定；请使用当前
Git中的Tools/prepare_sandbox_acceptance.ps1或上述独立附件。修正仅涉及验收
辅助脚本，运行EXE与原ZIP/清单/校验和均未重写。远程CI仍未运行，不以宿主
PATH限制、静态准备或已有Python的源码CI替代本次实际来宾证据。
