# 0.9.0-dev 本地交付回执

2026-10-18，源码提交114b0f4。目录`dist-rpg/releases/0.9.0-dev-114b0f4/`。
DELIVERY.json为ready，七项交付checksum通过；没有push、PR或远程Release。

| 文件 | 字节 | SHA-256 |
|---|---:|---|
| AiNieeRPG-0.9.0-dev-windows-x64.zip | 253835203 | ec4d14c981f72ea8f5000bee0ef04301990efb87681128624969e22d89f14fa7 |
| AiNieeRPG-source-114b0f4.zip | 52006884 | 486730999d92f71852a9d7060577e0027eddacd5e50fcebb89faba99129e9aad |

3620软件文件、722源码成员通过素材/凭据审计；验收后软件文件重新核对SHA未变。
源码完整回归246 passed / 207 subtests，含安装版Translator++。

新ZIP解压EXE在仅含System32的PATH下通过12组检查：自检、17716行GUI、格式2/3、
迁移、三后端与图片、构建/校验/提取/迁移恢复、进程树故障及大重复数据比较。
界面新按钮截图已检查，按钮交互由源码Qt证明。旧格式1的17392单元摘要保持DB SHA；
旧profile4摘要派生18254位置，原缓存18248保持不写回，DB SHA仍为3f398694…d935。

新增重复样例有4000个原生位置；Stev/SExtractor分别覆盖4000。RPGMTL的4000条记录
全部保留为歧义，共享组各有2000个地址，报告1163397字节；没有把同文多位置改成
单一地址。新两个插件显示字段回写、数字/逻辑参数保持通过。
四类实际进程树故障继续通过：取消1.269秒、主程序退出0.644秒、输出超限0.898秒、
60秒超时60.350秒；每组三层受控进程均结束，无关自有哨兵存活，没有发布候选。

当前游戏真实Items比较也通过，响应从89988329降到529673字节，3989663个逻辑地址
全部保留，16MB限制不变。两条新显示规则的受控原装Game.exe画面及位图已检查。
新工程17716单元、29条接受示例、17687条未译；原27条和已审核图片保留。
原游戏9570文件集合/hash最终再核对一致，原profile4数据库SHA不变。

实现与边界见 BACKEND_COMPARISON_EVIDENCE.md、PROFILE5_EVIDENCE.md。
DeepSeek实现比较服务和共享索引纯模块，交接均完成、guard无拒绝、受保护文件无变化；
Codex负责方案、消费者审查、集成、独立测试、原生验证及交付。

真实翻译按用户决定后续交给DeepSeek；本轮没有调用翻译模型。自然触发、其余规则、
全量长译文布局、独立干净机器和远程CI未验收，其他游戏/真实版本按用户决定后置。
现有0.8交付保持原样，不把本增量标为完整计划完成。

私有证据：`work/extracted-package-check/fd14d7679416446aa7e068ccfff54b3a/evidence/`、
`work/frozen-backend-comparison/88bf030207cc4e89950217411be318d3/result.json`、
`work/final-v9-original-audit/1348db4c99e04881b4bc57c0c4f5c5e2/result.json`。
最终清单见发行目录的DELIVERY.json、EXTRACTED_PACKAGE_CHECK.json、
LEGACY_COMPAT_CHECK.json、PACKAGE_MANIFEST.json与SHA256SUMS.txt。
