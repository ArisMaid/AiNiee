# 图片处理 v1 实现契约

Codex 负责 SQLite 权威数据、人工确认、构建集成与验收；DeepSeek 仅实现 `ModuleFolders/Service/GameProject/ImageCodec.py`。不得修改其他文件、安装依赖、执行命令或读取游戏素材。可阅读本契约与项目现有代码。不存在的测试由 Codex 独立编写。

## 纯函数接口

仅支持 PNG 与 RPG Maker MV `.rpgmvp`、MZ `.png_`；其他格式明确报错。输入必须 bytes，最多 64 MiB，像素最多 16,000,000，拒绝动画、损坏文件、错误格式，不更改 Pillow 全局限制。统一 ValueError 包含稳定错误码。

- `decode_image(data: bytes, suffix: str, key: str = '') -> tuple[bytes, dict]`：普通 PNG 返回验证后的原始 PNG 字节；加密文件严格验证 16 字节头 `5250474d560000000003010000000000`，移除头并用 32 位十六进制 key 对正文前 16 字节 XOR。验证 PNG；返回信息 `width,height,mode,encrypted`。不记录或打印 key。实际引擎 `rmmz_core.js:450-462` 已核对此算法。
- `encode_image(png: bytes, suffix: str, key: str = '') -> bytes`：先验证 PNG，然后反向封装，普通 PNG 保留 bytes。
- `render_png(base_png: bytes, overlays: list[dict], font_bytes: bytes) -> bytes`：Pillow + fontTools，从确认的干净底图上叠加文字，不自动抹除原图。每项字段 `box: [x,y,w,h]`、`text`、`font_size` 整数 6..256、`color: [r,g,b,a]` 四个整数、`align: left|center|right`。精确校验类型（bool 不作为 int）、框在图内、框之间不重叠、总数不超过 500、文本最多 2000 字；多行；字形缺失或排版溢出立即拒绝，不静默截断或缩字。cmap 指向 .notdef 算缺字。通过每行 textbbox 和总行高检验实际 ink bbox 在框内。输出 RGBA PNG，尺寸不变，框外像素完全不变（包括 alpha），不修改 base。空 overlays 拒绝。font_bytes 最多 32 MiB，只接受有效单个 TrueType/OpenType 字体（TTC 不支持）。
- `ocr_png(png: bytes, executable, tessdata, language: str = 'jpn+eng', timeout: int = 45) -> dict`：本地可选 Tesseract，先验证 PNG。路径绝对化、exe 文件存在，tessdata 目录存在、所选语言 traineddata 存在；语言仅 `[a-z_]+` 用 `+` 连接。timeout 1..120。新进程 argv 数组 shell=False，不网络、不执行游戏、不继承 API key；保留运行所需最小 Windows 系统环境（SystemRoot/WINDIR/TEMP/TMP 与 exe 目录 PATH），cwd=exe.parent。`stdin stdout --tessdata-dir <dir> -l <language> --psm 11 tsv`，图像通过 PNG stdin，避免 Unicode 输入文件名问题。输出上限 8 MiB，错误摘要不含任意环境内容。通过 subprocess.run communicate 有上限输出不能预防进程内存消耗，但返回后拒绝超限；明确此边界即可。透明图只在 OCR 副本合成白底。解析 TSV 标准字段，按 block_num/par_num/line_num 分组，忽略空词和负 confidence，拒绝越界框；每行输出 `box,text,confidence`，不添加 TranslationUnit。返回 `{engine:'tesseract', language, regions:[...]}`。非零退出、超时、无效 TSV 明确报错。

## 集成边界

OCR 候选不会自动转为翻译单元。Codex 的服务会核对源文件 SHA-256、保存私有候选、接收人工修正区域，并在同一个 SQLite 事务中更新图片设置与单元集合。图片单元使用 `adapter_id=image-region`，其文本同样通过 TranslationCommitter。原游戏始终只读，输出沿用同名相对路径与加密扩展。仅在确认了干净底图和排版样式后才允许渲染；渲染候选还需独立确认哈希后进入构建。底图、字体、候选与批准记录均在项目目录，不进入发行包。
