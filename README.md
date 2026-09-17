# STALKER 汉化工具集

潜行者（S.T.A.L.K.E.R.）模组汉化与本地化工具集，面向 SoC / CS / CoP 三部曲及主流模组。
六个图形化工具统一在一个 Hub 中运行：**文件系统、编码转换、文本提取、XML 校对、OGM 视频转换、汉化包生成**。

当前发行版：**1.1.0**（build_58）· 更新内容见 [CHANGELOG.md](CHANGELOG.md)

---

## 功能总览

| 工具 | 说明 |
|---|---|
| 文件系统 | X-Ray DB 六格式解包 / 打包、批量解包、SquashFS 镜像浏览与提取、插件扩展 |
| 编码转换 | 单 / 多字节编码检测、手动指定、统一输出无 BOM UTF-8；支持开始 / 暂停 / 取消 |
| 文本提取 | 从 `scripts/` 或 `gameplay/` 文件夹提取可翻译文本，产出供翻译的 XML |
| XML 校对 | 行数 / ID 统计、ID 文本逐条对比复制，容忍多根 XML、坏实体、编码声明与实际不符 |
| 视频转换 | MP4 / MOV → OGM，按参考 OGM 还原编码与码率参数，兼容 X-Ray 引擎；可中途取消 |
| 汉化包生成 | SoC / ClS / CoP 三版本 gamedata 汉化包；字库按墨迹定标、简繁补字、DDS 图集 |

## 1.1.0 亮点

- **SquashFS 不再依赖外部工具**：大小改由纯 Python 解析镜像元数据（2.3 GB 镜像 99.6 s → 0.01~0.24 s），
  提取改为逐个 `rdsquashfs --cat`（不再把整包 tar 收进内存）；被安全软件拦截的 `sqfs2tar.exe` 已移除。
- **滚动条与布局一族修复**：该出现时真的出现、不该滚时不许滚、一次只有一个滚动条动、
  页内滚动不再带走标签条、面板高度随内容。
- **任务结束后不再停在「加载中…」**；构建器操作栏不再被窗口切掉。
- **视频页缺 ffmpeg 时弹窗处理**：自动安装 / 手动选择 / 稍后，只有点了才联网。
- **字库**：渲染字号按墨迹定标、简体缺字用繁体补、新增「日语字体」识别。

---

## 快速开始

### 方式一：用发行版（推荐给普通用户）

从 [Releases](https://github.com/ALittleHuman/STALKER-Localization-Toolkit/releases) 下载
`release <版本>.7z`，解压后直接运行目录内的

```
STALKER Localization Toolkit 1.1.0.exe
```

发行包是 PyInstaller 单目录版，**自带 Python 运行时、`ffmpeg.exe` / `ffprobe.exe` 与
`deps\squashfs-tools-ng-*`（rdsquashfs 等）**，无需另装任何东西。运行日志与插件目录都在 exe 同目录，
方便排查。

### 方式二：从源码运行

```bat
python stalker_toolkit.py
```

- Windows 10 / 11
- Python **3.12+**（需带 tkinter）。质量闸门固定用 3.12；源码在 3.14 上亦实测可用
- 首次启动若缺 `chardet` / `tkinterdnd2` 会自动安装；汉化包生成首次使用时会自动安装 `Pillow`
- 视频转换需要 `ffmpeg.exe` / `ffprobe.exe`（见下）
- SquashFS 功能需要 `deps\squashfs-tools-ng-1.3.2-mingw64`（仓库已带）

### 视频依赖（ffmpeg 7.x）

```bat
python download_ffmpeg.py
```

程序内的查找顺序只有两处：**exe 同目录** 与 **`user.ltx` 里手动指定的路径**（不再扫 PATH / 常见目录）。
找不到时视频页会弹窗提供三个选择：**自动安装 / 手动选择 / 稍后** —— 只有点「自动安装」才会联网下载。

ffmpeg 固定使用 **7.x**：8.x 的 libtheora 编码器对 STALKER OGM 输出有 bug。

### 构建发行版

```bat
python build_gui.py                    # 图形构建器（与命令行同一套构建逻辑）
python build.py                        # 构建到 builds\build_N
python build.py --version 1.2.0        # 指定基础版本号（写回）
python build.py --prerelease BETA.1    # 附预发布标记（写回；ALPHA / BETA / RC / PRE）
python build.py --prerelease ""        # 清空标记（发正式版时用）
python build.py --out D:\dist          # 构建到指定目录
```

**版本号、标记与两个构建计数的单一事实来源都是 `toolkit_base.py` 里的四行**，由
`toolkit_version.py` 归一化、组合显示串、推导 Windows 四段数字版本并原子写回：

```python
APP_VERSION       = "1.1.0"       # 基础版本
APP_PRERELEASE    = ""            # 预发布标记（"" = 无标记）
BUILD_COUNT       = 58            # 已构建次数（产物目录编号来源）
PRERELEASE_COUNTS = {...}         # 标记序号，键 "<完整版本>|<标记名>" → 已用序号
```

- 后两行由**构建工具**写回（`build.py` 推进、构建 GUI 只读）；历史上分散的计数文件已删除。
- **不给 `--prerelease` 直接构建时，标记序号自动 +1** 并写回（换版本号从 .1 重数、换回用过的标记续上原序号）；
  显式给 `--prerelease` 则原样使用且不动计数。
- 运行时标题、启动日志、产物名读的都是这一份，三者永远一致。
- ★ **跑一次 `run_ci.py` 也会推进构建计数**（构建探针的既有行为）—— 提交代码前用
  `git checkout -- toolkit_base.py` 还原，避免把构建状态混进提交。

**命名规则：外层目录不带版本号，版本号进内侧应用名。**

```
builds\build_58\                                    ← 外层恒为 build_N（编号来自 BUILD_COUNT）
    STALKER Localization Toolkit 1.1.0\             ← 内侧目录 = 应用名 + 完整版本串
        STALKER Localization Toolkit 1.1.0.exe
```

**自行修改的版本不要沿用官方版本号。** 官方版本串标识的是官方发行版；自编译产物请给一个自己的
区分标记（后缀/名号均可），这样不会被误认成官方版。要改的就是 `APP_VERSION` / `APP_PRERELEASE` 两行。

---

## 功能详解

### 文件系统

- X-Ray DB 六格式解包 / 打包：`xdb` / `2947ru` / `2947ww` / `2945` / `2215` / `11xx`；
  分卷（`gamedata.db0` / `db1` …）各自独立，可单独解包。
- **SquashFS（hsqs）**：列目录、取文件大小、提取；大小由纯 Python 读镜像元数据得出
  （lz4 / gzip / xz / zstd），提取走 `rdsquashfs --cat`。
- 拖拽添加、批量解包、勾选集解包、合并树视图（两棵树 + 封包文件列表），树行对齐以勾选框为准。
- NLC Improved 的加密 `sq_base` 需要闭源解密插件（见 [PLUGINS.md](PLUGINS.md)）。

### 编码转换

- 三种模式：检测 / 手动指定 / 自动；统一输出**无 BOM UTF-8**。
- 支持开始 / 暂停 / 取消（三态进度，本页独有），进度栏空闲时整栏收起。

### 文本提取

- 输入框选 **`scripts/` 或 `gameplay/` 文件夹本身**（只认这个名字，不做上下层猜测），
  产物写到 `输出目录/gameplay|scripts`。
- 一次只处理一类（两类都有就分两次跑）。

### XML 校对

- 行数 / ID 统计，ID 文本逐条对比并可直接复制；容忍多根 XML、坏实体、编码声明与实际内容不符。
- 内置两种比较模式，插件可贡献更多模式。

### 视频转换

- MP4 / MOV → OGM；按**参考 OGM** 还原编码与码率参数，输出兼容 X-Ray 引擎。
- ffmpeg 只认 exe 同目录与 `user.ltx` 指定处；缺失时弹窗（自动安装 / 手动选择 / 稍后）。
- 可中途取消；构造期不探测，避免拖慢启动。

### 汉化包生成

- SoC / ClS / CoP 三版本 gamedata 汉化包（**ClS / CoP 尚未充分测试**）。
- 大字号偏移 +5 / +7 / +9；渲染字号按**墨迹**定标放大到贴满格子（格子表 / 行高 / 字宽表不动）。
- 简体缺字形时用**繁体字形**补（OpenCC ST 表派生 2640 条，码位不变）；字体选择器含
  「日语字体」第四态，列表与预览都会标出。
- 产出 DDS 字体图集；画布高度自动覆盖全部行（避免静默丢行）。

---

## 界面行为约定

1.1.0 起，界面遵循几条固定约定（都有测试锁保护）：

- **滚动条智能隐藏**：内容显示得下就不出现；出现时才可以滚，**没有滚动条就不许滚**。
- 同一次滚轮事件**只有一个**滚动条动（隐藏的那个不参与，事件会往外冒泡）。
- **分隔条拖动**：拖动期间只画填色带预览，**松手才重排**。
- **日志栏可完全收起**，改变窗口尺寸不会弹回。
- 页面滚动时**顶部标签条钉住不动**。
- 面板高度随内容，空面板不占位。

---

## 格式支持

| 格式 | 说明 |
|---|---|
| xdb | CS / CoP 通用 XDB |
| 2947ru | SoC 俄版（2947） |
| 2947ww | SoC 国际版（2947） |
| 2945 | Builds 2571–2945 |
| 2215 | Builds 1482–2232 |
| 11xx | Builds 1096–1472 |
| SquashFS (hsqs) | 模组常见的 SquashFS 镜像（lz4 / gzip / xz / zstd） |

---

## 插件系统

启动时扫描 `plugins\` 加载 Python 插件，可扩展：新增 Hub 栏目、任意加密包解密、新封包/解包格式、
新命令与槽位动作、往已有下拉加条目、新建插件下拉、贡献面板，以及为 XML 校对贡献比较模式。

- 插件界面请使用后端无关的控件工厂 **`api.ui`（当前 16 个方法）**：`row / pack / label / button /
  checkbox / entry / text / combo / drop_box / set_text / set_state / alive / text_view /
  ask_yes_no / ask_open_file / ask_save_file` —— 其中 `drop_box`（只读拖入框）与 `set_state`（置灰）
  是 1.1.0 新增，两个后端（Tk / Qt）都真实支持。
- 写法与加载规则详见 [PLUGINS.md](PLUGINS.md)；架构说明见 [ARCHITECTURE.md](ARCHITECTURE.md)。

> **仓库里 `plugins\` 是空的**：闭源解密插件 `nlc_sqfs.py` 不在仓库发布，实验性的
> `engine_utf8_patch.py`（xrEngine UTF-8 补丁，内部测试件）同样不入库。干净克隆下 `plugins\`
> 只有占位文件，相关测试会自动记 SKIP。

---

## 测试与质量闸门

```bat
python run_ci.py               # 完整回归（含 cross_validate；缺外部 converter.exe 则 SKIP）
python run_ci.py --fast        # 快速档：跳过需要外部前提的步骤，并记入「本次未覆盖」
python run_ci.py --release     # 发版档：任何 SKIP 都算不通过
python run_inject_layout_locks.py   # 44 条注入验证（证明锁会红；约 10~15 分钟）
python run_scroll_audit.py     # 真页面滚动条几何审计（六栏目 × 多档窗口尺寸）
python run_ui_smoke.py         # GUI smoke（需桌面会话）
python run_qt_pilot_probe.py   # Qt 试点探针（需 PySide6）
```

- `run_ci.py` 的步骤：compileall → import modules → DB 六格式逐字节往返 → cross_validate（需
  converter.exe）→ `run_ext_probe`（扩展点端到端）→ `run_app_probe`（构造级 + 入口级）→
  `run_scroll_audit`（真页面滚动条几何）→ 静态守卫自测 → 静态守卫扫描 → pyflakes →
  `run_functional_probe`（功能完整性端到端）→ `run_build_probe` → `run_hub_probe` → `run_engine_compat_probe`。
- 作为对照的项目惯例：**每条锁都要先用真实注入证明「会红」，再证明修好后变绿**；
  不许为了让闸门变绿而放松锁。
- 命令行编码：`run_inject_layout_locks.py` 前请设 `PYTHONUTF8=1`（cp936 控制台下中文输出会报错）。

> **分支说明**：最新源码与发行版发布自 `dsh-snapshot-1.1.0-ALPHA.10` 分支；
> `.github/workflows/ci.yml` 目前只在推送到 `main` 与 PR 时触发，因此推送到快照分支不会跑 CI ——
> 提交前请本地跑 `python run_ci.py`。

---

## 目录结构

```
STALKER_Toolkit\
├─ stalker_toolkit.py         主入口（Hub：启动画面 → 日志 → 主题 → 插件 → 六栏目装配）
├─ toolkit.py                 公共库协调层（纯 re-export，保持既有导入兼容）
├─ toolkit_log.py             日志管线（summary / detail 两级，落盘 logs\runtime_*.log）
├─ toolkit_base.py            底层基础（APP_NAME / 版本 / 标记 / 构建计数 / 依赖兜底 / 窗口外壳）
├─ toolkit_theme.py           主题（亮暗色板 + 字体 + apply_theme + Win11 标题栏）
├─ toolkit_widgets.py         通用组件（ScrollPanel / ScrollViewport / AutoScrollbar / CanvasTree /
│                             LogBox / SplitPane / TaskRunner / drop_zone / dir_row / wheel_claim …）
├─ toolkit_plugins.py         插件宿主（PluginManager + Api + 槽位常量表）
├─ toolkit_plugin_ui.py       后端无关控件工厂 api.ui（Tk / Qt 两套实现）
├─ toolkit_textio.py          文本 / 文件 IO（编码探测链 / XML 文本 / 递归收集）
├─ toolkit_platform.py        平台与外部程序（应用配置 / locate_exe / 隐藏窗口运行）
├─ toolkit_paths.py           app_dir（Tk 无关层，Qt 侧可用）
├─ toolkit_constants.py       业务常量表（包扩展名 / 编码候选 / 输出命名模板）
├─ toolkit_version.py         版本号归一化、组合串、四段数字、原子写回、标记序号
├─ toolkit_guard.py           静态守卫（颜色/字体字面量、硬编码槽位；名单从常量表派生）
├─ apps\                      六个 App 的 GUI
│  ├─ fs_app.py / convert_app.py / text_extract_app.py / xml_compare_app.py
│  ├─ video_ogm_app.py / font_pack_app.py
│  ├─ _bootstrap.py           统一 stdlib/tkinter 导入与路径注入
│  └─ xml_modes.py            内置 XML 比较模式声明
├─ file_system\stalker_fs.py  X-Ray DB / SquashFS 引擎（LZHUF / 六格式 / SQFS 直读）
├─ font_pack\font_pack.py     字库渲染（墨迹定标 / 简繁补字 / DDS 图集）+ adv_tables.json
├─ plugins\                   插件目录（仓库内只有 .gitkeep，见上）
├─ deps\                      squashfs-tools-ng-1.3.2-mingw64（rdsquashfs / tar2sqfs / gensquashfs）
├─ qt_pilot*.py + build_qt_pilot.py   Qt6(PySide6) 试点外壳、主题与冻结包构建
├─ build.py / build_gui.py    命令行 / 图形构建器
├─ run_ci.py                  回归总入口；run_*.py 为各专项探针
├─ cross_validate.py          与官方 converter.exe 的 DB 六格式双向交叉校验
├─ download_ffmpeg.py         ffmpeg / ffprobe 检测与下载（被程序内弹窗调用）
├─ ARCHITECTURE.md            架构与设计说明（含每条测试锁的理由）
├─ PLUGINS.md                 插件开发指南
├─ CHANGELOG.md               更新日志
├─ LICENSE                    GPL-3.0
└─ user.ltx                   用户设置（主题 / 手动 ffmpeg 路径；自动生成，不入库）
```

`builds\`、`backup\`、`qt_pilot_dist\`、`qt_pilot_build\`、`plugins\*`、`ffmpeg.exe`、`ffprobe.exe`、
`user.ltx`、`logs\*` 都不入库（见 `.gitignore`）。`builds\` 与 `backup\` 是**有意保留的历史对照物**，
不是待清理垃圾。

---

## 主题与用户设置

Hub 右上角可切换亮 / 暗主题，选择写入 `user.ltx` 并在下次启动保持；Windows 11 标题栏跟随工具色板。

`user.ltx` 是**所有工具共用**的极简 INI：

```ini
[theme]
mode=dark
[ffmpeg]
path=
probe=
```

写入一律「读 → 改一项 → 整体写回」，各段互不影响。新增设置请往这里加段，
**不要**再给单个工具新开 `xxx.cfg.json`。

---

## 已知问题

- **NLC Improved 的引擎侧换行 / 渲染问题（[#1](https://github.com/ALittleHuman/STALKER-Localization-Toolkit/issues/1) /
  [#2](https://github.com/ALittleHuman/STALKER-Localization-Toolkit/issues/2)——已由引擎补丁解决）**：
  根因在引擎 —— 它把 3 字节汉字当作**两个 1 字节字符**来切分，于是有两种表现：个别超长段落显示为
  方块 + 西里尔字母；以及"视觉字宽正常、引擎却认为行宽偏大"导致**换行偏早**。
  用**引擎 UTF-8 补丁**（把 `MultiByteToWideChar(65001, …)` 的 `cbMultiByte` 立即数 `0x02` 改成
  `0x03`）打过之后即正常。工具侧的职责边界已实测排除：字库中所有字符都在 DDS 内、INI 坐标无误。
  ⚠ 该补丁目前是**实验性内部件**，只覆盖 NLC Improved [OBT] 的 `bin_x64\xrEngine.exe` 那一份构建，
  **暂不随发行包发布**。
- **lzo 压缩的 SquashFS 取不到文件大小**：列表可用、大小显示 0 并给出提示（其余压缩算法正常）。
- **文件系统页的合并语义与引擎不一致**：当前同名文件保留**先**加载的那份（first-wins），而 X-Ray
  是「后者为准 + 散装最后覆盖」。属行为变更，尚未修改。
- **缺少「真启动」自动化锁**：现有闸门能在进程内装配并做源码/AST 检查，但抓不到「一启动就崩」这类
  问题（历史上真实发生过）。计划在 2.0.0 补上。

## 版本规划

- **1.1.0**：SquashFS 引擎重写、滚动与布局一族修复、字库定标与简繁补字、任务壳统一（本版）
- **1.1.x**：社区反馈维护
- **2.0.0**：C++ / Qt6 完全重写，提升速度、精度与兼容性（X-Ray 引擎本身是 C++；
  已用 PySide6 试点验证：同为拖动分隔条，Qt 12~15 ms vs Tk 85~118 ms）

## 第三方组件

- 文本提取参考 [wzyddg/stalker_auto-trans-tool_remake](https://github.com/wzyddg/stalker_auto-trans-tool_remake)（作者已在贴吧声明开源）。
- SquashFS 工具链：[squashfs-tools-ng](https://github.com/AgentD/squashfs-tools-ng) 1.3.2（minGW64 构建）。
- `ffmpeg` / `ffprobe` 7.x（发行包内置；缺失时由程序弹窗或 `download_ffmpeg.py` 获取）。
- Python 侧依赖：`tkinterdnd2`（拖拽）、`chardet`（编码统计探测）、`Pillow`（字库渲染）、
  `imageio-ffmpeg`（仅作为自动安装的退路）。
- 简繁补字表由 OpenCC 的 STCharacters 派生（`font_pack\st_fallback.json`）。

## 许可证

**GNU General Public License v3.0**，见 [LICENSE](LICENSE)。
NLC 解密插件（`nlc_sqfs.py`）为闭源组件，不在本仓库发布。
