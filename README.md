# STALKER 汉化工具集

潜行者（S.T.A.L.K.E.R.）模组汉化与本地化工具集，面向 SoC / CS / CoP 三部曲及主流模组。六个图形化工具统一在一个 Hub 中运行：文件系统、编码转换、文本提取、XML 校对、OGM 视频转换、汉化包生成。

## 功能总览

| 工具 | 说明 |
|---|---|
| 文件系统 | X-Ray DB 解包 / 打包、批量解包、SquashFS 支持、插件扩展 |
| 编码转换 | 单/多字节编码检测、手动指定编码、统一输出无 BOM UTF-8 |
| 文本提取 | 从零散文件（XML 等）中提取可翻译文本 |
| XML 校对 | 行数 / ID 统计、ID 文本对比，支持多根 XML、坏实体、编码声明与实际不符 |
| 视频转换 | MP4 / MOV → OGM，按参考 OGM 还原编码与码率参数，兼容 X-Ray 引擎 |
| 汉化包生成 | SoC / ClS / CoP 三版本 gamedata 汉化包生成（ClS和CoP尚未测试） |

## 目录结构

```
STALKER_Toolkit\
├─ stalker_toolkit.py         主入口（Hub：日志 → 主题 → 插件 → 六栏目装配）
├─ toolkit.py                 公共库协调层（纯 re-export，保持既有导入兼容）
├─ toolkit_log.py             日志管线（最先加载；summary / detail 两级）
├─ toolkit_base.py            底层基础（APP_NAME / 版本 / 标记 / 构建计数 / app_dir / 依赖兜底 / 窗口外壳）
├─ toolkit_theme.py           主题（单文件：亮暗色板 + 字体 + apply_theme + 标题栏）
├─ toolkit_widgets.py         通用组件（LogBox / CanvasTree / SplitPane / 插件槽位 ...）
├─ toolkit_plugins.py         插件宿主（PluginManager + 槽位常量表）
├─ toolkit_textio.py          文本 / 文件 IO 工具（编码探测 / XML 文本 / 文件递归）
├─ toolkit_platform.py        平台与外部程序（应用配置 / locate_exe / 隐藏窗口运行）
├─ toolkit_constants.py       业务常量表（包扩展名 / 编码候选 / 输出命名模板）
├─ toolkit_version.py         版本号归一化、组合显示串、四段数字、写回、标记序号计数
├─ toolkit_guard.py           CI 静态守卫（颜色/字体字面量、硬编码槽位）
├─ apps\                      六个 App 的 GUI + 内置比较模式声明
│  ├─ _bootstrap.py           统一 stdlib/tkinter 导入 + 子目录路径注入（`__all__` 声明转发清单）
│  ├─ xml_modes.py            内置两种 XML 比较模式的声明式注册
│  ├─ fs_app.py               文件系统
│  ├─ convert_app.py          编码转换
│  ├─ text_extract_app.py     文本提取
│  ├─ xml_compare_app.py      XML 校对
│  ├─ video_ogm_app.py        视频转换
│  └─ font_pack_app.py        汉化包生成
├─ file_system\               X-Ray DB / SquashFS 引擎（stalker_fs.py + lzhuf_dll.dll）
├─ font_pack\                 汉化包生成库（font_pack.py + adv_tables.json 字宽表）
├─ plugins\                   插件目录（详见 PLUGINS.md）
├─ deps\                      squashfs-tools-ng-1.3.2-mingw64
├─ builds\                    历史 PyInstaller 产物（build_N\，版本号在内侧应用名上）；构建失败的现场归档在 FAIL\ 下
├─ backup\                    只留 pre_version_change\（版本写回机制的一次性备份；重构前的源码副本已清除）
├─ logs\                      运行日志（每次启动一个 runtime_<时刻>.log）
├─ build.py / build_gui.py    命令行 / 图形构建器（同一构建函数；构建失败会自动回退版本号并把现场归档到 builds\FAIL\）
├─ run_gui_text_audit.py      界面文案 / 标点审查（只读：扫 messagebox / tool_text / text= 里的长串）
├─ download_ffmpeg.py         ffmpeg / ffprobe 检测与自动下载
├─ run_ci.py                  本地回归测试总入口
├─ run_*.py                   各专项探针（构造级 / 扩展点 / Hub 级 / 功能 / 构建器 / 引擎兼容 / UI smoke）
├─ cross_validate.py          与外部 converter.exe 的 DB 六格式双向交叉校验（含目录条目）
├─ app_icon.ico               图标
├─ .editorconfig / .gitattributes  行尾声明（5 个历史 CRLF；其余 LF）
└─ user.ltx                   用户设置（主题 / 手动指定的 ffmpeg 路径；自动生成，不入库）
```

`builds\` 与 `backup\` 是**有意保留的历史对照物**（前者是历史产物，后者是重构前快照，
便于比对"哪些修复还没做"）。CI 与构建都显式排除它们——**不要把它们当成待清理的垃圾**。

## 快速开始

### 环境要求

- Windows 10 / 11
- Python 3.12+（需带 tkinter）。CI 固定用 3.12；源码运行在 3.14 上亦实测可用（本地
  `__pycache__` 为 `cpython-314`）
- 视频转换需要 `ffmpeg.exe` / `ffprobe.exe`（固定 7.x，见下）
- 文件系统 SquashFS 功能需要 `deps\squashfs-tools-ng-1.3.2-mingw64`

### 运行

```bat
python stalker_toolkit.py
```

首次启动如果缺少 `chardet` / `tkinterdnd2` 会自动安装；汉化包生成首次使用时会自动安装
`Pillow`。

### 获取视频依赖

```bat
python download_ffmpeg.py
```

脚本会检查根目录下的 `ffmpeg.exe` / `ffprobe.exe`，缺失时自动下载。其中 ffmpeg 固定使用 7.x 版本：ffmpeg 8.x 的 libtheora 编码器对 STALKER OGM 输出有 bug。

### 构建发行版

```bat
python build_gui.py                    # 图形构建器（构建逻辑与 build.py 完全一致）
python build.py                        # 构建到 builds\build_N
python build.py --version 1.2.0        # 指定基础版本号（写回）
python build.py --prerelease BETA.1    # 附预发布标记（写回；ALPHA / BETA / RC / PRE）
python build.py --prerelease ""        # 清空标记
python build.py --out D:\dist          # 构建到指定目录
```

**版本号、标记与两个构建计数的单一事实来源都是 `toolkit_base.py` 里的四行**，由
`toolkit_version.py` 归一化、组合显示串、推导 Windows 四段数字版本并原子写回：

```python
APP_VERSION       = "1.0.1"       # 基础版本
APP_PRERELEASE    = "ALPHA.2"     # 预发布标记（"" = 无标记）
BUILD_COUNT       = 5             # 已构建次数（产物目录编号来源）
PRERELEASE_COUNTS = {}            # 标记序号，键 "<完整版本>|<标记名>" → 已用序号
```

后两行由**构建工具**写回（`build.py` 推进、构建 GUI 只读），不再有独立的计数文件
（历史上的 `build_count.txt` / `prerelease_count.json` 已删除 —— 三四个文件存同一份
"构建状态"迟早对不上）。

`--version` / `--prerelease` 都会**写回前两行**（构建 GUI 的「保存版本号与标记」是同一实现）；
**不给 `--prerelease` 直接构建时，标记的序号自动 +1** 并写回第三/四行（按 (完整版本, 标记名)
各自计数：换版本号从 .1 重数、换回用过的标记则续上原序号；即使把 `PRERELEASE_COUNTS` 清空，
也会以 `APP_PRERELEASE` 里已写的序号为下限继续，不会倒退）。显式给 `--prerelease` 则
**原样使用且不动计数** —— 手工输入优先，与构建次数同规矩。
运行时标题、启动日志、产物名读的都是这一份，所以三者永远一致：

```
窗口标题 / 启动日志:  STALKER Localization Toolkit 1.0.1 ALPHA.1
```

**自行修改的版本不要沿用官方版本号。** 这里的版本号标识的是**官方发行版**；你若自己改了源码
（包括本地重新构建），请**不要**用与官方版相同的版本串对外发布 —— 给它一个你自己的区分标记
（自定的后缀 / 名号都行），这样自编译产物永远不会被误认成官方版。要改的就是
`toolkit_base.py` 里的 `APP_VERSION` / `APP_PRERELEASE` 两行。

**命名规则：外层目录不带版本号，版本号进内侧的应用名。**

```
builds\build_2\                                       ← 外层恒为 build_N（编号来自 toolkit_base.BUILD_COUNT）
    STALKER Localization Toolkit 1.0.1 BETA.1\        ← 内侧目录 = 应用名 + 完整版本串
        STALKER Localization Toolkit 1.0.1 BETA.1.exe
```

外层不带版本号，翻 `builds\` 时按编号排序不会被版本串打断；版本号跟着产物走，
用户解压/移动后仍能一眼看出是哪个版本，多个版本也能并排共存。
编号绝不覆盖既有目录（撞上就往后找第一个空号）。
闭源插件 `plugins\nlc_sqfs.py` 在构建期间会被临时移出打包范围。

## 格式支持

| 格式 | 说明 |
|---|---|
| xdb | CS / CoP 通用 XDB |
| 2947ru | SoC 俄版（2947） |
| 2947ww | SoC 国际版（2947） |
| 2945 | Builds 2571–2945 |
| 2215 | Builds 1482–2232 |
| 11xx | Builds 1096–1472 |
| SquashFS (hsqs) | 模组常见的 SquashFS 镜像 |

- DB 分卷（`gamedata.db0` / `db1` / ...）各自独立，均可单独解包。
- NLC Improved 的加密 `sq_base` 需要闭源解密插件，见 [PLUGINS.md](PLUGINS.md)。

## 插件系统

工具集启动时会扫描 `plugins\` 目录加载 Python 插件，可扩展：新增 Hub 栏目（工具 Tab）、任意加密包解密、新封包/解包格式、新命令与槽位动作、往已有下拉加条目、新建插件下拉、贡献面板，以及为 XML 校对贡献比较模式。插件写法与加载规则详见 [PLUGINS.md](PLUGINS.md)。

## 测试

```bat
python run_ci.py            # 完整回归（含 cross_validate；需要外部 converter.exe，缺失则 SKIP）
python run_ci.py --fast     # 快速回归（跳过 cross_validate；CI 跑的就是这一档）
python run_ui_smoke.py      # GUI 构建 + 编码/XML/文本提取/视频发现 smoke 测试（需桌面，单独跑）
python run_deadcode_audit.py  # 死代码审计（只读，退出码恒为 0）
```

`run_ci.py` 的实际步骤（顺序）：compileall → import modules → **DB 六格式逐一 pack/unpack/extract
逐字节往返** → cross_validate（需 converter.exe）→ run_ext_probe（扩展点端到端）→ run_app_probe
（构造级 + 入口级）→ 静态守卫自测 → 静态守卫扫描 apps/ → pyflakes（未定义名 / 未用导入）→
run_functional_probe（8 组功能完整性端到端，含任务壳失败路径与真实 ffmpeg 视频转换）→
run_build_probe（构建器与版本号）→ run_hub_probe（Hub 级框架集成）→
run_engine_compat_probe（旧调用形状兼容）。

注意覆盖边界：`run_ui_smoke.py` 与 `run_deadcode_audit.py` **不在** `run_ci.py` 里，需要单独跑；
CI 用的是 `--fast`，因此 **cross_validate 在 CI 上被跳过**。`run_ci.py` 自带控制台编码兜底
（内部对 stdout/stderr 做 UTF-8 `reconfigure`），**不需要**预先设 `PYTHONIOENCODING`；所有测试
产物都写在自己的临时目录或 `temp\` 下，交叉校验与各探针都不会往仓库里落文件。

GitHub Actions 会在 push 到 `main` 与所有 PR 时自动运行核心测试（`windows-latest` + Python 3.12，
工作流 `.github/workflows/ci.yml` 唯一的命令是 `python run_ci.py --fast`）。

## 主题

Hub 右上角可切换亮 / 暗主题，选择会写入 `user.ltx`，下次启动保持。Windows 11 标题栏会跟随主题使用工具色板中的纯色。

`user.ltx` 是**所有工具共用的**用户设置文件（极简 INI，按 `[段]` 分节），目前放了 `[theme] mode` 和视频工具手动指定的 `[ffmpeg] path/probe`。写入一律"读 → 改一项 → 整体写回"，所以各段互不影响。新增设置请往这里加段，**不要**再给单个工具新开 `xxx.cfg.json`。

## 已知问题

- **NLC Improved（魔改新版 OGSR）上，部分超长文本字段渲染异常**：个别字段（例如 esc_attention 中的超长段落）在游戏内会显示为方块和西里尔字母，疑似引擎局部按 windows-1251 处理所致，具体机制未知。字库生成侧已验证无缺字、坐标无误。Golden Sphere OGSR（旧版OGSR）未复现。相关讨论见 [#1](https://github.com/ALittleHuman/STALKER-Localization-Toolkit/issues/1)。
- **NLC Improved 上换行时机偏早**：引擎按 INI 字符宽度排版，而当前 INI 宽度参考 CN_Pack_Generator 的 GDI advance，视觉上字宽正常但引擎认为的行宽偏大，导致自动换行偏早。该问题为 NLC 独有。相关讨论见 [#2](https://github.com/ALittleHuman/STALKER-Localization-Toolkit/issues/2)。
- 以上问题均基于目前的测试。具体是否为所有新版OGSR均会复现的Bug尚不可知。

## 版本规划

- 1.0.x：社区反馈维护，分隔条手感优化
- 2.0.0：C++ 重写，提升速度、精度和兼容性

## 第三方组件

- 文本提取功能参考 [wzyddg/stalker_auto-trans-tool_remake](https://github.com/wzyddg/stalker_auto-trans-tool_remake)，作者已在贴吧（https://tieba.baidu.com/p/7900909352）声明开源。

## 许可证

见仓库 LICENSE 文件。NLC 解密插件为闭源组件，不在本仓库发布。
