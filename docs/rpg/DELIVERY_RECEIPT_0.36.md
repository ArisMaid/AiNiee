# 0.36.0-dev 本地开发包交付记录

2026-10-22，Codex。运行/源码封包提交：5b986a6（完整SHA见同目录封存DELIVERY.json）。
目录：dist-rpg/releases/0.36.0-dev-5b986a6。仅本地交付，未push、开PR或在线发布。
完整目标仍active，P0及全部计划未完成；Windows Sandbox按用户安排稍后启用，
本轮未修改宿主功能。真实模型和其他游戏验证仍后置。

| 交付物 | 字节 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.36.0-dev-windows-x64.zip | 254402274 | 315c5b2e51da94b500439158e74e6cc05ee95062336fee800035ce35ac999c74 |
| AiNieeRPG-source-5b986a6.zip | 52606455 | 8596a0bacaa482489381b995d46165f94dcb97ccc2ee3b181a88153419aca7cf |

## 变更与源码核验

为8个动态颜色章节目标和地图解锁提示新增25个可写正文位置，其中24个使用批准
AST节点的固定prefix/suffix。固定颜色边界由原节点保存，unit仅包含正文，原模板
表达式和函数逻辑保持；没有放宽全局TokenPolicy或增加通用动态模板框架。新能力
js_fixed_affixes_v1由profile/工程显式声明，实际旧0.35 EXE拒绝新工程且DB保持。

当前18644单元/974接受记录；原18619单元和949记录/锁逐项保持。包括16个属性名
原文锁与11个装饰标题SOP锁；新增25项为中性验证样例，974不是正式中文译文数。
原文整字节往返、错误边界/能力/残缺控制拒绝、两文件混合AST及未批准字节审计通过。
完整9570文件副本构建183.54秒、verify13.57秒，字体配置保持、静态缺字0。

VM核对45章节编号、37静态目标保持和8动态目标原表达式组合；地图5种状态保留
标志位/名称/icon260/音效/repeat行为，10份完整组合的控制符一致。原装Game.exe
完整副本受控运行8目标窗口（最大461.16px宽、84px高）和地图Ticker（206.17px宽）
通过；原窗口/字号保持，截图已查看，正常退出0、无捕获异常/console.error、输出
hash保持。用私有存档/固定帧和演示窗口，非完整Scene6导航或自然/物理输入。
失败探针及修正原因见E03_FOLLOWUPS_EVIDENCE.md，离线manifest仍not_run。

## ZIP解压后的实际EXE

3657软件文件、7156 PYZ模块；8类明确排除依赖数量均0。40字体文件均为Matplotlib
附带字体，未打包游戏字库。源码890成员，未含私有素材、工程DB、凭据或worker日志。
源码/便携隐私审计和7项SHA256SUMS通过，旧0.35封存7项与保护主库保持。

| 动作 | 结果 | 秒 |
| --- | --- | ---: |
| 离线self-check | 通过 | 1.16 |
| 实际GUI打开当前工程 | 18644行、974记录，控件可见，截图已查看 | 7.09 |
| 完整源码输出verify | changed_files为空 | 12.89 |
| 新25位置SDK重提取 | 原图/接受记录/锁与能力保持 | 0.76 |
| SDK构建 | 两脚本与源码SDK逐字节一致 | 0.94 |
| SDK离线verify | 通过 | 0.31 |

仅使用宿主System32 PATH和隔离用户目录，不代表干净Windows验收。未重复整款游戏
冻结EXE构建、全套回归或新增测试套件；没有模型请求、DeepSeek worker或删除操作。

封存报告中的任务统计28/5/1是封包当时快照。随后依据原计划16.3核定H02已实现的
v1范围，当前29已实现/4部分/1用户后置；见IMPLEMENTATION_STATUS.md和IMAGE_EVIDENCE.md。
这次状态复核不改运行代码或封存ZIP，也不宣称5315张图片均已汉化。随后D02/E04
按映射/上下文和已知窗口/SOP功能范围核定，当前31/2/1；复核依据及未验边界见
SCOPE_ACCEPTANCE_0.36.md。剩余E03与F03继续单列，不把114用途未证实候选称作
114漏翻或脚本全覆盖。封存的两次早期统计均保持为历史，完整目标没有标记完成。

私有记录：work/v36-delivery-checkpoint.json、work/current-dynamic-affixes-checkpoint-v36.json、
work/dynamic-affixes-sdk-checkpoint-v36.json、
work/dynamic-affixes-runtime-v36/34e5500baa3f4f5cbbc4f5ccc27c865c、
work/extracted-package-v36/f21545b822c342428fc63fcac5f03e68/evidence。
