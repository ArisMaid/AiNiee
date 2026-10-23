# 当前游戏 profile 增量5：两个插件显示字段

2026-10-18。仅当前 MZ 1.7.0 / game_id 33872391 / 0.141 文件集合。
profile schema 保持3，工程物理格式保持2，没有新增脚本文字编解码器或写入计划语义。

## 消费者与排除依据

只读盘点当前178个 JSON：174个登记插件、168个启用，事件内4681次 code357，
126种 plugin/command。355/655/356 分别为1739/2206/12条，仍按未审查脚本处理。
日文字符只用于排查优先级，不作为显示字段或开放回写的证据。

新增两条白名单：

| 插件命令 / 字段 | 消费者链 | 保持不变的反例 |
|---|---|---|
| SH_BenriCommands2.AddEstrus / text | JS337-347：读取 args.text，在有值时交给 $TM.show；Ticker331-336分派，587绘制 | num 保持数值逻辑，不随文字翻译 |
| Gaya.show / text | JS102-113 → GayaContainer.showText → Window_Hidden.makeBitmap，220-224调用 drawTextEx | fontSize、duration、位置与随机参数不开放 |

profile 新增 SH_BenriCommands2.js、Gaya.js、Ticker.js 的完整 SHA-256 指纹；源文件
改变则拒绝提取。哈希写在 profile 中，不把同名插件或其他版本视为已验证。

其余八类含日文的未批准参数保持排除：EventReSpawn.MAKE.id 根据事件 name 查找对象；
FilterControllerMZ 的 create/set/erase filterId 是滤镜标识；AnimationByPoint.label
用于匹配并结束动画；Keke 的 layer/insert/form 是图层、插入位置和几何形状选择枚举。
其中 EventReSpawn363-384、FilterControllerMZ716-721/775-777、AnimationByPoint196-203、
Keke1910/1951-1955/2182-2217 给出直接消费者。不能因为它们含日文而翻译。

## 验证

- 合成回写只改变两个 text，保留数字、资源/事件/滤镜 ID、标签及图形枚举，控制符保持。
  消费者指纹错误拒绝提取，原有数据不替换。专项2项通过。
- 当前游戏新建独立工程：17716单元/18264位置，新增10单元（AddEstrus9、Gaya1）。
  原有27条接受示例译文和已审核图片原样复制；新增2条明确的中文显示测试，合计29条，
  未译17687。没有调用翻译模型，中文测试文本不代表真实翻译质量。
- 9570项新副本构建/清单核验通过。原 profile4 工程 DB SHA 前后均为
  3f39869473a66c059cc66db069337376f858d332c255b0ce8dd3e8649304d935。
- 新副本原装 Game.exe，读取此前验收的 UI 存档，以构建后命令参数调用实际插件消费者。
  Ticker Bitmap1016×31、Gaya Bitmap108×18，中文位图与完整画面均已目视检查。
  Gaya固定随机输入0.5，记录位置(1071,341)、opacity255；两次都在 Scene_Map，无错误。
  使用隐藏窗口、固定tick/focus和受控入口，不能替代自然触发或所有随机位置/长译文布局。
  引擎进程正常退出0，owned树清理完成。当前已接受文本的所选字体检查通过。

首轮验证钩子早于异步引擎初始化，改为入口调用时安装。第二轮断言遗漏 Ticker 的
自动图标前缀，修正后位图通过；随后增加0.8秒呈现等待，避免抓到上一帧。失败驱动和
位图检查记录都保留，未据此修改游戏插件或放宽提取规则。

私有证据：`work/plugin-field-inventory/298854ac4eb8419f8d6911a1010f3ab0/`、
`work/profile5-build-acceptance.json`、
`work/profile5-runtime/bccb50cde6aa4fe1bbd7d334d8866602/result.json`。
游戏素材、存档、截图和完整脚本文本不进入软件或源码归档。
