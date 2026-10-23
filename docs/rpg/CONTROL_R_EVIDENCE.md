# 当前游戏 R 控制符的保留规则

2026-10-17。0.3 包仍阻断此控制符；0.4.0-dev 源码在取得以下证据后启用。

当前游戏 Skills.json 中有 14 个来源单元含 R 控制符。基类 obtainEscapeCode 会消费
这个名称，但基类和已核验的 Base/Message/DText 覆盖均不处理 R；KdCommon 处理的
颜色重置是 CR。不能将两者猜测为同一个命令。

实际原生渲染探针比较普通文字、尾部 R、着色文字、着色加 R 和着色加 CR：
有无 R 的文字像素 SHA 与宽度完全一致，着色后的颜色也一致；CR 会重置后续颜色。
探针使用游戏实际 Window_Base，未执行宿主端 eval 或修改游戏源文件。

因此只在当前指纹绑定的 profile 中将 R 声明为必须原样保留的命令。新增指纹包括
rmmz_windows、KdCommon、EscapeCharacterSe、DarkPlasma_TextLog 和 DTextPicture；
FontLoad 已有指纹继续保留。更改其中的消费者会导致 profile 匹配失败，不能把当前
结论沿用到别的插件版本。

源码独立检查确认默认策略仍报未知；当前 profile 的策略可保护和还原 R，缺失或
改为 CR 都拒绝。新建当前游戏工程的 14 项均通过扫描，阻断控制符数由 14 变为 0。
实际 SQLite 中故意移除 R 或改成 CR 的两个提案被拒绝，既有有效译文保持不变。
这不表示所有插件或未触发文字来源已经覆盖。

0.4 原生副本的实际技能说明控制器已显示中文。文件中的反斜杠与运行时 ESC 编码
分别核对；等价还原后内容和控制符逐字一致，运行后 JSON 文件 SHA 未变。
该指定说明条目未被授予或使用，不冒充自然习得技能的流程验证。

私有证据为 work/r-control-consumer-trace.json、native-r-control-evidence.json、
profile4-project-acceptance.json 和 profile4-build-acceptance.json。所选字体及游戏
数据只存在于私有工程/副本，未复制到软件或公共测试中。
