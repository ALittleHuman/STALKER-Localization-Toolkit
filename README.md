# STALKER 工具集

潜行者（S.T.A.L.K.E.R.）模组汉化与本地化工具集。全英文目录布局，兼容性优先。

## 目录结构

```
stalker_toolkit.py        主入口（单文件整合版 GUI）
toolkit.py                公共 GUI 组件库（主题 / 日志 / 文件树）
file_system\              X-Ray DB / SquashFS 引擎与独立文件系统 GUI
font_pack\                汉化包生成（字库渲染 / gamedata 组装）
xml_compare\              XML 校对工具
convert\                  编码转换工具
video_ogm\                OGM 视频工具（MP4/MOV → OGM，参数匹配参考 OGM）
text_extract\             零散文本提取
plugins\                  Python 插件（nlc_sqfs 等）
deps\                     squashfs-tools-ng 等第三方依赖
logs\                     日志输出目录
ffmpeg.exe / ffprobe.exe  视频工具二进制
app_icon.ico              工具集图标
```

## 运行

```bat
python stalker_toolkit.py
```

## 说明

- 文件系统工具支持 xdb / 11xx / 2215 / 2945 / 2947ru / 2947ww / SquashFS。
- NLC Improved 加密 sq_base 通过 `plugins\nlc_sqfs.py` 动态加载。
- 视频转换以参考 OGM 的参数为准，输出 X-Ray 兼容的 OGM。
- 日志默认写入 `logs\` 目录。


