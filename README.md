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
| 汉化包生成 | SoC / CS / CoP 三版本 gamedata 汉化包生成 |

## 目录结构

```
STALKER_Toolkit\
├─ stalker_toolkit.py         主入口（Hub）
├─ toolkit.py                 公共 GUI 组件库（主题 / 日志 / 文件树 / 插件宿主）
├─ apps\                      六个 App 的 GUI
│  ├─ fs_app.py               文件系统
│  ├─ convert_app.py          编码转换
│  ├─ text_extract_app.py     文本提取
│  ├─ xml_compare_app.py      XML 校对
│  ├─ video_ogm_app.py        视频转换
│  └─ font_pack_app.py        汉化包生成
├─ file_system\               X-Ray DB / SquashFS 引擎（stalker_fs.py + lzhuf_dll.dll）
├─ font_pack\                 汉化包生成库
├─ plugins\                   插件目录（详见 PLUGINS.md）
├─ deps\                      squashfs-tools-ng 等第三方依赖（发布包附带，仓库不含）
├─ logs\                      运行日志输出
├─ download_ffmpeg.py         ffmpeg / ffprobe 检测与自动下载
├─ run_ci.py                  本地回归测试入口
├─ cross_validate.py          压缩 / 解压一致性校验
├─ app_icon.ico               图标
└─ user.ltx                   用户主题配置（自动生成，不入库）
```

## 快速开始

### 环境要求

- Windows 10 / 11
- Python 3.10+（需带 tkinter）
- 视频转换需要 `ffmpeg.exe` / `ffprobe.exe`
- 文件系统 SquashFS 功能需要 `deps\squashfs-tools-ng-1.3.2-mingw64`

### 运行

```bat
python stalker_toolkit.py
```

首次启动如果缺少 `chardet` / `tkinterdnd2` 会自动安装。

### 获取视频依赖

```bat
python download_ffmpeg.py
```

脚本会检查根目录下的 `ffmpeg.exe` / `ffprobe.exe`，缺失时自动下载。其中 ffmpeg 固定使用 7.x 版本：ffmpeg 8.x 的 libtheora 编码器对 STALKER OGM 输出有 bug。

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

工具集启动时会扫描 `plugins\` 目录加载 Python 插件，可扩展：新增 Hub 栏目（工具 Tab）、任意加密包解密、新封包/解包格式、文件系统工具右键菜单项与下拉选项。插件写法与加载规则详见 [PLUGINS.md](PLUGINS.md)。

## 测试

```bat
python run_ci.py            # 完整回归（含 cross_validate，需要 converter.exe）
python run_ci.py --fast     # 快速回归（编译 / 导入 / DB 往返）
python run_ui_smoke.py      # GUI 构建 + 编码/XML/文本提取/视频发现 smoke 测试
```

GitHub Actions 会在 push / PR 时自动运行核心测试。

## 主题

Hub 右上角可切换亮 / 暗主题，选择会写入 `user.ltx`，下次启动保持。Windows 11 标题栏会跟随主题使用工具色板中的纯色。

## 已知问题

- **NLC Improved（魔改新版 OGSR）上，部分超长文本字段渲染异常**：个别字段（例如 esc_attention 中的超长段落）在游戏内会显示为方块和西里尔字母，疑似引擎局部按 windows-1251 处理所致，具体机制未知。字库生成侧已验证无缺字、坐标无误。Golden Sphere OGSR（旧版OGSR）未复现。
- **NLC Improved 上换行时机偏早**：引擎按 INI 字符宽度排版，而当前 INI 宽度参考 CN_Pack_Generator 的 GDI advance，视觉上字宽正常但引擎认为的行宽偏大，导致自动换行偏早。该问题为 NLC 独有。
- 以上问题均基于目前的测试。具体是否为所有新版OGSR均会复现的Bug尚不可知。

## 版本规划

- 1.0.x：社区反馈维护，分隔条手感优化
- 1.1.0：OGSR 中文无法换行补丁
- 2.0.0：C++ 重写，提升速度、精度和兼容性

## 许可证

见仓库 LICENSE 文件。NLC 解密插件为闭源组件，不在本仓库发布。
