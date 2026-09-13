# STALKER Toolkit 架构说明

> 事实快照：2026-09-11。本文**不固化文件行数**（代码仍在迭代，写死会立刻过时）；
> 需要行数时按附录 A 的命令现场复核。目录清单、契约、扩展点等结构性事实为代码实测所得。
> 本文只描述**当前实际结构**。方案 A 的分层拆分**已经完成**，不再有"进行中"的章节。

---

## 一、目录结构（当前实际）

### 1.1 根目录 `.py` 清单（实测）

| 类别 | 文件 |
|---|---|
| Hub 入口 | `stalker_toolkit.py` |
| 公共库协调层 | `toolkit.py`（纯 re-export，不含实现） |
| 库层（各自独立成文件） | `toolkit_log.py` `toolkit_paths.py` `toolkit_base.py` `toolkit_theme.py` `toolkit_widgets.py` `toolkit_plugins.py` `toolkit_textio.py` `toolkit_platform.py` `toolkit_constants.py` `toolkit_version.py` `toolkit_guard.py` |
| 构建 | `build.py` `build_gui.py` `download_ffmpeg.py` |
| 探针 / 审计 | `run_ci.py` `run_functional_probe.py` `run_ext_probe.py` `run_app_probe.py` `run_hub_probe.py` `run_engine_compat_probe.py` `run_build_probe.py` `run_ui_smoke.py` `run_guard_selftest.py` `cross_validate.py` `run_deadcode_audit.py` |

`toolkit_guard.py` 既是库层模块，也是 CI 里的一个**扫描步骤**（见第七节）。

### 1.2 目录树

```
STALKER_Toolkit\
├─ stalker_toolkit.py          Hub 主入口：日志 → DPI → 窗口 → 主题 → 插件 → 六栏目装配
├─ toolkit.py                  公共库协调层：只 re-export，不含实现
├─ toolkit_log.py              日志管线（最先加载，纯 stdlib）
├─ toolkit_base.py             底层基础（APP_NAME / APP_VERSION / app_dir / 依赖兜底 / 窗口外壳）
├─ toolkit_theme.py            主题（单文件：亮暗色板 + 字体 + apply_theme + 标题栏）
├─ toolkit_widgets.py          通用组件（LogBox / CanvasTree / SplitPane / PluginSlot ...）
├─ toolkit_plugins.py          插件宿主（PluginManager + Api + 槽位常量表）
├─ toolkit_textio.py           文本 / 文件 IO 纯函数（编码探测 / XML 文本 / 文件递归）
├─ toolkit_platform.py         平台与外部程序（app 配置 / locate_exe / run_hidden / 字体目录）
├─ toolkit_constants.py        业务常量表（包扩展名 / 编码候选 / 输出命名模板）
├─ toolkit_version.py          版本号归一化、组合显示串、四段数字、写回
├─ toolkit_guard.py            CI 静态守卫（颜色/字体字面量、硬编码槽位、手写窗口标志）
├─ apps\                       六个 App + 引导 + 内置比较模式声明
│  ├─ _bootstrap.py            统一 stdlib/tkinter 导入 + 子目录路径注入 + `__all__` 转发清单
│  ├─ xml_modes.py             内置两种 XML 比较模式的声明式注册（列/筛选/算法/详情）
│  ├─ fs_app.py                文件系统（DB 六格式 + SquashFS）
│  ├─ convert_app.py           编码转换
│  ├─ text_extract_app.py      文本提取
│  ├─ xml_compare_app.py       XML 校对
│  ├─ video_ogm_app.py         视频转换（MP4/MOV → OGM）
│  └─ font_pack_app.py         汉化包生成
├─ file_system\                stalker_fs.py（DB 引擎 + SquashFS 调用）+ lzhuf_dll.dll / lzhuf_dll.b64
├─ font_pack\                  font_pack.py + adv_tables.json（字宽表）
├─ plugins\                    Python 插件目录（nlc_sqfs.py 为闭源组件，不入库）
├─ deps\                       squashfs-tools-ng-1.3.2-mingw64
├─ builds\                     历史 PyInstaller 产物（build_N\，版本号在内侧应用名上）
├─ builds\FAIL\                构建失败现场归档（build_<编号>_<年月日时分秒>\ + 同名 .log）
├─ backup\                     重构前快照与一次性改动备份（含 pre_* 目录、stalker_toolkit_*.py）
├─ logs\                       runtime_<启动时刻>.log 与导出的 log_*.txt
├─ temp\                       构建与测试的临时目录
├─ .editorconfig / .gitattributes  行尾声明（5 个历史 CRLF 文件 + 其余 LF；见下）
└─ ARCHITECTURE.md / PLUGINS.md / README.md
```

**行尾约定**（2026-09-12 由外部审计指出"混用且无声明"后补齐）：41 个 `.py` 中`stalker_toolkit.py` / `toolkit_plugins.py` / `toolkit_textio.py` / `toolkit_widgets.py` /
`font_pack/font_pack.py` 是**历史 CRLF**，其余一律 LF，**无一处混合**。
声明放在 `.editorconfig`（仓库当前没有 `.git`，编辑器只认它）与 `.gitattributes`
（将来入库时生效）两份里，内容必须一致 —— `run_app_probe` 有一条锁按"声明 vs 实际"逐文件核对，
并且会核对两份声明不漂移（任一文件被顺手改成另一种行尾、或新文件没进声明，都会红）。
编辑时**逐文件保持原约定**：把 CRLF 文件整体改成 LF 会产生整文件假 diff。

**输入框的焦点 / 选中收敛**（用户口径 2026-09-12）：路径输入框要支持键盘输入，
点进去后光标常闪是**正常**的；但要求两件事 ——① **点空白处能取消**（焦点离开 **且**
选中高亮消失），② **打开任意组件后不停留在"某个输入框被选中"的状态**。
实现放在 `toolkit_widgets.py`：三个输入框工厂（`path_row` / `dir_row` / `themed_entry`）
各自 `install_blank_click_unfocus()`（挂在该 toplevel 上、幂等），Hub 侧
`install_tab_focus_reset(nb, root)` 在切页时收敛一次；核心是 `neutralize_input_focus(root)`。
两个 Tk 默认行为是这条需求的成因，改代码时别踩回去：
点 Label / Frame 这类**不可聚焦**控件**不会**改变焦点；而 `focus_set()` 只把焦点拿走、
**选中高亮仍残留**（实测 `selection_present()` 依旧 True），必须显式 `selection_clear()`。
`run_app_probe` 第 [12] 段有 9 条锁（含"点另一个输入框焦点要正常转移""焦点在列表上时
点空白不抢焦点""切页清掉上一个组件的选中态"以及 Hub 接线的源码漂移锁）。


**仓库里不再有交叉校验的落盘目录**：`cross_validate.py` 的样例与输出现在都写在
`tempfile.mkdtemp(prefix="toolkit_xval_")` 下，跑完自清，**不在仓库里落任何文件**。
（历史上的 `cross_validate_out\` 与 `cross_validate_samples\` 已删除；`run_ci.cleanup()`
仍会顺手清这两个名字，只为清掉别人的历史残留。同理，各探针的插件也写进自己的临时目录。）

**`builds\` 是有意保留的历史产物、`backup\` 现在只剩机制在用的那一份**：`builds\build_N` 是历史
产物（可拿旧版本比对"哪些修复还没做"）；`backup\pre_version_change\toolkit_base.py` 是版本写回
机制的一次性备份。**重构前的源码副本已按用户要求清除**（2026-09-12：`pre_widgets_split/` /
`pre_deadcode_cleanup/` / `pre_imports_cleanup/` / 单文件巨石 `stalker_toolkit_2026*.py` 等共 24 个
文件 —— 它们与当前代码同名同源、全局搜索会命中，属于"模块化残留"；其中一份 919 行的旧 `fs_app`
还曾藏在 `temp\`（CI 与审计的双盲区）里）。构建与 CI 都**显式排除**这些目录——`run_ci.py` 的
`_SKIP_PARTS` 是 `("__pycache__", "builds", "backup", "temp", ".git", "cross_validate_out", "deps")`，
`build.py` 清缓存时的 `os.walk` 过滤同样是 `("builds", "backup", "deps", ".git")`。

运行：`python stalker_toolkit.py`。构建：`python build_gui.py`（推荐）或 `python build.py`。

---

## 二、分层与依赖方向

```
                    stalker_toolkit.py (Hub, 入口)
                             │
                             │ 只 import，不改方向
                             ▼
              apps/*.py  ──►  toolkit.py（协调层，纯 re-export）
                             │
        ┌────────────┬───────┼────────┬─────────────┬──────────────┐
        ▼            ▼       ▼        ▼             ▼              ▼
 toolkit_widgets toolkit_plugins toolkit_textio toolkit_theme toolkit_platform
        │            │                          │              │
        └────────────┴──────────► toolkit_base ◄┴──────────────┘
                                       │
                                       ▼
                                  toolkit_log（最先加载，纯 stdlib）

 file_system/stalker_fs.py   纯 stdlib 叶子，不反向依赖任何上层
 font_pack/font_pack.py      stdlib + Pillow；唯一反向边是惰性引用 toolkit 的 XML 解析
```

单向依赖，无环：`widgets → theme → base → log`，`constants` 与 `paths` 属旁路（`constants`
零依赖纯数据；`paths` 零依赖，且 **`platform` / `theme` 只依赖 `paths.app_dir` 而**不**经 `base`**
—— 这条"旁路"就是 Qt 侧能读写 `user.ltx` 又不把 Tk 拉进进程的原因，见 §11.3）。

**Import 兼容约束（拆分后必须继续守住）**
各 App 使用形如 `from toolkit import T, color, apply_theme, ...` 的批量导入。`T` 是模块级
字典，`apply_theme()` 以 `T.clear(); T.update(P)` **原地修改**。因此 `toolkit.py` 必须
re-export **同一个字典对象**；任何 `T = ...` 形式的重新绑定都会让 App 里已绑定的 `T`
变成旧字典，导致切主题静默失效。`CURRENT_MODE` 同理只能单点持有。

---

## 三、Hub 主干流程

`stalker_toolkit.py` 的 `__main__`（实测顺序）：

| 步骤 | 位置 | 职责 |
|---|---|---|
| 1 | `log_summary("=== ... 启动 ===")` + `log_detail(...)` | **日志最先**：此后每一步都可被记录 |
| 2 | `SetProcessDpiAwareness(2)` | DPI 感知（失败只记 detail，不阻断） |
| 3 | `root = _BaseTk()` | 根窗口（tkinterdnd2 可用时带拖拽） |
| 4 | `start_mode = load_user_theme()` | 只读一次；启动帧就按**用户上次选的主题**画（旧写法先按默认暗色画、再由 `build_hub` 切一次，选了亮色的用户启动会闪一下暗色） |
| 5 | `set_app_icon` / `geometry("1280x860")` / `minsize(1024, 700)` | 图标与窗口尺寸 |
| 6 | `apply_theme(start_mode)` + `apply_tk_defaults(root, start_mode)` | 应用启动主题 |
| 7 | **`paint_startup(root)`** | **启动白屏修复**：装任何组件之前先画一帧（见 §3.3） |
| 8 | `PluginManager.shared(app_dir()/plugins, log=…, summary=…)` | **插件扫描一次**，进程级共享实例 |
| 9 | `TOOLS = list(BUILTIN_TOOLS)` + 插件栏目按 `order` 稳定插入 | 汇总栏目（内置六个固定在前） |
| 10 | `build_hub(start_mode)` | header / 主题下拉 / `SplitPane(Notebook + 日志区)` / `rebuild()`（**分帧装配**，见 §3.3） |
| 11 | `root.mainloop()` | 事件循环 |

两处设计意图值得记住：

* **`BUILTIN_TOOLS` 是模块级常量**（不是 `main()` 里的局部量），这样 `run_hub_probe.py`
  能核对**真实的**内置清单。此前探针自己手抄一份同名列表，Hub 少一个工具它照样通过。
* **插件扫描先于子工具**：文件系统工具需要同一份 `PluginManager`，见第五节的"共享实例"。

**Hub 日志区（唯一日志面板）**：工具内不再各自建日志面板，界面上只有这一个，右侧两个按钮：

| 按钮 | 行为 |
|---|---|
| 导出 | 把 GUI 简略日志 + 本次运行的 runtime 日志合并写入 `logs/log_<时间戳>.txt` |
| 清空 | 只清界面（`LogBox.clear()`），**不动**本次的 runtime 日志文件，详细日志仍可「导出」取回 |

「清空」是旧的文件系统工具里就有的用户可达功能，重构后日志面板统一到 Hub 时漏掉了，
后来补齐在 Hub 上——因此它对六个内置工具与所有插件栏目一起生效，不必各自实现。
注意清空必须走 `LogBox.clear()`：LogBox 是 `state="disabled"` 的 Text，Tk 对 disabled
的 Text **静默忽略** `insert/delete`，直接 `delete("1.0","end")` 点了没有任何反应。

### 3.1 HiDPI（高 DPI 屏）与标题栏主题——两处都必须"统一在一个地方"

这两件事都曾经只有 Hub 做了，别处漏掉，于是出现"2.5K 屏上界面发糊""暗色主题顶着亮色标题栏"。

**（一）DPI 感知：`toolkit_base.enable_hidpi()`，import 期自动执行一次**

| 要点 | 说明 |
|---|---|
| 时机 | 在**创建任何窗口之前**。因此放在 `toolkit_base` 的导入期，任何入口（Hub / `build_gui` / 探针）只要 import 了 `toolkit` 就自动生效——旧实现只有 Hub 自己调，别的入口自然漏 |
| 逐级降级 | `SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)` → `shcore.SetProcessDpiAwareness(2)` → `user32.SetProcessDPIAware()` |
| **必须检查返回值** | 这三个 API 都是**返回 HRESULT/BOOL 而不抛异常**。旧代码不看返回值，一旦因 exe 清单已锁定 DPI 设置而失败（`E_ACCESSDENIED`），它照样往日志写"已应用"——于是没人知道界面为什么糊。现在全失败时**回报真实状态**，结果存在 `HIDPI_STATUS`，Hub 启动会写进本次的 runtime 日志 |

进程若不是 per-monitor 感知，Windows 会把**整个窗口位图**按系统缩放拉伸，这就是"糊"的根因。

**（二）像素缩放：`toolkit_theme.px()` / `ui_scale()`**

**关键区别：字体的磅值由 Tk 按 `tk scaling` 自己换算，像素值不会。**
设计稿里写死的像素（行高、缩进、勾选框、Canvas 高度、窗口 geometry、弹窗尺寸）
都是按 **96 DPI** 定的，必须过 `px()`：

| 位置 | 曾经 | 150% 屏上的后果 |
|---|---|---|
| `CanvasTree.ROW_H` | 写死 24px | 正文行高实为 32px → 行比字矮，**文字被裁** |
| `ttk` Treeview `rowheight` | 写死 24 | 同上（XML 校对表格） |
| 窗口 `geometry` / `minsize` / 弹窗 `size` | 写死 1280x860 等 | 物理像素，150% 下只有 853x573 逻辑像素，窗口明显偏小 |

`apply_tk_defaults(root)` 内部先 `sync_tk_scaling(root)`（按 `GetDpiForWindow` 校正
`tk scaling` 与全局缩放系数），**再重刷一次主题样式**——因为宿主是 `apply_theme()` 在前、
`apply_tk_defaults()` 在后，不重刷就会用 100% 的行高去配 150% 的字体。

**（三）标题栏主题：`apply_titlebar(win, mode)` 必须每个顶层窗口都调**

它在 `toolkit_theme` 里，做两件事：切 `DWMWA_USE_IMMERSIVE_DARK_MODE`（属性 20，
失败回退 19），Win11 上再设 `CAPTION_COLOR`/`TEXT_COLOR`/`BORDER_COLOR`，最后用
`SetWindowPos(...SWP_FRAMECHANGED)` 让 DWM 立即重绘。注意要先取 `GetParent(winfo_id())`
——`winfo_id()` 给的是客户区子窗口，对子窗口调用会返回 `ERROR_INVALID_HANDLE`。

调用点（当前三处，缺一处就会出现亮色标题栏）：

| 谁 | 何处 |
|---|---|
| Hub 根窗口 | `build_hub()` 与 `on_theme()` |
| 构建器根窗口 | `BuildGUI.__init__`（曾经漏掉） |
| **所有弹窗** | `dialog_window()` 内部统一调（曾经漏掉） |

`run_app_probe.py` 第 7 组对以上三者都有断言（含用 `DwmGetWindowAttribute` 反查
弹窗标题栏是否真的变成暗色）。

### 3.2 界面响应：重活一律不许待在 UI 线程

排查口径是**先量再改**（隐藏窗口下 Tk 不重绘，测出来的滚动耗时是假的，必须让窗口可见）。
实测出的三处"明显延迟"与修法：

| 位置 | 改前（实测） | 改后（实测） | 做法 |
|---|---|---|---|
| 文件系统：勾选一个未加载的包 | **点击到返回 1150 ms**（3 万条目 DB 的解析全程在 UI 线程） | **0.6 ms**（解析在后台，界面不卡） | `_load_async()` / `_scan_and_load()`：解析、`rglob` 扫描都在 `TaskRunner` 的工作线程里；`fmt` 在主线程读好传进去（`StringVar.get()` 是 Tcl 调用，不能跨线程）；状态与界面更新经 `self._ui` 回主线程 |
| 视频：转换完成后的 ffprobe | 主线程同步跑，`parse_video_info` 内 `timeout=30` → 最长僵 30 秒 | 0 ms（在工作线程跑完随回调带回） | `work()` 里解析输出文件，`_convert_done(..., out_info)` 只负责显示 |
| XML 校对：换选一行 | 20 条差异 **134 ms**；200 条 **1478 ms** | **7–10 ms**，且与差异条数无关 | 明细里的逐条 id 列表**虚拟化**：只为视口建行；Canvas/滚动条按容器缓存，换行只更新数据（原先每次 destroy 重建 → SplitPane 重排 + Treeview 整块重绘） |
| XML 校对：填充表格（切筛选） | 1 万行 / 200 条差异 **1308 ms** | **143 ms** | `detail` 列不再调 `detail_builder`（那是"完整明细"，每行一次 × 上万行），改为按**计数**拼一句摘要 |
| XML 校对：滚轮 | 15.8 ms/格（1 万行） | 2.1 ms/格 | 同上（明细控件数与内容量脱钩） |

**写成探针的不变量**（`run_app_probe.py` 第 8 组，全部用**调用次数/控件个数**判定，
不用墙钟时间，避免 flaky）：

1. `fs.勾选未加载的包` → 必须**立刻返回**且 `task.running` 为真、`loaded` 仍为空
   （即"没有同步解析"）；
2. `xml.明细 id 列表已虚拟化` → 400 条差异时常驻控件 ≤ 40 行；
3. `xml.detail 列不调用完整明细渲染` → 打桩 `detail_builder` 后断言调用次数为 0。

> 通用教训：**UI 线程只做"摆放控件"**。解析、`os.walk`/`rglob`、子进程（ffprobe 这类
> 带超时的）一律进工作线程；工作线程里**不许碰任何 Tk 对象**（连 `StringVar.get()` 都不行），
> 需要的数据在主线程读好再传进去。

### 3.3 启动绘制与分帧装配（白屏 / 可点击时间）

用户口径（2026-09-12）"优化很差"，附了一段 21 s 录屏。逐帧分析（`ffmpeg` gdigrab + 帧内
近白像素占比）与**该次运行的运行日志**（`logs/runtime_20260912_153608.log`）一起定位到两件事：

| 症状 | 实测 | 根因 |
|---|---|---|
| 启动**纯白窗口 + 蓝色忙光标** | 冷启动 **1.47 s**（录屏逐帧）、热启动 0.77 s（同法复现） | Tk 建根窗口用系统默认**白底**，而"第一次重绘"本来要等到 `mainloop`；中间要扫插件、装六个栏目 |
| 窗口画出来了却**点不动** | 到 `mainloop()` 约 **2.0 s** | 六个栏目**全部同步装配完**才进主循环；单栏目实测 文件系统 203 / 编码转换 484 / 文本提取 209 / XML校对 117 / 视频转换 198 / 汉化包生成 164 ms |

处方（两处，均在 `stalker_toolkit.py`）：

1. **`paint_startup(root)`** —— 装任何组件之前，先按当前主题画一帧（`paint_now` →
   `root.update_idletasks()`），并挂一句"正在装载组件…"。用 `update_idletasks()` 而不是
   `update()`：前者只处理**空闲任务**（映射/布局/重绘），**不取出输入事件**，因此装配未完成时
   不会重入用户回调，也不会在 `mainloop` 之前响应关窗消息。
2. **`build_tabs(root, tools, build_one, defer_rest=…)`** —— 首个栏目同步装配，**其余每个交给一次
   `root.after(1, …)`**，于是 `mainloop` 立刻开始跑；`apply_theme()` 由 `on_done` 在全部装完后
   调用一次（它要配约 100 条 ttk 样式，**绝不能进装配循环** —— 加 `paint_now` 时它被顺手缩进
   进去过一次，实跑日志显示启动被拖慢）。

实测（冷冻 exe `build_12` 自带毫秒日志，`[时间戳]` 现为 `YYYY-MM-DD HH:MM:SS.mmm`）：

| 相位 | build_11（改前） | build_12（改后） |
|---|---|---|
| 深色窗口可见（首帧已画） | 不可测（窗口是白的） | **387 ms** |
| 首个栏目就绪 → 其余分帧 | — | **859 ms** |
| **进入 `mainloop`（界面可点）** | ~2000 ms | **861 ms** |
| 六个栏目全部装完 | ~2000 ms | 2225 ms（在事件循环里逐帧补齐） |
| 白屏平台（gdigrab 录屏 30 fps，3 次） | **0.77 s / 16 帧** | **0（NONE/NONE/1 帧）** |

**写成探针的不变量**（`run_hub_probe.py` 第 [6] 段，6 条）：`paint_now` 只走
`update_idletasks` 且返回 True；`paint_startup` 建提示标签并经 `paint_now` 落笔；
AST 上 `paint_startup` 必须早于插件扫描与 `build_hub`；`rebuild` 必须走 `build_tabs`
且把 `defer_rest` **透传**（写死 `False` 就退回"装完才进 mainloop"）；`apply_theme` 不许
进装配循环；`build_hub` 里外壳的 `paint_now` 必须早于 `rebuild`。故障注入 6 条各自变红、
逐字节还原后复核（见 UI 回执）。

**残余（如实记录，未修）**：映射到首绘之间仍可能有 **1 帧**白 —— Windows 先用窗口类背景刷
（`COLOR_WINDOW` = 白）填充客户区，Tk 才开始画。要彻底消掉只能"先隐身再显示"
（`withdraw` 到装完才 `deiconify`，或 `-alpha 0`），代价是窗口**晚约 0.4 s 出现、期间什么都看不到**，
并且 `-alpha` 恢复失败会让窗口永远不可见 —— 收益（1 帧 ≈ 33 ms）远小于风险，故不做。

### 3.4 分隔条拖动与布局分配（ttk 给不了的两件事）

用户口径（2026-09-12）「拖拽式分隔条拖的时候还是一卡一卡的」「窗口没最大化时布局也有待提升」。
两条都在 `toolkit_widgets.SplitPane` 与 Hub 的装配处修掉，实测数据如下。

**（一）拖动卡顿：每一步都在重排整棵可见控件树**

先把"一次应用"的成本量清楚 —— **口径必须含重绘**（`sashpos` + `root.update()`）。
只跑 `update_idletasks` 会漏掉重绘，早期口径就是这样把成本低估了一半：

| 口径 | 一次应用 | 折算 |
|---|---|---|
| 逐事件实时（原生 ttk 行为） | **108 ms / 次拖动风暴** | ≈ 12 fps |
| 合并 motion + 冻结重窗格重绘（**现默认** `LIVE_DRAG="freeze"`） | **45 ms** | ≈ 30 fps |
| 只挪预览线（`LIVE_DRAG="line"`） | 拖动期 4.5 ms，松手 102 ms | 拖动瞬间响应 |
| 只跑几何（`update_idletasks`，不含重绘） | 37.6 ms | — |
| 冻结整窗重绘 | 22 ms | 但连分隔条都不画，无意义 |

成本构成（同一结构上分离测得）：**Win32 重绘约六成、Tcl/Tk 的 C 层布局约三成半、
Python 层约 0.25 ms/步**（cProfile 里全部时间都停在 `tkapp.call` 上等 Tcl，纯 Python
函数开销 32 步合计 8 ms）。根因是 **Tk 每个控件都是一个独立的 Win32 子窗口（HWND）**：
尺寸一变，整棵可见树都要重排 + 重画；与数据量几乎无关（日志 5000 行、树 5000 行各只多
3 ms），也不是"Python 慢"。

**修法**：`LIVE_DRAG` 三档，默认 `"freeze"` —— 实时跟手，但
①**合并运动事件**：拖动期只记最新位置、最多排一次几何应用，绝不逐事件重排（鼠标每秒
上百个 motion，逐个处理会让分隔条落后光标几百毫秒，那才是"一卡一卡"的主观来源）；
②按下时对**重窗格**（控件数 > `FREEZE_MIN_WIDGETS`）发 `WM_SETREDRAW(0)`，松手恢复并
补画 —— 窗格边框与分隔条照常实时跟手，重页面内容在松手时一次补齐。
`<Destroy>` 与 `FREEZE_MAX_MS` 看门狗上都有解冻兜底，绝不留"卡死在冻结态、窗口再也不刷新"的窗口。

> **冻结/解冻踩过的坑（用户录屏实证 2026-09-12，务必别再犯）**：解冻**不能**只
> `InvalidateRect(父窗口)` —— 子窗口在冻结期间也没被重画，而重开父窗口的重绘不会让子窗口失效，
> 结果是**整块栏目页变空白 + 错位陈旧像素且不自愈**（视频 t=12.3s / 17.3s 两帧）。
> 必须 `RedrawWindow(hwnd, None, None, RDW_INVALIDATE|RDW_ERASE|RDW_ALLCHILDREN)`；
> 且**不要**加 `RDW_UPDATENOW`（同步强制整棵子树重画，松手一下从 ~100 ms 涨到 ~490 ms）。
> 读屏幕抓图逐像素比对：噪声底 1.05% / 现实现 1.27% / 旧实现 **16.07%**，已上锁。

> **性能测量的机器状态警告**：同一份代码同一脚本，本机实测在"空闲"与"`aces` 进程持续吃
> ~280% CPU（约 3 核）+ 录屏工具在跑"两种状态下，窗口缩放每步从 **113~123 ms 变成
> 484~654 ms**（4~5 倍）；录屏本身再加 1.3~1.5×。因此 §3.4 与回执里的数字**只能跨同一轮内的
> 对照来读**，不要拿不同轮次的绝对值互相比较。

**（一之二）窗口尺寸变化（拖边框）比拖分隔条贵得多**

| 场景 | 每步（`root.update()` 口径） |
|---|---|
| 拖窗口边框一步（真实栏目页） | **128~176 ms** |
| 只跑几何（`update_idletasks`） | 9.9 ms |
| 关掉顶层重绘 | < 1 ms → **几乎全是 Win32 重绘** |
| 冻结"当前选中页"重绘 | 65~72 ms |
| Configure 去抖之后（现状） | 113~123 ms |

"以秒计" = 拖边框时 WM_SIZE 连续到达、每步 100+ ms 在队列里积压（Windows 的 resize
模态循环里 Tk 仍在逐个处理），总时长 = 步数 × 每步。**我们的对策**是把 Configure 处理
去抖：`SplitPane._clamp` 与 `CanvasTree` 的 `<Configure>→_draw` 都改成"最后一次
Configure 之后 60~120 ms 才做一次"。剩下的主要成本（当前选中页几十个控件的重绘）属
Tk/Win32 架构，见 §九。

**（二）布局：三处"请求尺寸"没被约束**

| 症状（实测） | 根因 | 修法 |
|---|---|---|
| 日志栏在 1024x700 / 1280x860 / 1440x900 下只有 **1 / 1 / 4 px** | 栏目页面请求高度合计 900+ px，把 Notebook 的请求顶到超过窗口；`ttk.Panedwindow` 只能把最后一个 pane 压扁 | 装配时为每个栏目页 `pack_propagate(False)`：页面的请求**不参与** Notebook 的请求，高度由窗格分配 |
| 「数据包列表 / 包内文件」被挤到 1~55 px | 每个 `CanvasTree` 的 canvas 请求 `height=px(300)`，一页两三个就把内层窗格撑满 | canvas 请求降到 `px(120)`（外面一律 `fill="both", expand=True`，有空间照长） |
| 给 pane 设的 `minsize` **毫无作用** | ① `ttk.Panedwindow` 的 pane **只有 `-weight`，没有 `-minsize`**（`pane(..., minsize=)` → `TclError: unknown option "-minsize"`）；② 原来的 `paneconfigure(..., minsize=)` 是 **tk 版** Panedwindow 的方法，ttk 不认 → 抛错被 `except: pass` 吞掉 | `SplitPane` 自己实现：记下各 pane 最小值，在 `<Configure>`（走 `after_idle`）与拖动结束后跑两趟 `_clamp()`（右→左保后一个 pane、左→右保前一个），总空间不足时**让后面的 pane 先挨饿** |

实测（物理像素，本机 150% 缩放）：

| 窗口 | 日志栏（min 165）改前 → 改后 | 文件系统页被挤扁容器 |
|---|---|---|
| 1024x700 | 1 → **89** | 9 → 5 |
| 1280x860 | 1 → **129** | 2 → **0** |
| 1440x900 | 4 → **139** | 2 → **0** |
| 真实默认 1920x1290 | 被挤到最小 → **461**（栏目区 1107 → 811） | 0 |

**（三）顺带修掉一个"看着对、其实空转"的真 bug**：`ttk.Panedwindow.panes()` 返回的是 Tcl 路径
**字符串**而不是控件对象，原代码把它当控件用（`p in alive`、`walk(pane)`），于是
`refresh_children()`（类文档声称"拖动后强制重绘自绘控件"）**从未生效过** —— 遍历到的全是字符串，
`winfo_children()` 直接抛 AttributeError 被吞掉。现在统一过 `_panes()`（`_nametowidget` 转换）。

**写成探针的不变量**（`run_hub_probe.py` 第 [7] 段，5 条，全部用真 Tk 对象/真实几何判定，
不用墙钟时间）：`SplitPane` 的 minsize 两趟收敛（夹具里后一个 pane 的原生分配只有 83 px < 120，
必须被顶到 120 —— 少任何一趟都测得出）；`_panes()` 必须是控件对象且与 `_children` 对齐；
`refresh_children()` 必须真的触达 pane 里 `CanvasTree._draw`；命中 sash 时 `_rb_press` 必须返回
`"break"` 且**拖动期不得改变 `sashpos`**、松手必须改一次；AST 上栏目页必须 `pack_propagate(False)`
且 Hub 两栏都带 `minsize`。

**已知取舍（刻意，不是遗漏）**：拖动期间不再实时改变内容尺寸 —— 这是拿"内容跟手"换"跟手不卡"。
要在 Tk 上同时做到两者，只能把整页控件数降到几十个（布局重写）或自己接管绘制（不现实）。

### 3.5 滚动条：平时隐藏、装不下才出现（`AutoScrollbar` / `ScrollViewport`）

**用户口径（2026-09-12）**：滚动条不该常驻 —— 装得下的时候它是纯噪声，还白占宽度、
把内容挤窄。**所有**滚动条都该这样；整个界面也要一条"内容高度超出窗口才出现"的纵向滚动条，
且那条属于**主界面**的功能（不是某个组件的）。

**`AutoScrollbar(parent, orient=…, command=target.yview)`** —— `ttk.Scrollbar` 的直接替代，
调用方式（含 `pack`/`grid` 的写法）一行都不用改：它**记住调用方用的布局参数**，
然后按"内容装不装得下"自己 `pack_forget`/`grid_remove` 或放回原处。

* 判定：被滚控件回调 `set(first, last)`，`first <= 0 且 last >= 1` 即装得下 → 收起；
* **滞回**：用 `last >= 1.0` 而不是 `>= 0.999`。滚动条一出现就占宽度，内容变窄后可能
  又"刚好装得下"→ 收起 → 又超出 → 出现，肉眼就是**闪**。真正装得下时 Tk 给的 `last` 恰好
  是 `1.0`，所以这条界线不会误判（`0.999` 仍算超出）；
* `grid` 场景用 `grid_remove()`：它记住格位，放回时不用重算（`pack` 放回只能排到末尾，
  调用方一般只放一个滚轴，可接受 —— 已写在类文档里）。

**`ScrollViewport(parent, horizontal=…, minsize_y=…)`** —— canvas 视口：内容保持**自然尺寸**，
装不下就滚、装得下就铺满；`horizontal=True` 时内容**左对齐**（`anchor="nw"`）且保持自然宽度。

| 场景 | 内容窗口尺寸 | 结果 |
|---|---|---|
| 视口比内容大 | `max(内容请求, minsize, 视口)` = 视口 | 铺满、无滚动条 |
| 视口比内容小（纵向） | 高度取内容请求，宽度=视口宽 | 纵向滚动；横向不浪费（页面照旧吃满宽度） |
| 视口比内容小（`horizontal=True`） | 宽高都取内容请求 | 左对齐 + 横竖两条滚动条 |

**Hub 的窗口级滚动条就在主界面代码里**（`stalker_toolkit.build_hub`）：`ScrollViewport`
包住两栏，`minsize_y = min_top + min_log + px(16)`，而两栏的 `minsize` 用的**就是这两个变量**
—— 否则"滚动条出现的时机"和"两栏真的被压死"的时机会各说各话（第二真值）；
滚轮绑在 `root` 上（内层可滚控件自己消费时会 `break`，事件到不了窗口级处理器，
所以"在日志里滚日志、在空白处滚整页"两不冲突）。

**写成探针的不变量**（`run_hub_probe.py` 第 [8] 段，13 条，全部真控件 + 真几何）：
装得下收起 / 超出出现 / 再装得下又收起；收起时**真的把宽度让给内容**（实测 300 → 285，
不是只改配置）；临界点滞回；`grid` 场景放回原格位；是 `ttk.Scrollbar` 子类；`toolkit` 有导出；
视口在"内容大/视口大"两种情形下滚动条的出现与消失；内容**不被压扁**（保持自然宽度 500）；
`minsize_y` 生效；纵向视口内容横向铺满；AST 上 Hub 用了 `ScrollViewport` + 绑了滚轮 +
`minsize_y` 覆盖两栏 minsize。另有**收敛锁**：活代码里不许再有裸 `ttk.Scrollbar(` 调用点
（漏一处那一处就还是常驻占宽）—— 例外只有 `toolkit_plugin_ui.py` 里 `_SB = ttk.Scrollbar`
那句回退（没有括号，不匹配该模式；那个模块的设计目标是最小依赖、要能单独 import）。

**度量教训（同一天踩的，如实记）**：为查"日志栏往上拖时内容不显示"我写了个像素测量脚本，
结论**无效**，三处口径都错了：① 用"底色占比"当"空不空"的判据 —— 文字内容本来就以底色为主
（实测 92%），分不出"内容在"与"内容没了"，应该看**非底色占比**（墨迹）；
② `_apply_drag` 是 `after(1)` 排的，测完 `update()` 立刻采样，回调还没跑 → **拖动根本没生效**
（`sash0` 前后不变就是铁证）；③ 采样用的是**固定 bbox**，而窗格几何在变，采到的是"原地那块屏幕"
而不是"当前那个窗格"。**先断言"刺激真的生效了"（这里就是 sash 必须动过），再谈观测**
—— 这条与之前 device-pixel-ratio 那次是同一类错误：口径不说清楚，数字就是错的。

---

## 四、公共库各模块职责

> 职责描述取自各模块 docstring 与公开符号。各模块**行数见附录 A**（集中一处，便于随代码更新）。

| 模块 | 职责与要点 |
|---|---|
| `toolkit_log.py` | 日志管线。只依赖 `datetime/os/re/sys/time`，**必须能在 `import tkinter` 之前导入**。对外 API：`summary`（落盘 + GUI 日志栏，GUI 未就绪先缓冲、由 `take_buffer()` 回放）/ `detail`（**不写 GUI**，只落盘，导出时全量）/ `log_to_file`（保持旧的"只落盘"语义）/ `set_gui_sink` / `set_log_dir` / `log_path` / `log_name` / `app_dir_fallback`。**每次启动一个新日志文件** `logs/runtime_<启动时刻>.log`（`YYYYMMDD_HHMMSS`，与导出产出的 `log_<时刻>.txt` 用同一时刻格式）；时刻在 import 期定一次，整个会话的所有线程写同一个文件；**行时间戳带毫秒**（`[YYYY-MM-DD HH:MM:SS.mmm]`，同一 `datetime` 对象取值）。**保留策略**见本文档"`logs\` …"一节：`retention_keep(标记)`（纯函数：预发布 → None、正式版 → 100）/ `set_log_retention` / `cleanup_logs(keep, log_dir)` / `cleanup_startup_logs()`（启动幂等一次）/ `current_keep` / `policy_applied`（探针核对"接线没被删"用）。**并发与不静默**（外部审计 A-1/A-2/A-3，2026-09-12 修）：写盘走 `_WRITE_LOCK`、启动期缓冲走 `_BUFFER_LOCK`（`take_buffer` 的"关闭缓冲 + 取走"是一个临界区）、写盘失败记 `log_write_failed()` 并往 stderr 留一行（Hub 启动时读它并在日志栏说出来）。`logs/` 仍**不被 CI 的 `cleanup()` 清理**。 |
| `toolkit_base.py` | `APP_NAME` / `APP_VERSION` + `APP_PRERELEASE` + `BUILD_COUNT` + `PRERELEASE_COUNTS`（**版本、标记与两个构建计数的单一事实来源**，由构建工具写回）/ `app_dir`（**re-export 自 `toolkit_paths`**）/ `ensure_package` / `_BaseTk` / `_HAS_DND` / `DND_FILES` / `set_app_icon` / `errbox` / `enable_hidpi` + `HIDPI_STATUS`。导入期即 `toolkit_log.set_log_dir(app_dir())`，并设置进程级 DPI 感知。 |
| `toolkit_paths.py` | `app_dir()` —— **Tk 无关**的最小模块（规则 5 行）。存在的唯一理由：`user.ltx` / app 配置 / 日志目录都要这条规则，而消费方里没有一个是 UI 层的；非 Tk 后端（Qt 试点）不该为了读设置把 Tk 拉进进程。`toolkit_base` 与 `toolkit_platform` 都从它取（前者 re-export，三种既有用法全部不变）。**不要在这里 import tkinter** —— 那等于把刚断开的依赖接回去。 |
| `toolkit_theme.py` | 主题**单文件**：`THEMES`（dark/light 两套色板）+ `_FONTS` + `palette` / `T` / `CURRENT_MODE` / `color` / `apply_theme` / `apply_tk_defaults` / `load_user_theme` / `save_user_theme`（只读写 `user.ltx` 的 `[theme]` 段，由 `toolkit_platform` 落盘）/ `apply_titlebar` / `_role_of`。新增主题只往 `THEMES` 加数据。 |
| `toolkit_widgets.py` | 通用组件，六个 App 与插件共用：`refresh_theme` / `path_row` / `dir_row` / `count_label` / `tool_header` / `tool_text` / `tool_label` / `tool_button` / `themed_entry` / `themed_listbox` / `dialog_window` / `stat_grid` / `vscrollbar` / `drop_zone` / `LogBox` / `log_section` / `CanvasTree` / `SplitPane`（**pane minsize 与拖动预览线由它自己实现**，见 §3.4）/ `TaskRunner` / `status_style(_name)`，以及插件接线件 `plugin_slot_bar` / `PluginSlot` / `attach_plugin_context_menu` / `tool_dropdown` / `refresh_dropdown` / `plugin_options_area` / `tool_panel` / `plugin_entries` / `invoke_plugin_callback`。 |
| `toolkit_plugins.py` | 插件宿主：`PluginManager`（扫描/共享实例/查询）+ `Api`（9 个 `register_*`）+ 槽位常量表（`HOST_*` / `LOC_*` / `AREA_*`）+ 行分类与筛选语义（`MODE_ROW_KINDS` / `MODE_DIFF_TYPES` / `row_matches_filter` / 默认筛选集）。 |
| `toolkit_textio.py` | 文本/文件 IO 纯函数：`fmt_size` / `read_text_file` / `read_text_bytes` / `decode_bytes` / `decode_file` / `sniff_encoding` / `is_multibyte_utf8` / `bytes_fit_encoding` / `parse_xml_texts` / `collect_files`。**判定链（多/单字节检查优先级最高）**：BOM → **多字节检查**（能按 UTF-8 解码**且含多字节序列** → utf-8；纯 ASCII 不算，继续往下）→ 手动指定 → **XML 声明（须被字节证实）** → chardet 统计探测 → `windows-1251`。三条实测依据：① 多字节排在手动之前，因为"多字节 UTF-8 的字节用单字节编码解必是乱码"属物理事实，而纯 ASCII 在两种编码下字节完全相同、没有多字节证据，就该让位给用户选择与声明；② 声明是**文件自己的声称**，字节能证明它是假的时候就不采信（`bytes_fit_encoding`）——只靠多字节检查只能证明"不是 UTF-8"，不能证明"是哪种单字节编码"，若不校验声明，"字节 cp1251 + 声明 utf-8"会被判成 utf-8，目标=utf-8 时静默跳过、目标非 utf-8 时正文被成片替换；③ chardet 的低置信度猜测只采信**多字节家族**（`_is_single_byte_codec` 程序化判定，不维护编码名单——手工名单漏掉过 cp865/0.025 导致整篇乱码）。**逐文件**跑本函数，所以 `override="auto"` 天然支持"一目录多编码"。编码候选顺序另有实测依据（`gb18030` 必须排在 `windows-1251` 之前）。 |
| `toolkit_platform.py` | **用户设置** `user_config_path`（`app_dir()/user.ltx`，极简 INI 按 `[段]` 分节）+ `load_user_config` / `load_user_value` / `save_user_value` / `save_user_values`（一律"读 → 改一项 → 整体写回"，**保留其它段**）；`app_config_path` / `load_app_config` / `save_app_config`（`app_dir()/<name>.cfg.json`，通用库能力，当前无调用方）；`locate_exe`（应用配置 cfg.json → 应用目录 → extra_dirs → PATH，**不读** user.ltx——需要用户级设置的工具自己 `load_user_value` 后把结果传进来，见 `apps/video_ogm_app.find_ffmpeg`）、`run_hidden` / `hidden_kwargs`（`CREATE_NO_WINDOW`）、`system_font_dirs` / `open_in_explorer`。查找函数**不写盘**。 |
| `toolkit_constants.py` | 纯数据、零依赖：包扩展名 `PKG_EXTS` / `PKG_EXT_MARKERS`、格式↔扩展名 `EXT_FOR_FORMAT` / `output_ext_for`、SquashFS 工具名 `SQFS_TOOL_NAMES`、备份约定 `BACKUP_DIRNAME` / `BACKUP_SUFFIX`、编码候选 `ENCODING_CHOICES` / `LEGACY_ENCODING`、文本提取命名模板。 |
| `toolkit_version.py` | 版本号与构建计数：`parse_full_version` / `split_prerelease` / `format_prerelease` / `normalize_base` / `full_version` / `version_tuple` / `current_base_version` / `save_base_version` / `save_version`（写回前备份到 `backup/pre_version_change/`）/ `next_prerelease`（预发布标记序号：按 **(完整版本串, 标记名)** 各自计数，`consume=False` 只读、`True` +1 落盘；键用完整版本串而非 semver 主号）/ `current_build_count` + `save_build_count`（构建次数）。**四项常量都住在 `toolkit_base.py`**：读取走 `_constant_text`（进程内模块属性优先、文件正则兜底，`BASE` 被重定向时只认副本文件），写回走 `_write_base_constant`（整行替换、缺行补写、临时文件 + `os.replace` 原子写，坏值/缺行一律当默认而绝不打断构建）。 |
| `toolkit_guard.py` | CI 静态守卫：颜色字面量、字体字面量、`creationflags=subprocess.CREATE_NO_WINDOW`、插件调用点的裸 `host`/`area` 字符串。只扫 `apps/`。**点名清单（host/area）由 `toolkit_plugins` 常量表派生**（原先手抄一份，往表里加挂载点会静默漏检），`run_guard_selftest.py` 再从两个方向钉住：逐名命中（表里每个名字都必须真被抓到）+ 派生的点名集合与钉住清单一致（覆盖范围不许悄悄缩水）。逃生舱：行内注释 `# guard: allow`。 |
| `toolkit.py` | **纯 re-export 层，不含实现**。文件内 import "未被使用"是设计使然 —— 末尾模块级 `__all__`（146 名）就是它的对外契约，pyflakes 视 `__all__` 中的名字为已使用，因此**不需要**（也不再有）整文件豁免。`run_app_probe.py` 有 6 条契约锁：字面量 `__all__` 存在、无重复、**覆盖全部 import**、**不含未 import 的名字**、运行期 `__all__` 与字面量一致（防运行期 `append` 偷加名字）、每个名字都能真取到。 |

归层要点：`refresh_theme` 需要引用 `LogBox` / `CanvasTree.recolor`，必须在 widgets 层；
`apply_titlebar` 依赖 `palette`，属主题层；`LogBox` 是**组件**而日志**管线**独立成
`toolkit_log.py`，这样日志才能在 `import tkinter` 之前初始化。

### 4.1 编码判定：这条链为什么长这样，以及**不要再往上面加东西**

**结论与口径（用户决策，勿改）**

1. **手动指定是可靠模式，`auto` 是便利模式。** 只要事先查清目录真实的编码，手动就不会错；
   `auto` 是给图方便的人用的，本质是猜，**仍然可能出错**。
2. **链的排序不是为了"让 auto 变聪明"，而是为了让手动在真实目录里可用。**
   ①多字节检查压在手动之上，才使得"对一个混着 UTF-8 文件的 windows-1251 目录手动选 1251"
   这件事成立 —— 若手动是绝对压制，那些 UTF-8 文件必然被毁。实测：受约束环境下
   手动 1251 与 `auto` 都是 22/22，而手动 `utf-8`/`windows-1252` 只有 12/22
   （挂掉的全是 cp1251 文件，能救的 UTF-8 文件仍被①救下）。
3. **只覆盖两种编码：多字节只用 UTF-8、单字节只用 windows-1251。**
   "多字节不用 utf-8"（GBK/Big5…）与"同一目录里有不止一种单字节编码"这两种情况
   **现实基本遇不到**；要为它们写代码（阈值、打分、逐段重判）必然非常冗余。
   所以这两种情况**不解决**，也不引入任何相关机制。
4. **不建议做的事**（都是被讨论并否决掉的，**不是硬性禁止** —— 链条本身不禁止改动，
   只是这些改法收益低、代价高，改之前先想清楚）：
   * 加"坏字节比例分级 / 置信度打分"来决定是否改判编码；
   * 给手动指定加约束（当前语义是字节不否定它，它说是什么就是什么）；
   * 自动把判定结果改写回配置文件，或"顺手"修正用户的选择。
   判定层目前只做一件事：**按链给出一个编码名**；链之外的策略默认不加。
   真要改链，请连带更新 §4.1 的口径与 `run_functional_probe` 第 6/9 组的锁。

**怎么查清真实编码（用现成功能，无需新代码）**

用 `源编码 = auto` + **输出到新目录**（绝不碰原文件）跑一遍，再看本次的 runtime 日志
`logs/runtime_<启动时刻>.log`（或点 Hub 的「导出」，它会把简略日志与详细日志合成一份）。
逐文件的判定结论与**决定它的那一步**都在里面（`log_detail` 级，只落盘、不刷 GUI），
标签与判定链一一对应：`多字节(...)` = ① 含多字节序列、`指定(...)` = ② 手动、
`声明(...)` = ③ 采信（且被字节证实的）XML 声明、`统计(...)` = ④ 统计探测/默认：

```
[成功] string_table_ui.xml  | 声明(windows-1251) → utf-8
[成功] arc_string_table.xml | 统计(windows-1251) → utf-8
[跳过] mike_strings.xml     | 源=多字节(utf-8)，已是目标编码；已对齐声明/BOM → utf-8
```

（原先每行末尾还有 `| 校验通过` / `| 校验失败: …`。「自动校验」已按决策删除，
见下条与 `apps/convert_app.py` 里 `自动校验：已删除` 那段说明。）

（`mike_strings.xml` 的声明写的是 windows-1251，但字节是多字节 UTF-8，所以由①定的案；
标签如实写 `多字节` 而不是 `声明` —— 这一行是用户核对"目录到底是什么编码"的依据，不能含糊。）
确认整目录结论一致且都合预期后，再改成手动指定、做原地转换。

---

## 五、插件系统

完整写法与 API 细节见 [PLUGINS.md](PLUGINS.md)，此处只记架构事实。

- 目录：`plugins\**\*.py`；忽略 `_` 开头文件、`__pycache__`、`.git`；支持 `enabled.txt`
  白名单（`fnmatch`，`*` `?` 通配）；按相对路径排序加载。
- 插件文件提供 `PLUGIN_INFO` 与 `register(api)`；旧式只提供 `decrypt_sq` / `open_sq`
  的插件仍被自动接成解密器。

**扩展点全清单（实测 `toolkit_plugins.py` 中 `def register_*`）**

| # | 注册点 | 消费方 |
|---|---|---|
| 1 | `register_decryptor(check, decrypt)` | 引擎分类为 `encrypted` 后的通用解密链 |
| 2 | `register_format(name, handler)` | 文件系统的格式表（`handler` 需 `unpack` / `pack`） |
| 3 | `register_command(action_id, label, handler, when=None)` | 命令中心，`id = <插件文件>:<动作名>` |
| 4 | `register_menu_item(...)` | 槽位挂载点（新形态引用命令，旧形态自带 callback） |
| 5 | `register_option_entry(host, area, value, when=None)` | 往**已有**下拉加条目 |
| 6 | `register_option(label, choices, callback=None, host, area, when, order)` | **新建**插件下拉 |
| 7 | `register_panel(title, builder, host, area, order, when)` | 往组件区域贡献面板 |
| 8 | `register_tool(name, builder, order=0)` | 新增 Hub 栏目 |
| 9 | `register_compare_mode(name, columns, compare, row_builder, filters, order, detail_builder)` | XML 校对的比较模式（贡献点） |

另有 `PluginManager.register_compare_mode(...)`（与 `Api` 上的同名方法签名略有差别，供**内置**
模式使用）：`apps/xml_compare_app.py` 在 `XMLCompareApp.__init__` 里遍历
`xml_modes.builtin_mode_specs()` 逐条注册**内置**两种模式（行数/ID 统计、ID 文本对比）。
内置与插件进的是同一张 `compare_modes` 表，组件侧没有 `== MODE_TEXT` 之类的分支。

**注意内置模式的注册时机**：它需要先拿到 `PluginManager` 实例，所以**随 App 构造**才发生，
而 Hub 的顺序是「先扫插件、后建 App」——插件往往先占住名字。因此：
- `register_compare_mode` 遇到同名**不会**把内置挡回去（否则内置永远进不了表、插件独占该名字）；
  同一内置名字重复登记会被跳过，避免 Hub 重建界面时注册表无限增长；
- `compare_modes_for()` 保证同名时 **`plugin == "<builtin>"` 的那条生效**，与注册顺序无关，
  插件（可能只是无意重名）顶不掉内置。`run_ext_probe.py` 对此有专门断言。

**槽位寻址模型**（`toolkit_plugins.py` 为唯一事实来源）

| 维度 | 常量与取值 |
|---|---|
| host | `HOST_FS` `HOST_CONVERT` `HOST_TEXT` `HOST_XML` `HOST_VIDEO` `HOST_FONT`（= `fs` `convert` `text` `xml` `video` `font`） |
| location | `LOC_TOOLBAR`（工具标题下方一行动作区）/ `LOC_CONTEXT`（主内容控件右键菜单） |
| area | `AREA_TOP_BAR` `AREA_FORMAT` `AREA_PACK_FORMAT` `AREA_SOURCE_ENC` `AREA_GAME` `AREA_LANG` `AREA_SIZE` `AREA_SUFFIX` `AREA_FILTER` |

- **精确匹配，不跨槽位回退**；非法寻址在注册时被拒绝，并写入 `registration_errors` →
  合并进 `load_errors`（Hub 启动弹窗可见）。绝不静默丢弃。
- **`when` 条件**：`None` 恒显示；`dict` 要求宿主传入的 context 键相等（缺键即不满足）；
  **可调用对象**则调用之（`_when_ok`）。
- **context 可传可调用对象**：`PluginSlot._current_context()` 检测到 callable 就调用，
  因此状态会变的工具可以传 `lambda: {...}`，避免"构造时的快照被冻结、`when` 永远为假"。
- **`PluginSlot.refresh(context=None)`**：按当前 context 重算槽内命令；无可见命令时
  销毁容器并置 `frame=None`；`refresh(context=新dict)` 可直接替换 context。运行期状态
  变化（如 fs 的 `loaded` 由空变有）后调它即可让 `when` 生效。
- **`order` 排序**：所有挂载点/下拉/面板按 `order` 升序稳定排序，同值保注册顺序。
- **当前已接线的槽位**（实测 `apps/*.py` 调用点）：
  - `toolbar`：六个 App 全部接线（`plugin_slot_bar(...)`）。
  - `context`：仅 `fs_app`（DB 列表右键）。
  - 面板/新建下拉区域：`tool_panel(...)` 见 `fs_app` / `xml_compare_app`；
    `plugin_options_area(...)` 见 `fs_app` / `video_ogm_app`。

**共享实例**：Hub 启动时 `PluginManager.shared(plugins_dir, log=…, summary=…)` 初始化并
`scan()` 一次；其余消费方（文件系统工具、`PluginSlot`、`plugin_entries` 等）调用
`PluginManager.shared()` 取同一份，避免重复扫描与多实例。未被显式初始化时按
`<项目根>/plugins` 兜底自建，进程内仍只有一份。

**通用解密上报**：加密容器由引擎分类为 `encrypted`（`sqfs_check()` 只返回 `sqfs` /
`encrypted` / `unknown`，不携带模组名），应用层统一走插件解密链，日志以插件
`PLUGIN_INFO.name` 上报，三种结果措辞分明（成功 / 认领但输出无法识别 / 无插件认领）。
工具内不存在任何具体模组名的分支，也不 `import` 具体插件模块。

---

## 六、引擎与字库

**DB 六格式**（`stalker_fs.FORMATS` 实测键序：`xdb` / `2947ru` / `2947ww` / `2945` /
`2215` / `11xx`）：

- header 恒 LZHUF；`2947ru` / `2947ww` 再经 `_Scrambler`（`_CFG` 给两套 seed/scramble 参数）。
- 文件体按 `size_comp != size_real` 走 LZO1X，否则原样；`11xx` 特殊：`uncomp == 0` 时载荷为 LZHUF。
- **offset 是文件绝对偏移、自 8 起算**（`_build_header_xdb` 用 `off = 8` 起步）。
- **HEADER 的接受判据是"结构自洽优先"**（`_read_chunks`）：扫描是逐字节回退的
  （要认非 8 字节对齐的数据），而 `_validate_header` 只要求"有一个条目像样"，
  两者相加会让**载荷内部一段碰巧能解出条目的字节**冒充 HEADER（截断/畸形包尤其容易
  走到逐字节路径）→ 整包解出错误文件名。现在先记候选，**与整份文件结构自洽**的候选
  （所有非目录条目 `offset + size_comp` 落在文件内）优先；一个自洽的都没有才退回第一个
  通过轻量校验的候选，保持对畸形包的既有容忍度。"结构像样"的判据只有一处定义：
  `_entries_fit_file`，`auto_detect` 用的 `_entries_self_consistent` 也走它。
- 公开 API：`pack_db` / `unpack_db` / `auto_detect` / `load_db` / `extract_file` /
  `lzo1x_decompress` / `sqfs_check` / `sqfs_list` / `sqfs_extract` / `sqfs_pack`。

**LZHUF 两条路径**：纯 Python `_Lzhuf` + 可选 DLL 加速（`_load_dll` 依次找同目录
`lzhuf_dll.dll` → `%TEMP%` 下由 `lzhuf_dll.b64` 解码出来的副本）。装配完成后
`lzhuf.encode` / `lzhuf.decode` 被换成 `_lzhuf_encode_locked` / `_lzhuf_decode_locked`。

**SquashFS**：通过 `deps\squashfs-tools-ng-*` 的 `rdsquashfs.exe` / `sqfs2tar.exe` /
`tar2sqfs.exe`。列表结构走 `rdsquashfs --describe`，尺寸走一次 `sqfs2tar`；
批量导出用一次 `sqfs2tar` 而非逐个 `--cat`。

**字库**（`font_pack/font_pack.py`）：`extract_chars` → `render_font` → `write_dds` →
`build_package(game, lang, xml_dir, font_path, out_dir, …)`。字号表 `SIZES`（10 档：
11/13/15/16/17/18/20/21/23/25）、`CELL_HEIGHTS`、`BLOCK_WIDTHS`；字宽表外置
`adv_tables.json`（实测 10 个字号 × 各 125 条）。游戏版本 `GAMES` = `SoC` / `ClS` / `CoP`。

---

## 七、构建、探针与 CI

### 7.1 构建

| 入口 | 说明 |
|---|---|
| `python build_gui.py` | 图形构建器（推荐）。**不重写构建逻辑**，只是 `build.py` 的外壳，走同一构建函数 |
| `python build.py` | 命令行。`--out DIR` / `--version X.Y.Z` / `--prerelease BETA.1`（实测 `parse_args`）；不给 `--prerelease` 时标记序号自动 +1，显式给出则原样使用且不动计数 |
| 默认产物 | `builds\build_N`（**目录名不带版本号**）；版本号进内侧应用名：`builds\build_N\STALKER Localization Toolkit X.Y.Z[ 标记]\`，exe 同名 |
| 计数文件 | **没有独立文件**：构建次数存在 `toolkit_base.BUILD_COUNT`（`next_build_dir` 递增；读到非数字或撞上已存在目录时**往后找第一个空号**，绝不覆盖历史产物）。历史上有过 `build_count.txt`，已删除 |
| 标记计数 | 同样存在 `toolkit_base.PRERELEASE_COUNTS`：键 `"<完整版本>|<标记名>"` → 已用序号（纯字面量，可手改；缺失/空/损坏一律当空；临时文件 + `os.replace` 原子写）。历史上有过 `prerelease_count.json`，已删除 —— 两个计数与版本号/标记**同处一份文件**，是同一份"构建状态" |

**版本号 / 标记 / 两个计数的单一事实来源与流转**（这是构建章节的核心）：

1. **四项并列放在 `toolkit_base.py`**，它们是一体两面，分几处存必然对不上：
   ```python
   APP_VERSION       = "1.0.1"       # 基础版本
   APP_PRERELEASE    = "ALPHA.2"     # 预发布标记（"" = 无标记）
   BUILD_COUNT       = 5             # 已构建次数（产物目录编号）
   PRERELEASE_COUNTS = {}            # {"<完整版本>|<标记名>": 已用序号}
   ```
   后两项**由构建工具写回**（`build.py` 推进、`build_gui.py` 只读），读写实现只有
   `toolkit_version.py` 一处：读取"进程内模块属性优先、文件正则兜底"（`BASE` 被探针
   重定向时只认那份副本），写回"同目录临时文件 + `os.replace`"原子替换、缺行时补写、
   坏值当默认（0 / 空）而绝不打断构建。
2. `toolkit_version.py` 负责归一化（`beta1` / `BETA.1` / `b1` → `BETA.1`；通道别名
   `a/alpha → ALPHA`、`b/beta → BETA`、`rc → RC`、`pre → PRE`）、组合显示串
   （`full_version` → `1.0.1 ALPHA.1`）、推导 Windows 四段数字版本
   （`version_tuple`，`BETA.1` → `(1,0,0,1)`，纯 `1.0.1` → `(1,0,1,0)`；预发布字母**不进**
   数字段），以及写回。
3. **`full_version()` / `version_tuple()` 的 `prerelease` 默认值是 `None` = "用已保存的标记"**，
   显式传 `""` 才是"这次不带标记"。因此运行时标题、启动日志、产物名读的是同一个串。
4. `build.py --version` / `--prerelease` **都会写回**（`VER.save_version`，一次改两行，
   写回前备份旧文件；与 `build_gui.py` 的「保存版本号与标记」是同一实现）。
   **不给 `--prerelease` 直接构建时标记序号自动 +1**（`VER.next_prerelease(consume=True)`，
   按 (完整版本串, 标记名) 各自计数）：同版本同标记 1→2→3、换标记名从 .1 起、换回用过的
   标记**续上**原序号、版本串一变就重新从 .1 数（键是**完整版本串**，不是 semver 主号）。
   显式给 `--prerelease` 则**原样使用且一个字节都不动计数**（手工输入优先，与
   `BUILD_COUNT` 同规矩）。构建 GUI 在未手改标记时就是"不传 `--prerelease`"，
   让推进点只剩 `build.py` 一处；手改标记后才显式传，界面「当前」框写明"计数不动"。
   清空标记：`--prerelease ""` 或 GUI 里把标记选「无」（构建或保存都会清空）。
5. **构建次数与标记序号都写回上面那一份文件**（`BUILD_COUNT` / `PRERELEASE_COUNTS`）：
   `next_build_dir()` 先 `VER.current_build_count()` 再 `VER.save_build_count()`，
   `next_prerelease(consume=True)` 走 `_save_prerelease_counts()`，两者共用
   `_write_base_constant()`（整行替换 / 缺行补写 / 临时文件 + `os.replace`）。
   因此**不再需要第二个计数文件**；探针把 `V.BASE` 指向一份 toolkit_base.py 临时副本，
   就同时隔离了"版本号 + 标记 + 两个计数"。
6. 两个易踩的坑（都已有回归锁，见 `run_build_probe.py` 第 3 组）：
   * **写文件后要同步进程内模块**：`import toolkit_base` 拿到的是缓存对象，只改文件的话
     同一进程里紧接着的 `current_base_version()` 会读回旧值（构建器"保存后立刻构建"就会用错版本）；
   * 但**重定向 `BASE` 写临时副本时不能同步**（否则污染当前进程，探针后面还要读它）——
     所以同步带 `os.path.abspath(BASE) == _REAL_BASE` 判定。构建器取"本次生效值"也改为
     用命令行显式参数优先，不再依赖这次同步。**读取侧判据与此对称**：`BASE` 一旦被
     重定向，`APP_VERSION` / `APP_PRERELEASE` / `BUILD_COUNT` / `PRERELEASE_COUNTS`
     一律只认那份副本文件，不再读进程内模块属性。
7. PyInstaller 的 version-file 用四段数字，窗口标题与日志用显示串——两处由同一模块推导，
   避免"给人看的版本"与"给系统看的版本"各写一份。

构建细节：`--onedir --windowed`，清 `.gitkeep` / `__pycache__`，`plugins` / `logs` 建在 exe
同层（可写），`logs\` 里放一份说明文件（`README.txt`，既保证目录非空，也把
`runtime_<启动时刻>.log` 的命名规范写给打开该目录的人看），本地存在
`ffmpeg.exe` / `ffprobe.exe` 时
拷到 exe 旁。**闭源插件 `plugins\nlc_sqfs.py` 在构建期间被临时移出**打包范围（`finally`
里恢复）。`chardet` 声明为隐藏导入。

**ffmpeg / ffprobe 不落独立的配置文件**（历史遗留的 `video_ogm_tool.cfg.json` 已删除）：
`build.py` 把两者拷到 exe 旁、`download_ffmpeg.py` 下到项目根，两处都等于 `app_dir()`，
`locate_exe` 的第二步直接命中，imageio-ffmpeg 还能自动安装；再缓存一份绝对路径既冗余，
又会因查找顺序（配置在 `app_dir()` 之前）让陈旧记录**压过随包发布的二进制**。

自动查找到的路径**不再写盘**；只有用户在「设置 ffmpeg」里**手动指定**的才记进
`user.ltx` 的 `[ffmpeg] path/probe`（用户级、跨工具共用的唯一设置文件），
并且它优先于自动查找——**手动选过就尊重它**（原实现在末尾无条件用 imageio 覆盖
ffmpeg，等于手动选择白存）。`toolkit_platform` 的 `load_app_config` / `save_app_config` /
`locate_exe(config_name=…)` 作为通用库能力保留（`run_app_probe` 有覆盖），只是不再有调用方。

### 7.2 `run_ci.py` 当前实际步骤（按执行顺序，实测）

| # | 步骤 | 说明 |
|---|---|---|
| 1 | `compileall` | 遍历活代码 `py_compile`；跳过 `_SKIP_PARTS = ("__pycache__", "builds", "backup", "temp", ".git", "cross_validate_out", "deps")` |
| 2 | `import modules` | 导入 `toolkit` / `file_system.stalker_fs` / `plugins.nlc_sqfs` / `stalker_toolkit`；闭源插件不在库中时 SKIP。**自带编码兜底**（文件顶部对 `sys.stdout/stderr` 做 `reconfigure(encoding="utf-8", errors="replace")`），因此 GBK 控制台直接跑也不会因 `UnicodeEncodeError` 中断，**不需要外部设 `PYTHONIOENCODING`** |
| 3 | `DB roundtrip all formats` | 对 `stalker_fs.FORMATS` **每个格式**做 pack → unpack → `extract_file` 逐字节比对 |
| 4 | `cross_validate (external converter)` | 需 `cross_validate.py` + 外部 `converter.exe`（路径可用 `STALKER_CONVERTER_EXE` 覆盖）。**`--fast` 整步跳过**并记入"未覆盖"清单；默认档缺件 SKIP + 记清单；**`--release` 缺件即 FAIL** |
| 5 | `run_ext_probe (扩展点端到端)` | 正例（每条注册是否真的落地）+ 负例（错误写法必须既不生效又留痕）。探针插件写进**本进程独有的临时目录**，可与其他探针并发运行 |
| 6 | `run_app_probe (构造级 + 入口级)` | **94 项**（含库契约与日志保留/并发）：构造六个 App + 调用安全入口 + TaskRunner 生命周期 + `toolkit_textio` 编码判定 + `toolkit_platform` + `toolkit_constants` + `toolkit.py` 的 `__all__` 契约 + 日志策略/写盘锁/缓冲锁；打桩全部对话框；无桌面则 SKIP 且退出码 0。<br>计数只作参考：**以实跑输出为准**（每条加固都会加） |
| 7 | `静态守卫自测 (守卫是否可信)` | `run_guard_selftest.py`：用故意违规样例证明守卫不是空壳（7 拦下 + 7 放行 + 1 组合），并核对**覆盖集**：常量表里每个挂载点都必须被守卫认得 + 点名清单与钉住的一致 |
| 8 | `静态守卫扫描 apps/` | `toolkit_guard.py` |
| 9 | `pyflakes (未定义名 / 未用导入 / 重复定义)` | 覆盖面 = **全部活代码**：库层全部模块（含 `toolkit_version.py` / `toolkit_guard.py` / **`toolkit_plugin_ui.py`**）+ `stalker_toolkit.py` + 六个 App + 引擎 + `build.py` / `build_gui.py` + `cross_validate.py` / `download_ffmpeg.py` + 全部 `run_*.py`（含只做静态覆盖、不在 CI 里跑的 `run_inject_layout_locks.py`）。当前 **exit 0（干净）**。豁免清单**已清空**：`toolkit.py` 原先靠整文件豁免遮住"导入但文件内未使用"的告警，现在它用模块级 `__all__`（146 名）显式写下对外契约、零告警，豁免不再需要 —— 豁免名单里任何一个名字都会把该文件的**全部**告警（含真实未定义名）一起吞掉，空着更安全。`apps/_bootstrap.py` **同样不放豁免**：它用模块级 `__all__`（31 个转发名）显式声明转发清单，pyflakes 视 `__all__` 中的名字为已使用、零告警；不豁免反而更好——将来往里加名字却忘了同步 `__all__`，这一步会立刻报出来。`stalker_toolkit.py` **也不豁免**——它曾整文件豁免，结果把 40 个死导入一起藏住了。仓库自带探针**缺件即 FAIL**（原先记 SKIP = 把门禁文件删掉就算绿灯），只有闭源插件与外部 `converter.exe` 缺失才 SKIP。`pyflakes` 未安装时 SKIP |
| 10 | `run_functional_probe (功能完整性端到端)` | **9 组**回归锁：文本提取 / XML 比较 / 编码转换 / 引擎六格式真实往返 / 汉化包生成 / 编码判定 / 任务壳失败路径 / 视频转换（真实 ffmpeg）/ **复杂编码环境**；全部在临时目录内。第 8 组需要 `ffmpeg` / `ffprobe`，缺失时该组 SKIP。第 9 组是"受约束的复杂编码环境"：**22 个文件 × 4 种组合**（源=auto/手动1251 × 原地/输出新目录）必须全部正确 —— 覆盖声明与字节不符（两个方向）、无声明、只有 version、UTF-8 BOM、纯 ASCII、单引号/大写/空格/前导空白、多根、属性含西里尔、CRLF、嵌套目录；约束是**多字节只用 UTF-8、单字节只用 windows-1251**（那两个例外基本遇不到，为它们写代码必然冗余，所以不覆盖、也不需要任何阈值机制） |
| 11 | `run_build_probe (构建器与版本号)` | 版本模块解析·组合·四段推导·写回（临时副本）+ `build.py` 参数 + `build_gui` 无头构造 |
| 12 | `run_hub_probe (Hub 级框架集成)` | 按 Hub 真实装配顺序：6 内置栏目 + 插件栏目 + 插件贡献在同一运行态成立；另含「真实 `plugins/` 目录可无损扫描（无加载错误）」一条。探针插件同样写进本进程独有的临时目录。**第 [6] 段是启动绘制契约 6 条**（白屏 / 可点击时间，见 §3.3）：`paint_now` 只走 `update_idletasks`、`paint_startup` 建提示标签并经 `paint_now` 落笔、AST 上 `paint_startup` 早于插件扫描与 `build_hub`、`rebuild` 走 `build_tabs` 且透传 `defer_rest`、`apply_theme` 不在装配循环里、外壳的 `paint_now` 早于 `rebuild`；分帧调度另用**假 root** 跑真 `build_tabs`（首栏目同步 / 其余每次 `after` 一个 / `on_done` 只调一次 / `defer_rest=False` 与旧实现等价）。**第 [7] 段是分隔条与布局契约**（见 §3.4）：minsize 两趟收敛、`_panes()` 必须是控件、
`refresh_children` 触达 `CanvasTree._draw`、合并 motion（拖动期不同步改几何）/松手落到目标
且**不留冻结**、`LIVE_DRAG` 三档合法且 freeze 档"按下冻结重窗格、松手解冻（只冻重的那一侧）"、
真实 `event_generate` 事件路径（绑定未丢、`break` 生效、普通点击不被吞）、AST 上栏目页
`pack_propagate(False)` 且两栏带 `minsize` |
| 13 | `run_engine_compat_probe (旧调用形状兼容)` | 缺 `size_comp` / `use_lzhuf` 的历史调用必须仍解出正确字节 |
| 14 | `run_ui_smoke (界面冒烟，需桌面与 ffmpeg)` | Hub 装配六个工具 + 插件工具、汉化包勾选框的控件类/文案、编码判定、XML 解析、cfgxml、ffmpeg/ffprobe 发现。**`--fast` 跳过并记清单**；其余档缺桌面记 SKIP（`--release` 记 FAIL），退出码非 0 一律 FAIL |
| — | `cleanup()` | 清活代码 `__pycache__`、`temp/build`、`temp/toolkit_*` / `temp/dsh_*`，并顺手清 `cross_validate_out/` 与 `cross_validate_samples/`（**仅供清掉历史残留**——现在的 `cross_validate` 与各探针都在自己的临时目录里工作，不在仓库落文件） |
| — | `uncovered_report()` | 收尾打印**本次未覆盖**清单（SKIP ≠ PASS）。`--release` 档只要清单非空即整体 FAIL |
| — | `RESULT: PASS/FAIL` | 退出码 0 / 1 |

**三档门禁（用户裁定 2026-09-12，方案 3）**：`--fast`（公开 CI：跳过需外部前提的步骤，
其余全跑，清单照记）→ 默认（本地全量：缺前提 SKIP + 清单）→ `--release`（发版门禁：
缺前提即 FAIL，且收尾要求清单为空）。`--fast` 与 `--release` 同时给**报错**——两者对
"缺前提算不算失败"的判定相反，静默取其一会让调用者以为拿到了另一档。

**`logs\` 由 CI 有意不清理，改由"版本阶段"决定保留**：`cleanup()` 只删**测试自己产生的**产物，
`runtime_<时刻>.log` 是排障依据（历史行为曾"跑一次 CI 就清空 runtime.log"，属已修缺陷）。
每次启动一个新文件，所以"这一次运行做了什么"永远对应一个独立文件，不必在混杂内容里找边界。
保留策略（用户裁定 2026-09-12）：

| 版本 | 保留 | 理由 |
|---|---|---|
| **预发布版**（`APP_PRERELEASE` 非空：ALPHA/BETA/RC） | **不自动清理** | 测试期一次会生成大量日志，删早了没法回看失败现场；下限由人工把握 |
| **正式版**（`APP_PRERELEASE == ""`） | 自动保留最近 **100** 个 | 长期运行不积压 |

执行点：`toolkit_base` 导入期（每个入口都导入它，所以"每次开软件"必然走到）
按 `APP_PRERELEASE` 设策略，再调一次 `toolkit_log.cleanup_startup_logs()`（同一进程幂等）。
只删文件名精确匹配 `runtime_YYYYMMDD_HHMMSS.log` 的文件 —— Hub 导出的 `log_<时刻>.txt`
是用户主动产出的快照，**不在**清理范围内；本次会话的日志文件永远保留（即使时钟回拨排不到最新），
且给它预留一个名额（所以目录稳定在 ≤100，不是 101）。
排障/发版前验证可用环境变量 `STALKER_LOG_KEEP` 覆盖：`none` 关闭清理、数字改上限
（仓库里跑的是预发布版，这个开关让"正式版那条路径"不必改常量就能验）。

**行时间戳带毫秒**（`[2026-09-12 15:36:08.412]`，2026-09-12 起）：原先只到秒，而"窗口就绪 /
插件扫描完成 / 六个栏目装配"这些相位会挤在同一秒里 —— 用户报"启动卡"时，日志分不出是哪一段，
只能像那次一样靠录屏逐帧反推。毫秒由**同一个 `datetime` 对象**取出（不是两次 `time` 调用拼起来，
后者会在一秒边界拼出 `.412` 配下一秒的秒数）。`run_functional_probe` 对此上锁。

**可并发运行**：`run_ext_probe.py` 与 `run_hub_probe.py` 把探针插件写进各自进程独占的临时目录
（`ext_probe_plugins_*` / `hub_probe_plugins_*`），不再写仓库 `plugins/`——此前两者都往
`plugins/zz_*.py` 写，并发时会互相覆盖，并把对方的插件算进"插件栏目"计数。

### 7.3 其余探针

| 脚本 | 用途 |
|---|---|
| `run_ui_smoke.py` | 需桌面的 smoke：六工具构造 + 插件栏目 + 编码检测 + `parse_file` ID 统计 + cfgxml 解析 + ffmpeg/ffprobe 发现。**已纳入 `run_ci.py`**：`--fast` 档跳过并记入"未覆盖"清单，默认档缺桌面记 SKIP，`--release` 档缺桌面即 FAIL；退出码非 0 一律 FAIL |
| `run_gui_text_audit.py` | 界面文案 / 标点审查（只读）：扫 `messagebox` / `tool_text` / `text=` 里的长串与标点。**没有 pass/fail 语义**，因此只进 pyflakes 名单做静态覆盖，不作为 CI 步骤（原名 `_gui_text_audit.py`：下划线前缀 + 文档/CI 全无登记，2026-09-12 改名并登记） |
| `run_inject_layout_locks.py` | **故障注入验证器（手动跑，唯一会临时改写源文件的脚本）**：把面板迁移与主题映射的 **12** 条锁各自打回"错的写法"，跑对应探针（Qt 侧 `run_qt_pilot_probe.py` / Tk 侧 `run_ext_probe.py`）断言目标锁变红，`finally` 还原并核对 sha256。**故意不作为 CI 步骤**（会改真实源文件），但**在 pyflakes 静态名单里** —— 否则 `run_app_probe` 的"不许有游离 `run_*.py`"防腐锁会红 |
| `run_deadcode_audit.py` | 死代码审计（未用导入 / 未被引用函数·常量 / 空实现 / 重复实现候选）。**退出码恒为 0**——这是审计不是闸门。同样**不在 `run_ci.py` 里**。<br>**已知 / 易误报项**（2026-09-12 复核实测）：① 未用导入 **0 处**（`toolkit.py` 有了模块级 `__all__`，"导入但未使用"已不再是告警；旧文写的 ~131 已过期）；② 空实现 1 处 = `apps/fs_app.py::_db_click`（**有意为空**，作用是拦掉 `CanvasTree` 在无 `on_click` 时"点叶子就切勾选"的默认行为，见 `toolkit_widgets.py` 的点击分支，**不要为了审计好看而给它加代码**）；③ 重名 **28 组**基本都是各文件同名但语义不同的内部辅助（`main` / `check` / `_build_ui` / `work` / `apply` …），非重复实现；真正要处理的重复实现得靠人工核查（例如 2026-09-12 修掉的 `xml_compare_app.decode_file` —— 它**遮蔽**了公共层同名函数）；④ "注释代码" 2 处（`toolkit_base.py` / `font_pack_app.py`）**都是它的正则误报**（把以 `import` / `tk.` 开头的**中文说明性注释**当成了代码残骸），别去"清理"；⑤ **它看不到 `temp/`**（`SKIP_DIRS` 含 `temp`）——历史上最大的一处重构残留（旧 `fs_app` 副本 919 行）恰好藏在那里，2026-09-12 已移入 `backup/pre_modularization/` |
| `download_ffmpeg.py` | 检测并自动下载 `ffmpeg.exe` / `ffprobe.exe` |
| `cross_validate.py` | 与外部 `converter.exe`（cv）的**DB 双向交叉校验**，**六种格式全覆盖**（xdb / 2947ru / 2947ww / 2945 / 2215 / 11xx）× 三个方向：<br>**A** cv 封 → 工具解（工具读得懂官方产物）、**B** 工具封 → cv 解（官方认工具产物）、**C** 工具封 → 工具解（自洽）。<br>**源集合含目录条目**（`(path, b"", True)`，path **不带**尾斜杠，引擎的 build_header 自己补 `\`）—— 这是关键覆盖：旧脚本只喂文件，于是"目录条目"这条路径从未被交叉验证过，而 cv 恰恰只在处理目录条目时才崩（11xx）。<br>**内容比对是逐字节**（`first_byte_diff`，2026-09-12 由哈希口径订正：用户要求"字节级相同"，且不一致时要给出**首异下标 + 两侧字节值 + 双方长度**；哈希给不出位置）。<br>**文件名代码页**：cv 用 Win32 `GetACP()`（本机 936）而不是 `locale.getpreferredencoding()`（外部审计实测后者在别的机器上返回 utf-8 → 会把"cv 写得成的合法乱码名"预测成写不成 → **误报 FAIL**）。预测走 `MultiByteToWideChar(CP_ACP)`（不是 Python 的 `errors="ignore"`：无效前导字节在 API 里是私用区字符 U+F8F5）；判定收敛在纯函数 `classify_cv_name()`，由 `run_functional_probe` 第 [10] 段上锁。<br>**两个西里尔样本都测**：一个预测名含 `?`（Win32 非法字符 → cv 建不出文件 → SKIP 并如实归因）、一个预测名是**合法乱码名**（cv 会照写 → SKIP）。只测前者会让"预测名算错"碰巧躲过（旧实现就是这样一直没暴露）。<br>**cv 的两个封包侧规范化行为**（期望值必须照此校准，否则误报）：① **路径全部转小写**（故方向 A 忽略大小写比对；方向 B 里 cv 解工具包会保留原大小写，说明转小写是 cv 行为、不是引擎丢信息）；② **只给"直接含文件的目录"写条目**，中间层目录不写（故方向 A 不要求中间层目录条目，但要求叶子目录条目齐全）。<br>**cv 能力实测**：xdb/2947ru/2947ww 能封能解；2945/2215/11xx **不能封**（`-pack` 返回 0 但不产出文件，只看 returncode 会误判成功）；11xx 解**含目录条目**的包时栈溢出 `0xC00000FD`，故 A/B 记为 SKIP(cv 缺陷)，另用"不含目录条目的 11xx LZHUF 载荷包"覆盖 cv 侧 11xx 路径。<br>**PASS / FAIL / SKIP 严格分开、末尾给计数，只有 FAIL 才非零退出**（SKIP 一律附原因，避免假绿）。**运行目录完全隔离**：样例与输出都在 `tempfile.mkdtemp(prefix="toolkit_xval_")` 下，跑完自清，因此多个 CI 可并发，且不在仓库里落任何文件。当前实测 **PASS 18 / FAIL 0 / SKIP 6**（双文件名样本后从 16/0/4 增加） |

### 7.4 GitHub Actions

`.github/workflows/ci.yml`：单 job `core`，`windows-latest`，`timeout-minutes: 20`，
Python **3.12**，唯一命令 `python run_ci.py --fast`（push 到 `main` 与所有 PR）。

**注意覆盖边界**：CI 跑的是 `--fast`，因此 **`cross_validate` 一步被跳过**；
`run_ui_smoke.py` 与 `run_deadcode_audit.py` 从来不在 `run_ci.py` 的步骤里，需要本地单独跑
（前者的桌面前提在 CI 上也不成立）。这三处是本仓库测试覆盖的**已知边界**，不是遗漏。

---

## 八、已完成的拆分（不再"进行中"）

方案 A 的分层拆分**已全部落地**，主干加载顺序固定为 **日志 → 主题 → 插件 → 组件**：

1. `toolkit_log.py` —— 日志最先加载，`summary` / `detail` 两级。✅
2. `toolkit_base.py` —— 底层基础。✅
3. `toolkit_theme.py` —— 主题收敛为单文件，新增主题只加数据。✅
4. `toolkit_widgets.py` —— 通用组件统一管理，供插件复用。✅
5. `toolkit_textio.py` / `toolkit_plugins.py` —— IO 纯函数与插件宿主各自成文件。✅
6. `toolkit.py` —— 退化为纯 re-export 协调层，既有导入 100% 兼容。✅
7. `toolkit_platform.py` / `toolkit_constants.py` / `toolkit_version.py` / `toolkit_guard.py`
   —— 平台样板、业务常量、版本号、静态守卫各自成文件。✅
8. `apps/xml_modes.py` —— 内置 XML 比较模式改为**声明式贡献**，与插件走同一张表。✅
9. App 日志迁移 —— Hub 的 `attach_log()`（按控件层级上溯、递归隐藏子工具日志面板、
   改写 `app._log` 造成 tag 丢失）**已整段删除**，`rebuild()` 现在只做 `factory(tab)`。✅
10. 六个 App 与插件栏目使用**完全一致**的 App 契约（见第十节）。✅

---

## 九、当前仍然存在的已知限制

只列**能在代码或注释里找到依据**的。已修复项不在此列。

1. **LZHUF 单例不可重入（已知且接受）**：`stalker_fs.lzhuf` 是进程级有状态单例，DLL 内部
   同样是 file-scope static，并发调用会互相污染。现状是在单例上包一层 `_lzhuf_lock`
   （`threading.RLock`）把访问**串行化**，DLL 与纯 Python 两条路径都覆盖，调用点无需改动。
   代价是 LZHUF 调用串行（单次约 830 KB 编码 ~127 ms）；彻底可重入需把 C 侧 static 收进
   上下文结构体重编 DLL——**留待 2.0**。
2. **`cross_validate.py` 依赖外部 `converter.exe`**：默认路径是本机
   `E:\Software\Games\STALKER\Localization\Tools\Tool\Stalker_Unpacker_2017\converter.exe`，
   但**可用环境变量 `STALKER_CONVERTER_EXE` 覆盖**（`run_ci.py` 解析后回传给子进程，
   两处判定不会不一致）。缺件时按档位处理（用户裁定 2026-09-12，方案 3「两级门禁」）：
   `--fast` 跳过并记入"未覆盖"清单；默认档 SKIP + 记清单；**`--release` 判 FAIL**，
   且 `--release` 档只要清单非空即整体不通过。这条的代价是公开 CI 永远不覆盖
   交叉校验（runner 上没有那个工具），收益是公开 CI 的"红"始终意味着代码有问题，
   而不是"这台机器不是作者的电脑"。该脚本运行目录已隔离（见 7.3），**不在仓库落文件**。
   `run_ui_smoke.py` 同理（缺桌面/ffmpeg），但**`run_ui_smoke` 连默认档都只认
   "无法创建 Tk 根窗口"这一种 SKIP**，其余退出码非 0 一律 FAIL。
3. **残留的本机绝对路径**：除上面第 2 条外，还有
   - `file_system/stalker_fs.py`：SquashFS 工具的一个兜底搜索路径；
   - `apps/video_ogm_app.py`：`find_ffmpeg` 的若干候选目录（`C:\ffmpeg\bin`、
     `C:\Program Files\ffmpeg\bin`、`E:\Software\Tools\FFmpeg\*\bin` 等，属**候选**而非唯一路径）；
   - `apps/font_pack_app.py`：字体文件对话框的初始目录兜底 `C:\Windows\Fonts`
     （正常路径取自 `toolkit_platform.system_font_dirs()`）。
4. **未抽公共 App 基类**：迁移后各 App 的共享样板只剩 `root = parent` / `_make_pump` /
   构建 UI 约几行，而六个 App 结构差异较大（`ConvertApp` 是 `ttk.Frame` 子类，其余为普通类），
   加一层继承收益不抵复杂度——这是**决定**，不是欠债。
5. **`context` 槽只接了文件系统工具**：其余组件要开该槽，需由该组件指定"主内容控件"后调用
   `attach_plugin_context_menu(widget, host, app=…)`（helper 已就绪）。
6. **测试口径的固有缺口**：`run_ci.py` 的"import modules"只导入模块，**方法体内的
   `NameError` / 隐式初始化抓不到**。因此必须配合构造级与入口级探针
   （`run_app_probe.py`、`run_functional_probe.py`、`run_hub_probe.py`）——本仓库已多次
   踩过"闸门全绿但功能已断"。这是**保留多层探针的理由**。
7. **启动仍有的两项代价（明知而未修，理由在此）**：
   - **映射到首绘之间可能还有 1 帧白**（录屏 3 次：NONE/NONE/1 帧）：Windows 先用窗口类
     背景刷（`COLOR_WINDOW`）填客户区，Tk 才开始画。彻底消除只能"先隐身再显示"，代价是
     窗口晚约 0.4 s 出现、期间用户什么都看不到（`-alpha` 恢复失败还会让窗口永远不可见），
     收益 ≈ 33 ms，不划算。
   - **分帧装配期间每个栏目各占一帧**，单帧最长 ~400 ms（视频转换，含 ffmpeg/ffprobe 解析
     334 ms），期间界面不响应；但用户已经能看见窗口并在栏目之间操作，比"装完才进 mainloop"
     的 2 s 好得多。要再降只能把单个栏目的构建再切片（收益递减、复杂度陡增）。
8. **分隔条跟手是"三档取一"，不是免费的（见 §3.4）**：Tk 每个控件一个 HWND，改尺寸就要
   重排/重绘整棵可见树。**含重绘**的实测：逐事件实时 108 ms/次拖动风暴（≈12 fps）、
   合并 motion + 冻结重窗格重绘 45 ms（≈30 fps，现默认）、只挪预览线 4.5 ms（拖动期）。
   也就是说：默认档下**重页面内容在拖动期间不重绘**（松手补齐），换来窗格边框与分隔条
   以 ~30 fps 跟手。想要"内容也逐帧跟手又不卡"，在 Tk 上做不到（要么把整页控件数降到
   几十个，要么换 UI 工具包）——`LIVE_DRAG` 三档都留着，改一个常量即可切换。
9. **拖窗口边框仍然慢（每步 113~123 ms）**：已做的是把 Configure 去抖（`_clamp`、
   `CanvasTree._draw` 从"每个 Configure 一次"改成"最后一次之后 60~120 ms 一次"），
   从 128~176 ms 降到 113~123 ms。剩下的是**当前选中页几十个控件的 Win32 重绘**（冻结该页
   可再降到 65~72 ms，但内容在拖动期间不刷新）：属 Tk/Win32 架构成本，非本工程算法或
   Python 层（Python 层约 0.25 ms/步）。要不要把"拖边框期间冻结当前页重绘"也打开是一个
   **视觉取舍**，留给用户定。
9. **pane 的 minsize 是本工程自己实现的**：`ttk.Panedwindow` 的 pane 只有 `-weight`，没有
   `-minsize`（`pane(..., minsize=)` 直接 `TclError`）。`SplitPane` 用 `_clamp()` 在窗口尺寸
   变化与拖动结束后收敛；**总空间连各 pane 最小值之和都放不下时，让后面的 pane 先挨饿**
   （主工作区通常在前）。因此极小窗口下仍可能出现某栏偏小，这是有意的优先级。

### 9.1 已修、但值得留一笔的三类历史缺陷（外部审计要求备案）

这三类**都已修复**，列在这里不是为了记功，而是为了解释"为什么这个仓库养着多层探针"——
它们有共同特征：**不崩溃、不报错、日志还显示成功**，任何"跑起来没崩"的检查都抓不到。

| 曾存在的缺陷 | 症状（当时用户能看到的） | 为什么普通检查抓不到 |
|---|---|---|
| `extract_chars` 对 **GBK 源静默丢字**（`decode("utf-8-sig", "ignore")`） | 中文汉化包的字库里**没有那些字** → 游戏内空白，而日志一行告警都没有 | `errors="ignore"` 把"丢数据"变成**不可观测**；要抓它必须**用不在内置集里的字符**做端到端断言 |
| `check()` **丢弃 `False`**（`check("x", lambda: a == b)`） | 275 条断言里 **49 条永不失败**；把 `check` 改真后立刻暴露 10 条真失败 | 纯布尔表达式被静默当作通过——**断言空转**，退出码仍为 0 |
| `is_package_name` **家族匹配缺失**（不认 `.db0` / `.sq_base`） | 部分包不被识别为包 | 判定散在多处、各自维护一份名单，漂移没有任何症状 |

共同教训（也是本仓库"不静默 / 锁必须能被注入证明 / 新挂载点由常量表派生"这些规矩的来源）：
**假绿比漏报更贵**——漏报会被用户看见，假绿会让所有人看不见。

---

## 十、App 统一契约

六个内置 App 与插件注册的 Hub 栏目，**使用完全相同的契约**：

```python
app = App(parent)        # parent 是 Hub 在 Notebook 里创建的 Tab Frame
                         # 形式上即 callable(parent) -> object
```

**注意：全仓库没有任何模块级 `def build(parent)`。** Hub 侧的装配代码是
`stalker_toolkit.rebuild()` 里的一行：

```python
apps[label] = factory(tab)
```

而 `factory` 就是 `BUILTIN_TOOLS` 里放的**类本身**（`("文件系统", FSToolApp)` …），
插件侧对应 `register_tool(name, builder)` 的 `builder`（`callable(parent) -> object`）。
因此真实契约是 **`App(parent)`**，不是 `build(parent)`——旧文档里的 `build(parent)`
是一个并不存在的符号。

App 侧的三条硬性约定：

1. **不自建根窗口**：没有 `master=None` 分支、不建 `tk.Tk()`、不设 `title/geometry/minsize`。
   工具只能从 Hub 启动。
2. **不碰主题**：不调 `apply_theme()` / `apply_tk_defaults()`。宿主模式下主题由 Hub 统一应用，
   避免依赖进程级 `CURRENT_MODE` 的初始化顺序。
3. **不自建日志面板**：不调 `log_section()`。日志直接走全局两级通道：

   ```python
   from toolkit import log_summary, log_detail
   log_summary(msg, tag)   # summary：进 Hub 日志栏 + 落盘
   log_detail(msg, tag)    # detail：只落盘，导出日志时全量输出
   ```

   需要线程安全地更新 UI 时，用 `self._ui = _make_pump(parent)`（长任务用 `TaskRunner`）。

收益：Hub 不再需要按控件层级上溯去改写子工具的日志引用，内置工具与插件栏目不再有两套契约。

> 需要通用控件时优先取 `toolkit` / `api.widgets`，不要自造同类控件；颜色与字体一律经
> 主题层（`color("角色")` / `T["font*"]`）取得，否则 `toolkit_guard.py` 会在 CI 里拦下。

---

## 十一、Qt 试点（`qt_pilot.py`）—— 性能路线的验证件

**背景**：性能评估（见 UI 回执第九节）测出 Tk 的定律 —— **每步 ≈ 17 ms 地板 + 1.4 ms × 可见控件数**
（窗口 1920x1290 / 2.5 Mpx），真实栏目页 40~70 个控件 → 80~120 ms/步（8~12 fps）；
要在 16 ms 内跑完，Tk 只允许约 0 个控件。根因是"每个控件一个 Win32 子窗口 + 每次尺寸变化逐窗口重绘"。
因此"内容实时跟手"在 Tk 里做不到，唯一方向是**单表面渲染**的工具包。

**试点范围（刻意最小、可回退）**：

| 项 | 内容 |
|---|---|
| 文件 | `qt_pilot.py`（试点窗口，独立运行）、`run_qt_pilot_probe.py`（验收） |
| 页面 | **只做文件系统页**：与 Tk 版**同清单**（格式/自动检测/解包选中/批量解包/输入·输出/进度·状态/数据包列表六按钮/包内文件/封包区/日志栏） |
| 引擎 | **同一份** `file_system/stalker_fs`：`unpack_db` / `pack_db` / `extract_file` / `fmt_key` / `FORMATS` |
| 未接 | 插件槽（`PLUGINS.md` 契约）、主题系统、`TaskRunner`、Hub 装配、打包 |
| Tk 路径 | **一行未动**；`run_ci.py` 的试步骤缺 PySide6 时按外部前提 SKIP，不影响 Tk 门禁 |

**实测（同机、空闲态；口径与 Tk 侧一致：每帧真重排 + 真绘制）**：

| 操作 | Tk（文件系统页） | **Qt 试点** |
|---|---|---|
| 实时拖动分隔条（内容逐帧重排） | 80~118 ms/步（8~12 fps） | **12~15 ms/步（≈70~85 fps）** |
| 窗口缩放一步 | 113~123 ms | **30~35 ms** |

**写成探针的不变量**（`run_qt_pilot_probe.py`，现 60 条：试点本体 22 条 + [8] 插件槽 19 条 +
[9] 主题映射与持久化 19 条）：①**隔离** —— `import qt_pilot` 后
`sys.modules` 里不得出现 `tkinter`/`toolkit`（两条路互不干扰，子进程实测）；②**同清单** —— 顶部/数据包/
包内文件/封包全部按钮 + 三个面板 + 三棵树 + 进度·状态·目录行 + 日志栏齐全；
③**扫描规则与 Tk 版逐字一致**（最后一个点起 `.db`/`.sq`，因此 `xxx.xdb` 不收 —— 判定表 10 个样本）；
④**同引擎** —— 源码必须调用 `extract_file` 且不得手搓偏移（试点第一版就是手搓偏移导致 0/5 不一致）；
⑤**真实往返** —— 临时目录内 pack→扫描→加载→解包逐字节一致→重封包逐字节一致（8 条）；
⑥**线程纪律** —— `work()` 里只 `emit`，不得直接碰控件（AST 检查）；⑦性能兜底阈值 + 窗口逻辑尺寸与 Tk 版一致。

**迁移待办（试点验证通过后再逐项做）**：~~插件槽契约~~（**已完成**，见 11.1）、
~~主题（色板/字体 → Qt 样式表）~~（**映射已完成**，见 11.3；**持久化未做**，原因写在那一节）、
`TaskRunner` 的等价物（QThread + 信号已在本试点验证）、Hub 装配与 Tab、日志栏统一、
`CanvasTree` 在 Qt 里的等价物（`QTreeView` + model 天然虚拟化）、打包（PyInstaller + PySide6，
体积实测 +42 MB）、以及探针/锁的双轨与切换开关。

**风险与取舍（如实记录）**：① PySide6 会显著增大发行包（**实测净增 +42 MB / +13%**，见下）；
② 六页 UI 需要重写（引擎与业务逻辑可留）；③ 插件是第三方契约，迁移要给出兼容层或明确破坏性变更；
④ Qt 的 `QTreeView` 若不设虚拟化同样会慢 —— **已用真实 5242 条目压测排除**（见下）。

**打包体积（实测，2026-09-12 **改为可复跑**）**：`python build_qt_pilot.py` —— 一条命令做完
"构建 → 裁剪 → 扫 Tcl/Tk → 跑冻结 exe 自检"，产物在 `qt_pilot_dist/QtPilot/`（已入 `.gitignore`）。
**实测：未裁剪 95.3 MB（200 文件）→ 裁剪后 61.9 MB（101 文件）**，裁剪项与释放量都是运行时量出来的：

| 裁剪项 | 释放 | 为什么可以删 |
|---|---|---|
| `PySide6/opengl32sw.dll` | 19.68 MB | Qt 的软件 OpenGL 兜底；试点只画控件 |
| `PySide6/translations` | 6.44 MB | Qt 自带翻译；界面文案是我们自己的中文 |
| `libcrypto-3.dll` | 5.95 MB | OpenSSL；试点不联网 |
| `libssl-3.dll` | 1.27 MB | 同上 |

> 早先那个"未裁剪 94.9 MB → **68.7 MB**"是**临时手敲命令**打出来的一次性数字（命令没留下、
> 产物也没留）。现在 61.9 MB 更低，是因为构建期多了 `--exclude-module tkinter/_tkinter/
> tkinterdnd2/PIL` 并把 `file_system` 作为 data 打进包 —— 两处都写进了脚本，谁都能复跑。
> 与 Tk 发行包的量级对比结论不变（Qt 侧几十 MB vs Tcl/Tk 3.6 MB），但**引用请用可复跑的这组数字**。

**冻结产物的验证（`run_qt_build_probe.py`，11 条，已进 `run_ci.py` 的本地/发版档）**：
① 构建脚本能按文档跑通并产出 exe；② 冻结树里 **0 个 Tcl/Tk 产物**；
③ **正对照** —— 同一套判据用在 Tk 发行包上必须**扫得出**（实测扫出 7 项：
`_tcl_data` / `_tk_data` / `_tkinter.pyd` / `tcl8` / `tcl86t.dll` / `tk86t.dll` …），
否则 ② 的"0 个"可能只是检测器失灵（**这正是"永远为真的锁"的典型形态**）；
④ 冻结 exe `--selftest` = `PASS 8 FAIL 0`（引擎真实往返在冻结包里跑通）；
⑤ 冻结 exe `--themecheck` `ok=8 bad=0 tkinter=False`（**冻结态也没把 Tk 拉进进程**）；
⑥ 冻结 exe `--bench` 能开真窗跑完（裁剪后 `qwindows.dll` 那条路仍可用）；
⑦ 裁剪清单每项都真的删掉了、且没删掉必需项（`platforms/qwindows.dll`、`platforms/qoffscreen.dll`、
Qt6Core/Qt6Widgets/Qt6Gui）。

**冻结包的中文输出不能当契约**：冻结 exe 的 stdout 编码取决于控制台代码页，
中文行在别的进程里捕获时会是乱码（实测如此）。所以 `--themecheck` 末尾另打一行
**纯 ASCII** 的 `THEMECHECK ok=8 bad=0 tkinter=False`，验证脚本只解析这一行。
另：`run_frozen()` 会**清掉** `TCL_LIBRARY/TK_LIBRARY/PYTHONHOME/PYTHONPATH` 再跑 ——
否则**本机装的** Tcl/Tk 或源码目录会掩盖产物自己的问题（测的就成了"这台机器"而不是"这个包"）。

**虚拟化压测（真实 `gamedata.db_base`：5375 条目 / 5242 文件）**：Qt 侧拖动/缩放成本与行数几乎无关
（194→5242 行：拖动 8~11 ms、缩放 17~23 ms）；自定义 model 填充仅 0.2 ms（`QTreeWidget` 11.1 ms、
`QStandardItemModel` 17.9 ms）。同结构下 Tk 为 **37.9~39.0 ms/步** → 即使控件极少，Qt 仍快 3.5~4.6×。

### 11.1 插件槽兼容层（迁移里唯一的第三方契约风险）

**契约审计**：`PluginManager` 的注册点共有 11 个，其中**只有 3 处**与具体工具包耦合 ——
`api.widgets`（直接暴露 `toolkit_widgets`）、`register_panel(...)` 与 `register_tool(...)` 的
`builder(parent)`；其余（解密器 / 格式 / 命令 / 菜单项 / 下拉条目 / 新建下拉 / 比较模式）都是
**宿主渲染的纯数据 + 回调**。

**契约扩展（纯新增、向后兼容）**：

| 字段 | 语义 |
|---|---|
| `api.backend` | `"tk"` / `"qt"`，插件据此分支（不分支也行，见下） |
| `api.ui` | 后端无关的控件工厂，方法面固定 **14** 个：造控件 `label/button/row/checkbox/entry/text/combo/pack` + 改控件/取输入 `set_text/text_view/alive/ask_yes_no/ask_open_file/ask_save_file` |

* Tk 实现：`toolkit_plugin_ui.TkUiFactory`（缺省，既有插件行为不变）；
* Qt 实现：`qt_pilot_plugins.QtUiFactory`（同名同参）；
* 注入方式：`PluginManager(..., ui_factory=...)` **按实例**保存（不是模块级全局）——
  同一个进程里 Tk 宿主与 Qt 宿主可以各持一个实例而互不污染。

后 6 个方法是**迁移 `engine_utf8_patch` 时按实测补的**：插件真正需要的除了"造控件"，还有
"改标签文字 / 往只读视图写报告 / 判控件是否还活着 / 三个标准对话框"。只给前 8 个时，
插件仍得自己 `box.configure(...)`、`filedialog.askopenfilename(...)` —— 那还是 Tk 专有。

**实测（真实插件）**：

| 插件 | 结果 |
|---|---|
| `nlc_sqfs.py`（**闭源第三方**，0 处 Tk 构造） | **原样可用**：解密器在 Qt 宿主里正常注册（`decryptors == 1`） |
| `engine_utf8_patch.py`（我方实验件，**已迁移**） | 面板在 Qt 宿主里 `panel/ok` 真建出来：3 个动作按钮点击后确实进 `identify/verify/apply`、1 个只读 `QPlainTextEdit`、按钮同一水平行、外层竖直顺序与 Tk 一致 |
| 只用 Tk 的 builder（**反例样例**） | 静态预检抓不到 lambda 里的 Tk 时，由"运行期错误形状判定"兜住 → 如实上报 `skip(tk-only)`，**不崩、不算 fail** |
| 双后端样例（用 `api.ui` 写一遍） | Qt 侧建出按钮（`backend='qt'`）、**Tk 侧（独立进程）也建出按钮**（`backend='tk'`） |

**Qt 侧语义差（试点踩到并已解决，两个都写进了锁）**：

1. Qt 里创建控件**不会自动进布局**（Tk 靠 `pack`）。`QtUiFactory` 因此采用"**创建即入布局**"，
   `pack()` 退化为对齐提示 —— 同一份按 Tk 风格写的插件代码在两个后端都能显示。
2. **容器的默认方向必须与 Tk 的 `pack()` 默认一致（`top`，即竖直）**。第一版把 `row()`
   造成 `QHBoxLayout`，于是"按钮行 / 路径标签 / 结果框"这三个兄弟在 Qt 上会横着排、
   在 Tk 上是竖着排 —— **同一份插件代码、两个后端的布局不一样**，而这恰恰是兼容层要保证的东西。
   修法：`row()` = 竖直容器；`pack(side="left"/"right")` 把控件从竖直序列摘出来、移进
   同一个惰性创建的**水平行子容器**（`_hrow`），于是 `side="left"` 的语义两边一致。
   注入验证抓过一次"只查控件类型不查布局方向"的弱锁（见 §11.2）。

**迁移成本（实测，基线 = `builds/build_18` 里的迁移前副本，sha `6950b10e`）**：

| 指标 | 迁移前 | 迁移后 |
|---|---|---|
| `plugins/engine_utf8_patch.py` 行数 / 字节 | 1470 / 72631 | **1452 / 72321**（−18 行 / −310 B） |
| Tk 控件构造调用点 | 9（`ttk.Frame`×3、`ttk.Button`×2、`ttk.Label`×2、`ttk.Scrollbar`×1、`tk.Text`×1） | **0** |
| Tk 布局/改控件调用点 | `.pack(`×11、`.configure(`×8、`.delete/.insert(`×3 | **0**（改为 7 处 `ui.pack(`） |
| Tk 对话框调用点 | `filedialog`×2、`messagebox`×1 | **0**（改为 `ui.ask_open_file/ask_save_file/ask_yes_no`） |
| Tk 专有辅助函数 | `_dialog_parent()`（12 行，`winfo_toplevel`/`_default_root`） | **删除**（工厂内 `_toplevel()` 统一归一） |
| `api.ui` 调用点 | 0 | **16** |

即：**9 处构造 + 25 处布局/改控件 + 3 处对话框 + 1 个辅助函数 → 16 处 `api.ui`**，净 −18 行。
迁移是**纯机械替换**：面板的控件结构（3 个动作按钮 + 只读结果框、`side="bottom"` 的底部区域、
注册的 3 个命令与 toolbar 挂载点）**一个都没动** —— `run_ext_probe` 原有的 10 条锁迁移前后**一字未改**
（迁移后另**新增** 1 条"点击真的进对应流程"，正是为了补上"结构没变 ≠ 接线没接错"这一格）。

**锁**：`run_hub_probe.py` 新增 1 条（Tk 侧 `api.backend == 'tk'` 且 `api.ui` 方法面完整、`api.widgets` 保留
—— 防止新契约在 Tk 路径上被悄悄丢掉）→ hub **42**；`run_ext_probe.py` 的插件段从 10 条加到 **11** 条
（新增"面板三个按钮点了真的进对应流程"：迁移后面板由同一个 builder 造，接线接错时
"command 非空 + 控件齐全"照样全绿 → ext **56**）；`run_qt_pilot_probe.py` 的 [8] 从 9 条扩到 **19** 条
（工厂方法面一致、**契约清单确实读到 14 个方法且不靠导入 Tk 模块**、Qt 工厂声明 `backend='qt'`、
真实插件注册期无错、闭源插件解密器可用、3 个动作生成按钮、**真实面板 `panel/ok` 且无 fail 行**、
3 个按钮齐全、只读结果视图、按钮同一水平行、外层竖直顺序与 Tk 一致、**点击真的进插件流程**、
**插件源码里已无 Tk 代码用法（AST）**、只认 Tk 的反例仍被上报 `skip`、可移植贡献全 ok、
同一份源码在两个后端都建出控件）→ qt_pilot **41**；第 [9] 段主题映射再加 **14** 条（见 11.3）
→ qt_pilot **60**（主题映射 14 + 持久化等内容 5）。

### 11.2 本次新锁的注入验证（不注入的锁不算锁）

**12** 条布局/迁移/主题锁都用**按真实字节改写 → 跑探针 → 断言目标锁变红 → `finally` 还原并核对 sha256**
已验证（面板迁移 6 条见下表前 6 行，主题映射 4 条见 11.3）。工具是仓库里的
`run_inject_layout_locks.py`（手动跑，**故意不进 `run_ci.py` 的执行步骤**
—— 它会临时改写真实源文件，不适合放进自动闸门；但它**在** pyflakes 的静态扫描名单里，
否则 `run_app_probe` 那条"每个 `run_*.py` 都要被静态检查覆盖、不许有游离脚本"的防腐锁会红
—— 这条锁本次就实打实地抓到过这个新文件）：

| 注入（跑哪个探针） | 变红的锁 |
|---|---|
| 插件 `_ui()` 永不返回 `api.ui`（Qt） | "真实插件面板在 Qt 后端建出来了（panel/ok）" + 另外 5 条面板锁 |
| 插件 `_ui()` 里重新 `import tkinter`（Qt） | "engine_utf8_patch 里已无 Tk 构造/对话框（迁移真的落到 api.ui）" |
| `pack()` 里 left/right 归位那行短路（Qt） | "三个动作按钮落在同一个水平行容器里" |
| `row()` 改用 `QHBoxLayout`（Qt） | "外层容器是竖直堆叠（Tk 默认 pack 方向）…" |
| 契约清单读取返回空元组（Qt） | "契约清单是从 toolkit_plugin_ui.py 读到的 14 个方法…" |
| 三个按钮全接到 `identify`（**Tk 侧 `run_ext_probe.py`**） | "实验插件面板的三个按钮点了真的进对应流程（不只是 command 非空）" |

第 4 条第一次跑时**探针全绿** —— 原锁只比对了"控件顺序的类型"，没查容器方向，
于是把 `row()` 换成横向也照样通过。锁因此收紧成"顺序类型 + `isinstance(layout, QVBoxLayout)`"，
再注入才变红。**这条记在这里，是因为它是"锁看起来在测同一件事、其实没测"的实例**：
没有注入验证就会留下一条永远为真的锁。

同类问题第 5 条是**"清单本身降级"**：`qt_pilot_plugins.UI_METHODS` 原先是
`try: from toolkit_plugin_ui import UI_METHODS / except: 8 个方法` —— 一旦导入失败，
探针那条"两侧方法面一致"就只在 8 个方法上比对（永远为真）。现改为**AST 读源码取清单**
（不 import，避免把 tkinter 拉进 Qt 侧进程），读不到返回空元组，并补一条
"清单必须是 14 个方法"的断言把这个降级堵死。

第 6 条是**"结构锁测不到接线"**：`_engine_panel_problem()` 只要求三个按钮的 `command` 非空，
而三个按钮都由同一个 builder 造 —— 全部接到 `identify` 也满足它。所以补了一条
真 `invoke()` 看进入哪个 op 的锁（Tk 侧），并在 Qt 侧同样有一条点击锁，两个后端都钉住。

### 11.3 主题映射：色板/字体 → QPalette + 样式表 + 持久化（试点最后一块）

**单源，不抄一份。** `qt_pilot_theme.py` **直接 `import toolkit_theme`** 读 `THEMES` / `_FONTS`。
（这个"直接"是后来才成立的：第一版只能**按 AST 读源码里的字面量**，因为
`toolkit_platform → toolkit_base` 顶层就 `import tkinter`；把 `app_dir()` 挪进 Tk 无关的
`toolkit_paths.py` 之后依赖断了，于是换成了真 import —— 见本节末"持久化"。
AST 那版还有个刻意的安全阀：只能取字面量，`THEMES` 一旦被改成算出来的就会显式失败而不是
悄悄用过期色板；换成真 import 后这个顾虑自然消失，因为读的就是运行时对象。）

**"同一份"是被证明的，不是被声称的。** 探针里那条关键的锁不是"Qt 自己和自己比"（那样永远相等），
而是：另起**子进程**（那里 Tk 可用）把 `toolkit_theme.palette(mode)` 的**运行时真值** dump 出来，
再与 Qt 侧逐字段对拍 —— **两个模式 × 18 个颜色角色 + 6 个字体角色**全等。

**映射面**：`qpalette()` 铺 19 个 `QPalette.ColorRole`（含 Disabled 组的 `text_dim`）、
`stylesheet()` 生成 40 行 QSS 覆盖试点用到的控件类（QWidget/QLabel/QGroupBox/QPushButton/
QLineEdit/QPlainTextEdit/QComboBox/QCheckBox/QProgressBar/QScrollBar/QSplitter/QTabBar/
QHeaderView/QTreeView/QMenu/QToolTip/QMainWindow）、`make_font()` 把 `(family, size[, "bold"])`
映射成 `QFont`（**磅值同号**：Tk 按 scaling 换算磅→像素，Qt 按 DPI 换算，结果等价）。
Tk 的 ttk 样式名也在这一层落地：`Dim.TLabel`/`Title.TLabel`/`Stats.TLabel`/
`Green|Red|Yellow.TLabel`/`Accent.TButton` 都有对应（`apply_label_style` /
`apply_button_style` 写 `role`/`style` 属性，由 QSS 按属性命中）—— 试点第一版把 `style`
参数**丢掉了**，于是插件写的语义样式在 Qt 上全变正文色。

**两条语义差（都写成了锁）**：

1. **`px()` 不能在 Qt 侧用。** Tk 的 `px()` 是"96 DPI 设计值 × 缩放系数"（Tk 只把**字号**按
   显示器换算，像素常量不会）；Qt 的坐标本来就是设备无关逻辑像素、高 DPI 由 Qt 缩放 ——
   再乘一次就是**双重缩放**（150% 屏上大 1.5 倍）。锁按 **AST** 找真的 `px(...)` 调用
   （正则会把"别用 px()"这句文档也算成调用，第一版就这么红过一次）。
2. **采样真实像素要看 device pixel ratio。** 第一版像素锁用 `widget.geometry()`（**逻辑**像素）
   去索引 `grab()` 出来的图（**设备**像素），150% 缩放下差 1.5 倍，于是采到了"隔壁那个控件"的
   颜色（按钮采成了分组框底色）。现在按 `img.devicePixelRatio()` 换算 —— 探针实测 `dpr=1.5`。
   这与本项目其它历史教训同源：**口径不说清楚，数字就是错的**。

**锁（19 条，`run_qt_pilot_probe.py` 第 [9] 段 → qt_pilot 41 → 55 → 60）**：色板逐角色一致（两模式 × 18）、
字体逐角色一致（两模式 × 6）、`ThemeSourceError` 安全阀（表必须仍是字面量）、
**真实像素 7 处平面填充 == 色板角色**（host bg / 分组 surface / 按钮 surface2 /
强调按钮 accent / 输入框 entry_bg / 只读视图 entry_bg / 进度条 accent，暗亮各一遍）、
切换确实换像素、往返回到暗色、`Dim.TLabel` → `role=dim` + `font_sm` 磅值、
QSS 里三类语义样式取色来自色板、Qt 界面代码零颜色字面量、主题模块只允许 1 个
（强调色上的文字色，与 Tk `apply_theme` 里那处 `"#fff"` 同一语义 —— 不为它在 Qt 侧新造角色，
否则两个后端就各有一份"白"）、Qt 侧不得调用 `px()`、主题模块不得 import 任何 Tk 侧模块。

**注入验证（6 条，脚本 `run_inject_layout_locks.py` 扩到 12 条注入）**：

| 注入 | 变红的锁 |
|---|---|
| 色板被篡改（`bg` 借用 `surface`） | "Qt 侧色板与 Tk 运行时**逐角色**一致…" |
| QSS 里按钮底色写成 `bg`（配置对照全绿） | "真实像素：暗色下 7 处平面填充等于色板对应角色" |
| 插件工厂里又抄一份颜色字面量 | "Qt 界面代码里没有第二份色板" |
| 主题模块里误用 `toolkit_theme.px(24)` | "Qt 代码里不调用 toolkit 的 px()" |
| 主题模块把 `toolkit_base` 拉回来（Tk 依赖重新接上） | "独立进程 import qt_pilot_theme 后没有 tkinter/toolkit_base" |
| `save_mode` 自己整文件重写 `user.ltx` | "主题持久化不吞别的段" + "不自己写 user.ltx" |

> **第 5 条第一次跑时没红，而是探针整节 SKIP** —— 原因不在锁，在**我写的注入文本**：
> 插入的第二行漏了 4 个空格缩进，把 `try:` 块写坏了（`SyntaxError`），于是探针在
> "导入 qt_pilot_theme 失败"处分流成 SKIP，看起来像"锁没抓住这个错"。
> 这类"注入本身写错 → 伪装成漏锁"很难靠眼睛发现，所以验证器现在**注入后先 `ast.parse`
> 一遍**：解析不过就报 `[!!] 注入文本自身语法错误（这不是锁的问题）` 并计入失败。
>
> 另有一处同类收获：`run_app_probe` 的"不许有游离 `run_*.py`"防腐锁在本轮又抓到过
> 一次（新脚本没进静态名单），以及上面两条"锁口径"修正 —— 都说明**锁和注入自身也要被验证**。

**仍未做的地方已经没有了 —— 持久化接上了（2026-09-12 同日）。** 之前卡在一个具体的依赖上：
Tk 侧 `load_user_theme/save_user_theme` 读写 `user.ltx`，路径来自 `toolkit_base.app_dir()`，
而 `toolkit_base` 顶层就 `import tkinter` / 选 `TkinterDnD.Tk` / import 期还会
`ensure_package("tkinterdnd2")`。也就是说 **`user.ltx` 是 Qt 侧唯一的 Tk 依赖**
（色板、字体、`px` 都不是）。冻结的 Qt 包里没有 Tcl/Tk，所以"存一次主题"会把整个 Tk 拖进来。

**解法：只把"应用目录"这一条规则搬出去**（没有动 `_BaseTk` / `DND_FILES` / `_HAS_DND`
那组承重接口 —— 它们被 8 个文件当**值**消费，还有探针按调用顺序打桩，动它们才是真风险）：

* 新增 `toolkit_paths.py`（Tk 无关，5 行规则）；`toolkit_base` 改为
  `from toolkit_paths import app_dir`（**re-export**），`toolkit_platform` 改从
  `toolkit_paths` 取。于是 `toolkit_base.app_dir()` / `from toolkit_base import app_dir` /
  `from toolkit import app_dir` 三种用法**一个字都没改**，`run_app_probe` 里那句
  `toolkit_platform.app_dir = lambda: 临时目录` 的打桩也照旧可用（它依赖"模块级名字"这一点，
  所以 `toolkit_paths` 里刻意不写成"包一层函数再内部 import"）；
* 依赖链随之中断：`toolkit_theme → toolkit_platform → toolkit_paths`，
  于是 `import toolkit_theme` **不再把 tkinter 带进进程**；
* `qt_pilot_theme` 因此从"按 AST 读源码里的字面量"改成**直接 `import toolkit_theme`**：
  真值就是那一份，连"读源码"这层间接都不需要了；
* 持久化直接转调 `toolkit_theme.load_user_theme / save_user_theme`
  （`qt_pilot_theme.load_mode/save_mode`），**不自己解析、也不整文件重写** `user.ltx` ——
  那份逻辑一旦抄错，存一次主题就会把 `[ffmpeg]` 等段一起抹掉。

**这一条依赖的断开是被证明的**（两条互为正反）：

| 方向 | 锁 |
|---|---|
| 正面 | 独立进程 `import qt_pilot_theme` 后 `sys.modules` 里**没有** `tkinter`/`toolkit_base`，且色板值正确 |
| 反面 | 拦截 `import tkinter`（meta_path）后仍能 `import toolkit_platform / toolkit_theme / qt_pilot_theme` 并取到 light 的 `bg` —— 拿不到就该失败，而不是悄悄降级成一份内置色板 |
| 持久化 | 临时目录（`toolkit_platform.app_dir` 打桩）里**真写** `user.ltx`：写入后 `[theme] mode = light` 且读回一致；预置的 `[ffmpeg]` 段在**两次**写入后都还在（读文件字节，不是读返回值） |
| 不许自己写盘 | AST：`qt_pilot_theme` 里不得出现 `open/write_text/write_bytes/replace` 调用（必须转调 toolkit_theme） |

**两条"锁口径"教训（都是跑红之后改的，不是想出来的）**：

1. **隔离只能在子进程里断言。** 第一版写了"本进程里没有 tkinter"——跑到第 [9] 段时**必然为假**：
   前面第 [8] 段已经加载过 `plugins/` 里的真实插件，而它 `register()` 里写着
   `from toolkit import ...`，那会把 tkinter 拉进来（**试点本体与此无关，是第三方插件的既有写法**）。
   现改为独立进程断言试点自己的主题链。
2. **黑名单要跟着设计走。** "主题模块不得 import Tk 侧模块"这份名单里原本也列着
   `toolkit_theme` —— 那是"不能 import 它"时代的产物；改成真 import 之后这条锁自己红了。
   现只禁 `tkinter / tkinterdnd2 / toolkit / toolkit_base / toolkit_widgets`，
   `toolkit_theme`、`toolkit_paths` 明确放行（它们 Tk 无关这一点由上面两条锁证明）。

---

## 附录 A：如何复核行数

本文**刻意不在正文里固化各文件行数**：`apps/*.py` 与部分库模块仍在迭代，写死的数字
几分钟就会过时，反而让文档变成错误来源。需要行数时请现场测量（一次读完整个仓库）：

```python
import os
root = r"<STALKER_Toolkit 目录>"
for dp, dn, fn in os.walk(root):
    dn[:] = [d for d in dn if d not in ("builds", "backup", "deps", "__pycache__", "temp")]
    for f in sorted(fn):
        if f.endswith(".py"):
            p = os.path.join(dp, f)
            with open(p, encoding="utf-8") as fh:
                print(len(fh.read().splitlines()), os.path.relpath(p, root))
```

把 `builds/` / `backup/` / `deps/` 排除在外，是因为它们是有意保留的历史对照物
（见第一节），不属于活代码。

测量口径：`len(open(path, encoding='utf-8').read().splitlines())`。
撰写时的**粗略量级**（仅供判断"哪个文件是大头"，不要当精确值引用；各文件以百/千行为单位）：
`toolkit_widgets.py` 约 1.4 千行，是单个最大的库模块；六个 App 在数百行至 1.3 千行之间；
`file_system/stalker_fs.py` 约千行；其余库层模块均在一千行以下。
