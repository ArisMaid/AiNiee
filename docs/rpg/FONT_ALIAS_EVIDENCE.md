# 自定义字体映射验收

0.2.0-dev，MZ 专用。普通 MV 原生提取回写不受影响，非 MZ 的非空字体别名配置明确拒绝。

## 实现

当前游戏 profile 按 `js/plugins.js` 与 `FontLoad.js` 的 SHA-256 锁定四个名称：
HSJP-Regular、HSJP-Bold、HSJP-ExtraLight、HSerifJP-Regular。配置字体时将这些名称与
捕获字体一并记入工程；`font_aliases_v1` 能力门禁防止旧程序忽略它们。

构建仅向输出 index.html 附加 AiNieeFontAliases.js。脚本在核心管理器加载后、插件启动前
包装 FontManager.load，只替换这些名称的文件参数，保留其他名称、参数、this 和返回值。
不修改原插件、程序变量或字体内容。重复同配置注入保持幂等；不同配置或已经开始的
目标字体加载明确拒绝/记录失败。没有轮询、网络或任意代码执行入口。

生成脚本 SHA-256 进入冻结写入计划；恢复先核对计划，发布后登记还必须核对实际脚本与
index 字节。伪造清单中的脚本 hash 不能替换批准的运行时代码。中断文件保留，不批量删除。

## 证据

完整本机回归 90 passed / 80 subtests，包含实际第三方后端、安装版 Translator++、Qt、
格式升级、字面占位符、字体加载次序和构建恢复。记录：私有
work/acceptance/rpg-font-aliases-final-20261016.xml。

当前游戏构建 d7dd8019f8bd4a30a8e95154f245fdf2 加仪器前通过完整清单验证（9571 项输出，
排除项另见清单）。原生 Game.exe 的受控公共事件 1968 实测：四个名称均向
fonts/AiNiee-Simplified.ttf 发起一次加载，均为 loaded，映射 installed=true / error=null。
DTextPicture 使用名称 HSJP-Regular，实际字符来自捕获字体，中文文本与 120×54 像素位图
及整屏均已检查。19 条已接受演示译文覆盖检查没有缺字。旧译文内容及 revision 保持不变。
私有证据：work/font-nuiit-runtime-evidence.json、font-nuiit-screen.png、font-nuiit-caption.png。

此测试通过隐藏窗口、固定 tick/focus 与指定样例进入场景，不代表自然游玩全路径、完整
随机分支或所有窗口排版通过。测试构建保留大量未译日文，全来源字体覆盖仍未通过。
原游戏 9570 个文件集合与 SHA-256 在运行后再次全部一致。

## DeepSeek 协作边界

font-alias-runtime-v1 使用 deepseek-worker 默认 deepseek-flash、reasoningEffort=max，
无 maxTokens 覆盖。任务在 360 秒超时，workerCompleted=false / verified=false；没有拒绝
调用、越界编辑或保护文件变化。仅留下 FontAliasRuntime.py，不能按成功交接计数。
进程结束后 Codex 审查该文件、实现配置/存储/构建集成，并独立运行上述测试及游戏验证。
日志与产物保留，没有自动重试或放宽权限。
