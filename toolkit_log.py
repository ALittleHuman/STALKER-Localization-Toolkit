# -*- coding: utf-8 -*-
"""
STALKER 汉化工具集 — 日志管线（最先加载，纯 stdlib）

设计约束（方案A）:
  1. 本模块必须能在 import tkinter / 主题 / 组件 / 插件**之前**导入，
     因此只依赖 stdlib（datetime / os / re / sys / time / threading），
     不得引入 tkinter 或工程内其它模块。
  2. 两级日志:
       summary(msg, tag) —— 进 GUI 日志栏 + 落盘
       detail(msg, tag)  —— 只落盘（静默），导出时全量输出
  3. 旧的 log_to_file(msg, tag) 保持原语义（只落盘），供既有调用点继续使用。
  4. **每次启动一个新日志文件**，文件名带进程启动时刻（精确到秒）：
       logs/runtime_YYYYMMDD_HHMMSS.log
     时刻在 import 期定一次，整个会话（含所有工作线程）都写同一个文件；
     所以"这一次运行到底做了什么"永远对应一个独立文件，不会被下次启动
     追加进来，也不需要靠时间戳在混杂内容里找边界。
  5. **并发**（外部审计 2026-09-12 提出的 A-1/A-3）：约束 4 的前提就是多线程共写一个
     文件，因此写盘与启动期缓冲**各自加锁**（`_WRITE_LOCK` / `_BUFFER_LOCK`）。
  6. **不静默**（A-2）：写盘失败不再 `except: pass` —— 记 `_LOG_FAILED` 供 Hub 提示，
     并往 stderr 留一行（只留一次，不刷屏）。
"""
import datetime
import os
import re
import sys
import threading
import time

_LOG_DIR = None          # 显式指定的日志目录（通常是 app_dir()）；None 时自动推断
_LOG_PREFIX = "runtime"
# 本次进程的日志时刻：import 期定一次 = 进程启动时刻。之后不再变，
# 保证同一会话内所有写入落在同一个文件里（多线程共用）。
_SESSION_STAMP = time.strftime("%Y%m%d_%H%M%S")
_GUI_SINK = None         # 由 Hub 注册: fn(msg, tag)

# A-1：写盘锁。多线程共写同一个文件的**追加**写；文本模式 append 无锁时，
# 高并发（多个包同时刷 detail）下日志行会交错，排障时读到的是拼接出来的假行。
_WRITE_LOCK = threading.Lock()
# A-2：首次写盘失败的说明（None = 一直正常）。日志写不出去必须**可见** ——
# 原先 `except Exception: pass` 意味着"日志目录不可写"时用户以为有日志、实际什么都没记。
_LOG_FAILED = None
_LOG_WARNED = False
# A-3：启动期缓冲锁。`take_buffer()` 与并发中的 `_buffer_add()` 原先有窗口：
# 关闭缓冲之后仍可能被追加进 `_BUFFER`，那条消息谁也取不到（GUI 日志栏丢一行）。
_BUFFER_LOCK = threading.Lock()

# ── 日志保留策略（用户裁定 2026-09-12）──
#   * **预发布版（ALPHA/BETA/RC）不清理**：测试期一次会生成大量日志，
#     删早了就没法回看失败现场，所以下限交给人工。
#   * **正式版（无标记）保留最近 100 个**。
LOG_KEEP_RELEASE = 100
# 哨兵："从未设置"。必须与 None 区分开 —— None 是**设置过的**策略"不清理"，
# 而"从未设置"意味着 toolkit_base 那行接线被删了（探针要能抓到这个）。
_UNSET = object()
_KEEP = _UNSET           # None = 不清理；>0 = 只保留最近 N 个 runtime 日志
_KEEP_APPLIED = False
_KEEP_ENV = "STALKER_LOG_KEEP"
# 只认本工具自己写的运行时日志：`runtime_YYYYMMDD_HHMMSS.log`。
# Hub 导出的 `log_<时刻>.txt` 是用户主动产出的快照 —— 绝不能顺手删掉。
_RUNTIME_RE = re.compile(r"^runtime_\d{8}_\d{6}\.log$")

# GUI 未就绪期间的 summary 缓冲（"日志栏可以稍后显示，但必须从一开始就记录"）
_BUFFER = []
_BUFFER_MAX = 500
_BUFFERING = True


def _buffer_add(msg, tag):
    with _BUFFER_LOCK:
        if not _BUFFERING:
            return
        _BUFFER.append((msg, tag))
        if len(_BUFFER) > _BUFFER_MAX:
            del _BUFFER[:len(_BUFFER) - _BUFFER_MAX]


def take_buffer():
    """取出并清空 GUI 未就绪期间缓冲的 summary 条目，并停止继续缓冲。

    "停止缓冲"与"取走"必须在同一个临界区里（A-3）：否则两者之间插进来的
    `_buffer_add` 会把消息放进一个再也无人读取的列表 —— GUI 日志栏少一行，
    而落盘那条还在，于是"界面与日志对不上"。
    """
    global _BUFFERING
    with _BUFFER_LOCK:
        _BUFFERING = False
        out = list(_BUFFER)
        _BUFFER.clear()
    return out


def app_dir_fallback():
    """与 toolkit_base.app_dir() 同规则的兜底实现（避免依赖上层模块）。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def set_log_dir(path):
    """指定日志目录（toolkit_base 导入后会调用一次）。"""
    global _LOG_DIR
    _LOG_DIR = path


def set_gui_sink(fn):
    """注册 GUI 日志栏通道。fn(msg, tag)；调用方需自行保证线程安全
    （Hub 注册时会用 _make_pump 投递到主线程）。"""
    global _GUI_SINK
    _GUI_SINK = fn


def log_name():
    """本次运行的日志文件名：`runtime_<启动时刻>.log`。

    命名规范与 Hub「导出」产出的 `log_<时刻>.txt` 一致（同一 `YYYYMMDD_HHMMSS`
    格式，按文件名即可排序），前缀不同以便区分"运行时日志"与"导出快照"。
    """
    return f"{_LOG_PREFIX}_{_SESSION_STAMP}.log"


def log_path():
    """本次运行的 runtime 日志完整路径（每次启动都不同）。"""
    return os.path.join(_LOG_DIR or app_dir_fallback(), "logs", log_name())


def log_write_failed():
    """首次写盘失败的说明（None = 一直正常）。

    Hub 启动后应当读一次并在日志栏里说出来 —— "日志目录不可写"必须让用户知道，
    否则他会以为有日志可查。进程内**只记第一次**（后续失败多半是同一个原因）。
    """
    return _LOG_FAILED


def _warn_write_failure(msg):
    """写盘失败往 stderr 留一行（只留一次）。绝不抛异常、绝不递归写日志。"""
    global _LOG_WARNED
    if _LOG_WARNED:
        return
    _LOG_WARNED = True
    try:
        sys.stderr.write("[toolkit_log] 日志写盘失败，本次运行的日志无法落盘：%s\n" % msg)
        sys.stderr.flush()
    except Exception:
        pass


def log_to_file(msg, tag="error"):
    """只落盘（保持旧语义）。

    并发：`_WRITE_LOCK` 保证"一行一次写入"（A-1）。
    失败：记 `_LOG_FAILED` + stderr 留一行，**不再静默**（A-2）。
    时间戳带毫秒：`2026-09-12 15:36:08.412`。原来只到秒，于是"启动卡在哪一步"
    只能靠录屏逐帧反推（2026-09-12 的白屏取证就是这么做的）；同一秒里有
    "窗口就绪 / 插件扫描 / 六个栏目装配"四五个相位，秒级精度分不出是哪一段。
    毫秒由**同一个 datetime 对象**取出，不是"两次 time 调用拼起来" —— 后者
    会在一秒边界上拼出 `.412` 配下一秒的秒数。
    """
    global _LOG_FAILED
    try:
        path = log_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _now = datetime.datetime.now()
        line = ("[%s.%03d] [%s] %s\n"
                % (_now.strftime("%Y-%m-%d %H:%M:%S"), _now.microsecond // 1000, tag, msg))
        with _WRITE_LOCK:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
    except Exception as e:
        _LOG_FAILED = "%s: %s" % (type(e).__name__, e)
        _warn_write_failure(_LOG_FAILED)


def summary(msg, tag="info"):
    """简略日志: 落盘 + 进 GUI 日志栏（GUI 未就绪时先缓冲，稍后回放）。"""
    log_to_file(msg, tag)
    if _GUI_SINK is not None:
        try:
            _GUI_SINK(msg, tag)
            return
        except Exception:
            pass
    _buffer_add(msg, tag)


def detail(msg, tag="info"):
    """详细日志: 只落盘，导出日志时全量输出。"""
    log_to_file(msg, tag)


# ═══════════════════════════════════════════════════════════════
# 日志保留（策略 / 执行分开：策略由 toolkit_base 依 APP_PRERELEASE 定，
# 执行在每次启动时做一次；探针两半都能单独验）
# ═══════════════════════════════════════════════════════════════

def retention_keep(prerelease):
    """按版本标记给出保留上限：**预发布 → None（不清理）**，正式版 → 100。

    纯函数（不读全局、不碰磁盘），所以"预发布不清理"这条裁定可以在探针里直接钉住，
    也不必等到真去发一个正式版才能验。
    """
    return None if (prerelease or "").strip() else LOG_KEEP_RELEASE


def set_log_retention(keep):
    """设置保留上限（由 toolkit_base 在 import 期按 APP_PRERELEASE 调一次）。"""
    global _KEEP
    _KEEP = keep


def _env_keep():
    """排障覆盖开关 `STALKER_LOG_KEEP`：`none`/`0`/空 = 不清理，数字 = 上限。

    为什么留这个口子：**只有正式版才清理**，而仓库里跑的是预发布版 —— 想验证
    "正式版那条路径"（以及发版前确认上限真的生效）就得能不改常量地把它打开。
    未设置时返回哨兵值 `_UNSET`，表示"用调用方设的策略"。
    """
    raw = os.environ.get(_KEEP_ENV)
    if raw is None:
        return _UNSET
    raw = raw.strip().lower()
    if raw in ("", "none", "off", "0"):
        return None
    try:
        return max(0, int(raw))
    except ValueError:
        return _UNSET


def current_keep():
    """当前生效的保留上限（None = 不清理）。供探针核对"策略确实接上了"。"""
    env = _env_keep()
    if env is not _UNSET:
        return env
    return None if _KEEP is _UNSET else _KEEP


def policy_applied():
    """策略是否被设置过（`toolkit_base` 在 import 期设一次）。

    只比 `current_keep() == retention_keep(APP_PRERELEASE)` 是**不够**的：
    预发布版的策略本身就是 None，把那行接线删掉，两边仍然都是 None，锁照样绿。
    所以这里单独回答"到底有没有人设过"。
    """
    return _KEEP is not _UNSET


def cleanup_logs(keep=None, log_dir=None):
    """只保留最近 `keep` 个运行时日志，返回 `(删除数, 保留数)`。

    * `keep=None` → 用当前生效的策略；<=0 → 什么都不做（绝不把日志清空）。
    * 只动文件名精确匹配 `runtime_YYYYMMDD_HHMMSS.log` 的文件：Hub 导出的
      `log_<时刻>.txt` 是用户主动产出的快照，**不在**清理范围内。
    * 按**文件名**排序而不是 mtime：命名规范已保证可排序，而 mtime 会被复制/解压改写。
    * 给**本次会话**的日志预留一个位置（`keep - 1`）：会话文件此刻可能还没写出来
      （`log_to_file` 才建文件），按 keep 个旧文件处理会让目录变成 keep+1 个。
    * 本次会话的文件永远保留（即使系统时钟回拨、它排不到最新）。
    """
    if keep is None:
        keep = current_keep()
    if not keep or keep <= 0:
        return (0, 0)
    d = os.path.join(log_dir or _LOG_DIR or app_dir_fallback(), "logs")
    try:
        cands = sorted(n for n in os.listdir(d) if _RUNTIME_RE.match(n))
    except OSError:
        return (0, 0)                      # 目录还不存在 = 没有可清理的
    cur = log_name()
    cur_present = cur in cands
    if cur_present:
        cands.remove(cur)                  # 本次会话的单独对待，不占名额两次
    n_keep = max(0, keep - 1)              # 留一个位置给本次会话的文件
    doomed = cands[:max(0, len(cands) - n_keep)]
    removed = 0
    for n in doomed:
        try:
            os.remove(os.path.join(d, n))
            removed += 1
        except OSError:
            pass
    return (removed, len(cands) - removed + (1 if cur_present else 0))


def cleanup_startup_logs():
    """启动时执行一次保留清理（幂等：同一进程只做一次）。

    预发布版策略是 None → 直接返回 (0, 0)，一个文件都不动。
    """
    global _KEEP_APPLIED
    if _KEEP_APPLIED:
        return (0, 0)
    _KEEP_APPLIED = True
    return cleanup_logs(None)
