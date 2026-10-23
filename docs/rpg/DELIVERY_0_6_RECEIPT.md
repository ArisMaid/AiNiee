# 0.6.0-dev 本地交付回执

代码提交 `cfedc11`；本次仅本地交付，没有 push、PR、远程 Release 或 CI 验收。
软件仍是开发版，完整计划和游戏汉化没有完成。

交付位置：`dist-rpg/releases/0.6.0-dev-cfedc11/`。

| 文件 | 字节数 | SHA-256 |
|---|---:|---|
| AiNieeRPG-0.6.0-dev-windows-x64.zip | 253750568 | 33b3cd39dc6a1f119d1446dcfb1b3fac4cf3e20a943da1f434173c801b97e139 |
| AiNieeRPG-source-cfedc11.zip | 51927208 | 4e12a62cc345b9d024def9fdcd98264bf64f3912df1e92b9400160f458c157e9 |

便携包清单 3615 文件，源码归档 693 成员。游戏内容 hash、私有目录、工程、存档和
凭据模式审计通过；已识别的上游公共示例模式单独核验。软件测试后文件集合和每项
SHA-256 再次一致。`SHA256SUMS.txt` 的七项交付文件校验通过，`DELIVERY.json` 为 ready。
旧版 0.5 交付保持原样。

## 独立验收

从最终 ZIP 新解压到 UUID 目录，实际 `AiNieeRPG.exe` 子进程 PATH 仅含 System32：

- 离线自检、17706 行 GUI、迁移对话框创建/截图通过；离屏字体为 Microsoft YaHei UI，
  未安装或复制字体。迁移按钮完整流程由源码 Qt 测试及当前游戏新建工程另行证明。
- 原有格式 2/3、迁移、三后端/图片、构建取消恢复、校验取消恢复检查通过。
- 新提取任务取消后复用 34 个 JSON，锁定译文保留；显式关联和注册迁移计划应用通过。
- 两次新迁移均重新校验过期译文；此处提交提案状态是 accepted，译文表状态是 translated。
- 旧格式 1 工程摘要读取 17392 单元，数据库 SHA 前后相同。

源码提交对应完整测试 188 passed / 128 subtests。当前游戏另行提取恢复复用
178 JSON + 1 JS，单元图和 27 条接受译文/修订/锁不变；新建工程通过 Qt 迁入 27 条。
原 profile4 数据库仍为 `3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935`。
原游戏 9570 文件集合及 SHA-256 全部一致。

## 证据和限制

私有证据保存在本地，不进入公开软件/源码包：

- `work/acceptance/rpg-0.6-review-final.xml`
- `work/d05-extraction-current-acceptance.json`
- `work/migration-review-current-acceptance.json`
- `work/migration-review-font-acceptance.json`
- `work/extracted-package-check/267e5c52c0b04ef2a402c2e4214607a0/evidence/`
- 交付目录中的 DELIVERY、EXTRACTED_PACKAGE_CHECK 和 LEGACY_COMPAT_CHECK。

首轮新增冻结包检查的驱动把译文状态误断言为 accepted；实际写入已成功，修正驱动为
translated 后，整轮从 ZIP 重新解压验证通过。首次失败目录及原始输出保留，没有修改软件包。

此版本尚不包含迁移任务持久化恢复。当前游戏仍有 17679 条未译；没有真实模型请求、
第二款游戏、其他真实发行版本或独立干净机器验收，也不扩大原有 NW.js 有限路径的结论。
DeepSeek 实现纯文档提取接口及明确关联模块，Codex 完成事务、恢复、GUI、审查和交付。
