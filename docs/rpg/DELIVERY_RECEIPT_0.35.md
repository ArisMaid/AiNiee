# 0.35 本地开发交付回执

2026-10-22，Codex。封包提交d8bee65a498ca420b91b1ac8c22cf8018a22a8e6，
分支codex/rpg-localization-core。已完成本地Windows便携交付；完整A01–H03及P0
仍未完成，保持28已实现/5部分/1用户后置。Sandbox干净Windows验收按用户后置。

发行目录：dist-rpg/releases/0.35.0-dev-d8bee65。解压启动AiNieeRPG.exe。

| 文件 | 大小 | SHA-256 |
| --- | ---: | --- |
| AiNieeRPG-0.35.0-dev-windows-x64.zip | 254396098 字节 | 10e8a4648991897a0c4a88990e45cbdde1b5e7150cc43ee40a1005099888f41f |
| AiNieeRPG-source-d8bee65.zip | 52598449 字节 | c199f0fb5151d115fa7620363c3130ff7fae944c96f3d7253839d23fce52be73 |

3657软件文件、889源码项和7份封存校验通过。实际EXE包含7156模块，8类既定
排除依赖均0；40份随包字体均来自Matplotlib，游戏字体不分发。软件/源码的
私有文件路径、凭据和原游戏文件hash审计通过，0.34七份封存校验及保护主库
保持。无push、PR或线上发布。

## 本次结果

新增11个装饰性英文标题的位置，复用现有10文件AST规则；实际GameBatchRunner
载荷保留英文，提示词现在称“游戏源文字”。没有增加通用解析、排版或恢复框架。
SDK原文整字节往返、人工提交/锁、回写、verify与未批准字节/AST审计通过。

中文候选在原装11px位图中出现真实1px裁顶，常用短词也有同类失败，不能声明
中文标题布局通过。按SOP优先约束，最终10项保留英文原文并锁定；Experience
原英文自身也越界，缩写E X P并锁定后墨迹x0–25/y1–8，在原60×11px位图内。
保留字号、窗口和绘制程序；页面提示链接可筛出11项，CLI/其他入口同样遵守。
这些是已定位且按SOP处理的标题，不是新增11条中文译文。

有限候选清单也已对账：1773个CJK节点为1659项SOP保留、114项未证实显示用途；
851个其他含空白候选为840项保留、11个标题进入工程。分区无重复/遗漏检查
通过，分类不自动产生写入权限；114项不是114条漏翻，不扩张成全脚本/全部英文
或自然剧情覆盖。详细来源、失败历史和逐位置私有清单见E03_FOLLOWUPS_EVIDENCE.md。

完整工程18608→18619单元，原938接受记录/锁和整个旧图保持；现949接受记录
包含本批10原文和1英文缩写。16条属性原文锁、文件表、字体和能力集保持。
静态缺字0，缩写新增字形另查通过。最终9570文件源码构建约195.91秒，独立
verify约15.01秒；9份标题脚本与0.34整字节相同，Scene_Heart缩写仅在批准节点
变化并通过AST审计。profile摘要：
45145cf42a663d12da65b4bb37374dca7ca2b485bcbdfb55213216d47164db22。

原Game.exe/NW0.48.4的实际Menu/Equip/Skill/Item四场景和11次原类标题演示通过，
最终墨迹均在位图内；退出0，无捕获异常/console.error，输出hash保持。明确
使用私有存档、固定帧与受控跳转，不是全部场景导航、自然/物理输入或中文标题
通过。离线manifest仍not_run。初次中文裁切、全原文Experience越界及私有Qt
启动驱动停滞均保留，不改判为通过。

## 新ZIP实际程序验收

ZIP另解压后运行EXE，PATH仅System32，使用内置Node/Qt及隔离用户/日志目录：

| 操作 | 结果/耗时 |
| --- | --- |
| 离线自检 | 通过，约1.17秒 |
| 工程Qt页面 | 18619行/949记录，约7.69秒；提示截图已查看，原库hash保持 |
| 完整源码游戏输出verify | 通过，约14.02秒；未用新EXE重复整份游戏构建 |
| 11位置SOP SDK重提取 | 通过，约1.81秒；原单元/11记录及锁保持 |
| SDK构建/独立verify | 通过，约2.32/0.34秒；10文件与源码SOP SDK整字节一致 |

源码Qt快照及实际链接信号另验证18619→11筛选、10原文锁+1缩写锁，截图已查看。
本机隔离PATH不等于干净Windows；未跑provider、新单元/回归套件或整套回归。
使用后软件hash保持。外部工具、原游戏/工程/存档/截图/字体和编码worker不随
包分发。封存ZIP中的说明仍反映封包前“最新便携0.34”，不回改封包；交付结论
以本回执和本目录DELIVERY.json为准。

私有定位：work/current-headers-final-sop-checkpoint-v35.json（完整副本）、
work/english-headers-final-sop-runtime-v35/7ce03bada00c4b2b9724a80ab69d6a26（原装运行）、
work/header-final-sop-ui-v35/afc0a2160e334e72853ca955e997c9d2（源码Qt）、
work/extracted-package-v35/56574f489113434cb75c8638fc02af30/evidence（实际ZIP程序）、
work/package-build-v35.log及work/package-v35-finalize.log。

本地发行目录的PACKAGE_MANIFEST.json、EXTRACTED_PACKAGE_CHECK.json、
CURRENT_SOURCE_CHECK.json、SOURCE_AUDIT.json、DELIVERY.json及SHA256SUMS.txt
记录封存证据。E03动态提示、E04/H02具体范围、真实翻译与干净环境各自另验；
不把本次局部交付当作完整目标完成。
