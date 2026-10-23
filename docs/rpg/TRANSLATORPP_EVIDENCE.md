# Translator++ 8.8.9 接入验收

日期：2026-10-16。安装来自官方公开发行版，未使用付费版或非官方修改版。

- 官方下载页：https://dreamsavior.net/download/
- 固定发行版：https://github.com/dreamsavior/TranslatorPlusPlus/releases/tag/8.8.9
- 文件：Translator++_8.8.9_x64_.51895b12.7z，221133957 字节。
- SHA-256：2389b58a1315870ca4bf3ee7b2eff06d65b2b635a5c56a9b3b0a59b1c1d9131c。
- 安装位置：仓库私有 `.tools/translatorpp/8.8.9/app/Translator++`。
- 实际 package.json 版本 8.8.9，RMMV/MZ Parser V2 版本 2.19。
- 实测 API：127.0.0.1:22883，GET /api/tools、POST /api/exec，均返回实际进程结果。

## 支持范围

AiNiee 导出 `.trans` 译文工程和已登记哈希的 sidecar。T++ 可以直接打开、编辑、保存；
也可以通过本地 API 推送与取回。每行绑定 unit_id、source_hash、dataset_revision 和
expected_revision。回传先检查全部行身份和原文，再逐条经 TranslationCommitter 校验。
锁定、控制符错误、过期版本及来源变化不会覆盖现有译文。

T++ 8.8.9 的 Trans.sanitize 会按每个文件的原文列去重。桥接将相同原文分配至不同的
交换表，保留每行单独的 ID 上下文。因此即使使用原版 T++ 重新打开工程，也不会合并
“はい”的选项译文与对话译文。交换工程的 gameEngine 为 ainiee-rpg-exchange，最终
游戏副本由 AiNiee 原生构建器生成。

## 真实往返证据

`tests/game_project/test_translatorpp_acceptance.py` 的可选安装集成测试实际执行了：

1. 探测已安装版本和所需端点。
2. 推送合成 MZ 工程的译文交换表。
3. 经 T++ API 将两处相同原文分别编辑为不同译文并导回 SQLite。
4. 把含引号及 JavaScript 样式字符的文本作为普通单元值写入，确认没有执行它。
5. 调用 T++ 的原生 MZ 提取器、编辑物品名称并导出至新的候选目录。
6. 核对物品 JSON 的目标变更及来源目录哈希。
7. 对候选导出执行全文件结构审计，拒绝存在非批准语义差异的结果。

发现的上游限制：合成地图中，一条没有重复 101 消息头的独立 401 对话指令在 T++
原生导出后丢失。测试把该行为保留为拒绝候选的回归样例。物品字段的导出成功不能
代表整张地图往返通过。工具不会自动采用 T++ 引擎导出或混合其回写结果。

测试启用方式（仅使用合成数据）：

```powershell
./Tools/start_translatorpp.ps1 -Headless
$env:AINIEE_TEST_TRANSLATORPP='1'
./.venv-rpg/Scripts/python.exe -m pytest tests/game_project/test_translatorpp_acceptance.py -q -p no:cacheprovider
```

HTTP 客户端只允许显式端口的 127.0.0.1，拒绝代理、重定向和其他主机；请求及响应
限制为 16 MiB / 32 MiB。只生成固定代码模板，译文使用 JSON 编码。自动化接口本身
具有 T++ 进程权限，因此启动与退出仍由本机管理，不将接口暴露到局域网。
T++ 软件和其附加组件不包含在 AiNiee 便携包中。
