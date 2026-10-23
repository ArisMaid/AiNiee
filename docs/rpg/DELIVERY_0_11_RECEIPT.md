# 0.11.0-dev 本地交付回执

源码f636725；3623软件文件、738源码成员、七项checksum；DELIVERY为ready。
本地目录dist-rpg/releases/0.11.0-dev-f636725，无push、PR或远程Release。

- 便携ZIP253871527字节，SHA-256
  `3227257036c9fb510c00e09720e09c0490a4c26effaa4f11b7e8a73dc80513e7`。
- 源码ZIP52044129字节，SHA-256
  `d2087b24444c37bfcc1f186974d4c234cf06942954d2cd1c8b9d2e302d028714`。

新增RPGMTL CommonEvents虚拟子工程桥接与按ID任务查询，细节见
RPGMTL_COMMON_EVIDENCE.md。只启用含批准修改的子工程，原生整文件差异核对保持。
上游空355+655在含目标子工程时仍拒绝，不静默降级，JS插件尚未接入。

源码315 passed / 207 subtests，含安装版Translator++。当前游戏图副本三个接受位置
（含一个受限122字符串）通过真实RPGMTL路由及9570输出校验；取消恢复复用6432文件，
17716单元/29条接受译文和原profile5 DB保持。首次上游失败、取消尝试与旧能力断言
均保留，不把失败改判为成功。

新ZIP解压EXE仅System32 PATH完成14组验收。新增CommonEvents组通过6个位置回写、
两条编码字符串、BOM、同文不同译、无关坏事件保持，以及含目标坏事件的候选/构建拒绝。
既有恢复、图片/三后端、四类进程树故障和脚本回写防护继续通过。
解压根work/extracted-package-check/1d07359e113e45ff9620ae83be23dc46。
GUI17716行、122字体家族、624墨迹像素，主页面截图检查；新增后端选择交互由源码Qt
证明，不宣称完整桌面/自然游玩验收。软件验收后全部hash保持，旧格式1及profile4只读
兼容通过。

原9570文件集合/hash与原profile4 DB保持，最终审计：
work/final-v11-original-audit/cd441f0edfdc4fa4bd20b47ef36133e3/result.json。
DeepSeek完成纯映射模块且guard无拒绝；Codex负责审查修正、接入、独立测试和交付。

真实翻译由用户决定后续交给DeepSeek，多游戏/真实其他版本后置。全游戏排版、完整
自然游玩、远程CI和独立干净机器仍未验收。旧0.10交付保留，本回执不表示全计划完成。
