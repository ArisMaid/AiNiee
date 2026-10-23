# 工作区目录与开发环境

AiNiee 目录保留完整 Git 主工程：源码、Resource、Tools、锁文件、文档、合成测试
及 Git 元数据。本地游戏、软件交付、验收现场、下载工具、Python 环境和缓存在
源码目录外分类，避免把私有内容带入源码同步。

```text
RPG一条龙工具/
  AiNiee/                     主源码与核心构建文件
  开发环境/                   Python环境、JavaScript依赖
  外部工具/                   Translator++、OCR工具、RPGMTL、SExtractor
  交付文件/                   最新版运行、最新版封存、验证基线、预发布源码、构建输出
  游戏资料/                   汉化工程、汉化输出、原版压缩包
  验收证据/                   公开摘要、沙盒、原装运行、界面、SDK、字体与图像
  开发记录/                   过程快照、辅助脚本、外部编码记录、运行工作区
  临时缓存/                   Python字节码、浏览器自动化、运行配置、空目录框架
  项目文档/                   目录整理、历史计划、当前状态与移动映射
  待删除/                     用户决定何时手动处置的历史产物
  selenoxia test 0.141/        固定的核心构建输入，保留已有路径
```

原游戏保留固定路径，因为工程元数据中的 source_root 不可变。原游戏目录位于
AiNiee 外，没有为改目录名称修改工程身份。它与“游戏资料/原版压缩包”共同构成
原版输入；不是可随缓存清理的副本。

## 路径约定

`Tools/rpg_paths.json` 只描述外层工作区相对路径。PowerShell 脚本、源码 JS
分析器和打包 spec 读取同一份约定；`RPG_WORKSPACE_ROOT` 可显式指定工作区根。
冻结包优先使用包内 Node/Acorn，不依赖开发目录。可选安装器在便携包中仍使用
包内 `.tools` 和 `work`，源码树中的脚本使用外层中文分类目录。
新克隆或 CI 如仍把 Acorn 安装在源码 `.tools/js`，该既有路径仍可使用。

从 AiNiee 根目录运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/start_rpg_dev.ps1
powershell.exe -NoProfile -ExecutionPolicy Bypass -File Tools/build_rpg.ps1
```

开发入口直接调用外置 `python.exe` 并把字节码缓存放到源码外。迁移后的虚拟环境
不依赖旧 activate/控制台入口；运行模块时使用此 python 的 `-m` 方式。
当前环境由 uv 管理，没有预装 pip；需要安装依赖时可用 uv 的 `--python` 参数明确
指定外置解释器，不以旧 Scripts/pip.exe 入口判断环境是否有效。
其他机器按 requirements-rpg.lock 创建自己的 Python 3.13 环境即可。

JS 依赖的两个锁文件仍属于主工程。首次安装时复制 Tools/package.json 与
Tools/package-lock.json 到“开发环境/JavaScript依赖”，在该目录运行 npm ci；
不要把 node_modules 复制回源码。Node.js 24.16.0 为构建机器单独安装的运行时。

测试仍用 `Tools/test_rpg.ps1` 的新 UUID 保留模式，产物在外层运行工作区；仅按
修改范围运行必要检查。构建输出在“交付文件/构建输出”，构建中间文件在外层
运行工作区，脚本不清理旧目录。

## 工程和证据迁移 SOP

只使用同盘无覆盖移动，不改写历史验收报告中的旧路径。移动清单依次记录源、
目标和文件系统 ID；先按历史归档映射、再按结构重排映射寻找旧文件。
原始报告的 failed/not_run 字段不会因移动改成通过。

当前工程的历史构建输出路径同样不可直接改写。移动工程后通过正常构建生成新
输出及登记，保留重排前 DB 与旧 manifest，并检查单元、接受记录、人工锁、内容
版本及游戏 payload 一致。基准工程和升级种子只移动，保持 DB 字节不变。

沙盒关闭后迁移映射目录，修改新的 WSB 入口；旧来宾结果保持。源码归档只从
已审核 Git commit 生成，不把外层目录整体压缩成软件源码。已封存 ZIP 和校验
文件不覆写，后续源码准备单独记录新的 commit 与 SHA。
