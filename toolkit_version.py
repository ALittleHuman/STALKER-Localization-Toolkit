# -*- coding: utf-8 -*-
"""版本号组合与落盘（单一事实来源在 toolkit_base.APP_VERSION）。

为什么单独成模块：
    * **运行期标题**要显示预发布标记（如 `v1.0.0 BETA.1`），
    * **Windows 版本资源**只能用四段纯数字（`1,0,0,0`），不能带字母，
    * 因此"给人看的版本串"与"给系统看的版本号"必须由同一处推导，避免两处各写。

基础版本写在 `toolkit_base.APP_VERSION`（形如 "1.0.0"），本模块负责：
    * 归一化预发布标记（`beta1` / `BETA.1` / `b1` → `BETA.1`）
    * 组合显示串（用于窗口标题、日志、产物目录/文件名）
    * 推导四段数字版本（供 PyInstaller version-file 使用）
    * 把修改后的基础版本写回 `toolkit_base.py`（与 build GUI 共用）
    * 预发布标记的**序号计数**（每个 (完整版本串, 标记名) 一份），命令行与
      构建界面共用同一个 `next_prerelease()`

计数（构建次数 + 标记序号）与版本号一样，**单一事实来源都在 `toolkit_base.py`**
（`BUILD_COUNT` / `PRERELEASE_COUNTS`，见该文件里的说明）。历史上它们各自放在
仓库根目录的独立文件里，那样等于同一份状态有两个真相；现已并入本模块统一读写。
读写都走同一套"模块属性优先、文件正则兜底 + 临时文件原子写"的实现，不再有
第二个机制。

不做的事：不改 `toolkit.py` 的 re-export 结构，不引入新依赖。
"""
import ast
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
# 真实仓库目录（`BASE` 会被测试/探针临时重定向，用于区分"写的是不是真文件"）
_REAL_BASE = BASE

# 支持的预发布通道 → 显示用大写名
CHANNELS = {"a": "ALPHA", "alpha": "ALPHA",
            "b": "BETA", "beta": "BETA",
            "rc": "RC", "pre": "PRE"}

_BASE_RE = re.compile(r'^APP_VERSION\s*=\s*["\']([^"\']*)["\']', re.M)
# 预发布标记与版本号并列存在同一处（toolkit_base.APP_PRERELEASE）
_PRE_RE = re.compile(r'^APP_PRERELEASE\s*=\s*["\']([^"\']*)["\']', re.M)
# 构建计数同样并列存在同一处（toolkit_base.BUILD_COUNT / PRERELEASE_COUNTS）。
# 这两个用"整行匹配等号右侧"（而不是要求右侧形状正确）：坏值也要能**被读坏后
# 当默认**、更要能被写回覆盖掉，否则手改成 `BUILD_COUNT = 五` 之后每写一次都在
# 文件末尾再追加一行，同一个常量出现两遍。
_COUNT_LINE_RE = re.compile(r'^BUILD_COUNT\s*=(.*)$', re.M)
_COUNTS_LINE_RE = re.compile(r'^PRERELEASE_COUNTS\s*=(.*)$', re.M)

# 完整版本串：1.0.0 / v1.0.0 / 1.0.0-beta.2 / 1.0.0 BETA.1 / 1.0.0a1
_FULL_RE = re.compile(
    r"^\s*[vV]?\s*(\d+(?:\.\d+)*)"
    r"(?:\s*[-_ ]\s*([A-Za-z]+)\s*[.\-_]?\s*(\d*))?"
    r"\s*$")


def parse_full_version(text):
    """解析用户可能直接粘贴的完整版本串。

    支持：`1.0.0` / `v1.0.0` / `1.0.0-beta.2` / `1.0.0 BETA.1` / `1.2-beta1`
    返回 (基础版本 'X.Y.Z', 归一化预发布 'BETA.2' 或 '')；无法解析返回 (None, '')。
    """
    if not text:
        return None, ""
    m = _FULL_RE.match(str(text).strip())
    if not m:
        # 退化：只有基础版本数字
        base = normalize_base(text)
        return (base, "") if base else (None, "")
    base = normalize_base(m.group(1))
    if not base:
        return None, ""
    name = CHANNELS.get((m.group(2) or "").lower())
    num = m.group(3) or ""
    pre = f"{name}.{int(num) if num else 1}" if name else ""
    return base, pre


def split_prerelease(tag):
    """把用户输入的预发布标记拆成 (通道名, 序号)。

    接受 beta1 / BETA.1 / b1 / 1.0.0-beta.2 / alpha 等形式；
    无有效通道时返回 (None, None)。
    """
    if not tag:
        return None, None
    s = str(tag).strip()
    if not s:
        return None, None
    # 去掉可能带的 "v"/"V" 前缀
    s = re.sub(r"^[vV]", "", s)
    m = re.match(r"^([A-Za-z]+)\s*[.\-_]?\s*(\d*)$", s)
    if not m:
        return None, None
    name = CHANNELS.get(m.group(1).lower())
    if name is None:
        return None, None
    num = m.group(2)
    return name, (int(num) if num else 1)


def format_prerelease(tag):
    """归一化为显示形式（如 'BETA.1'）；无效返回空串。"""
    name, num = split_prerelease(tag)
    return f"{name}.{num}" if name else ""


def normalize_base(version):
    """把基础版本规整为 'X.Y.Z' 形式（缺位补 0）；非法返回 None。"""
    if not version:
        return None
    parts = re.findall(r"\d+", str(version))
    if not parts:
        return None
    while len(parts) < 3:
        parts.append("0")
    return ".".join(parts[:3])


def full_version(base_version=None, prerelease=None):
    """给人和日志看的完整版本串，如 '1.0.0' 或 '1.0.0 BETA.1'。

    `prerelease=None`（默认）表示"用已保存的标记"（`toolkit_base.APP_PRERELEASE`）；
    显式传 `""` 表示"这次就是不带标记"。运行时标题/日志走默认值，因此构建时存下的
    标记在程序里也看得见 —— 否则产物叫 `... 1.0.1 BETA.1.exe`、界面却只显示 1.0.1。
    """
    base = normalize_base(base_version or current_base_version()) or "0.0.0"
    pre = format_prerelease(current_prerelease() if prerelease is None else prerelease)
    return f"{base} {pre}" if pre else base


def version_tuple(base_version=None, prerelease=None):
    """Windows 版本资源用的四段数字元组（不能带字母）。

    预发布不写进数字里（否则资源无效），只把序号放进第四段便于区分：
        '1.0.0' + BETA.1  → (1, 0, 0, 1)
        纯 '1.0.0'       → (1, 0, 0, 0)

    `prerelease=None` 同 `full_version`：用已保存的标记。
    """
    base = normalize_base(base_version or current_base_version()) or "0.0.0"
    nums = [int(x) for x in base.split(".")][:3]
    while len(nums) < 3:
        nums.append(0)
    _name, num = split_prerelease(current_prerelease() if prerelease is None else prerelease)
    return tuple(nums + [int(num) if num else 0])


# ─────────────────────────────────────────────────────────────
# 读写 toolkit_base.py 里的模块级常量（版本号 / 标记 / 构建计数 / 标记序号）
# ─────────────────────────────────────────────────────────────
# 哨兵：用来区分"这个常量确实是 None/0"和"根本没读到"
_MISSING = object()


def _base_py_path():
    """被读写的 toolkit_base.py 路径（探针会把 `BASE` 重定向到临时副本）。"""
    return os.path.join(BASE, "toolkit_base.py")


def _module_constant(name):
    """从**进程内已加载**的 toolkit_base 取模块级常量；取不到返回 `_MISSING`。

    为什么 `BASE` 被重定向时直接判不可信：探针把 `BASE` 指向临时副本，图的就是
    "读的写的是那份副本"；此时若还认进程内模块属性，等于绕过重定向去读真仓库
    的状态，"重定向"这个动作就作废了（写回侧的 `_sync_module` 判据与此对称）。
    """
    if os.path.abspath(BASE) != _REAL_BASE:
        return _MISSING
    try:
        import toolkit_base as _tb
    except Exception:
        return _MISSING
    return getattr(_tb, name, _MISSING)


def _file_constant(pattern):
    """在 `BASE/toolkit_base.py` 里正则捞某个常量的"等号右侧"文本。

    返回 `_MISSING` 表示文件读不到或没有这一行（老版本文件）。文件是**最后一道
    兜底**：进程内模块属性既然是缓存就可能过期，源文件不会。
    """
    try:
        with open(_base_py_path(), encoding="utf-8") as f:
            m = pattern.search(f.read())
    except Exception:
        return _MISSING
    return m.group(1) if m else _MISSING


def _constant_text(name, pattern):
    """按"模块属性优先、文件正则兜底"取常量的原始值；都没有返回 `_MISSING`。"""
    val = _module_constant(name)
    if val is not _MISSING:
        return val
    return _file_constant(pattern)


def _as_int(value, default=0):
    """把常量文本转成非负 int；坏值（None / 非数字）一律给 `default`。

    为什么坏值要静默兜底而不是抛异常：这两个计数都在**构建路径**上。手改坏一格
    不该让 `python build.py` 直接开不起来 —— 编号重来最多让产物叫回 build_1，
    比"构建器打不开"轻得多。负数同样夹到 0：`build_0` 这种目录名没有意义。
    """
    try:
        return max(0, int(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _sync_module(name, value):
    """写回真文件后，同步**进程内已加载**的模块属性。

    只改文件的话，同一进程里紧接着的 `current_*()` 仍读回旧值（构建器
    "保存后立刻构建"就会用错版本）。只在**写的是真文件**时同步：探针会把
    `BASE` 重定向到临时副本，那种情况下改内存模块等于污染当前进程。
    """
    if os.path.abspath(BASE) != _REAL_BASE:
        return
    try:
        import sys as _sys
        _tb = _sys.modules.get("toolkit_base")
        if _tb is not None:
            setattr(_tb, name, value)
    except Exception:
        pass


def _write_base_constant(pattern, name, line, value):
    """把 toolkit_base.py 里匹配 `pattern` 的一行换成 `line`（原子）。返回 (ok, msg)。

    * 文件里没有这一行（老版本文件 / 手删过）就**追加到末尾**：否则计数无处可存，
      每次构建都从 0 重新数 —— 比写坏一行更隐蔽。这里用整行正则替换而不是
      "匹配正确形状"，坏值才能被覆盖掉而不是越写越多行。
    * 同目录临时文件 + `os.replace`：这是构建路径上的写盘，写到一半崩掉留下
      半截 Python 源文件会让整个程序 import 不进来 —— 比序号重来严重得多。
      `os.replace` 是同目录内的原子操作，磁盘上要么是全旧、要么是全新。
    * 写失败**不抛异常**，只回报 (False, 原因)：计数丢了顶多让编号重来一次。
    """
    path = _base_py_path()
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        return False, f"读取失败: {e}"

    if pattern.search(src):
        new_src = pattern.sub(lambda _m: line, src, count=1)
    else:
        sep = "" if (not src or src.endswith("\n")) else "\n"
        new_src = src + sep + line + "\n"

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            f.write(new_src)
        os.replace(tmp, path)
    except OSError as e:
        try:
            if os.path.isfile(tmp):
                os.remove(tmp)          # 别把半截临时文件留在仓库里
        except OSError:
            pass
        return False, f"写入失败: {e}"
    _sync_module(name, value)
    return True, f"{name} → {line.split('=', 1)[1].strip()}（已写回 toolkit_base.py）"


def current_base_version():
    """读取 toolkit_base.APP_VERSION。"""
    val = _constant_text("APP_VERSION", _BASE_RE)
    return "0.0.0" if val is _MISSING else val


def current_prerelease():
    """读取 toolkit_base.APP_PRERELEASE（已保存的预发布标记，无则空串）。

    与 `APP_VERSION` 并列存在同一处 —— 版本号与标记是一体两面，分两处存必然对不上。
    """
    val = _constant_text("APP_PRERELEASE", _PRE_RE)
    return format_prerelease(val) if val is not _MISSING else ""


def current_build_count():
    """读取 toolkit_base.BUILD_COUNT（已构建次数）。

    缺失 / 空 / 坏值一律当 **0**：与旧行为一致（读到非数字就当没数过），
    由 `next_build_dir` 往后找第一个空号，历史产物照样不会被覆盖。
    """
    val = _constant_text("BUILD_COUNT", _COUNT_LINE_RE)
    return 0 if val is _MISSING else _as_int(val, 0)


def save_build_count(count):
    """把已构建次数写回 toolkit_base.py 的 `BUILD_COUNT` 一行。返回 (ok, msg)。

    `next_build_dir()` 用它 —— 计数与产物目录必须同时推进，所以写在这里、
    目录创建留在 build.py（BUILDS_DIR 是构建器的事）。
    """
    try:
        n = int(str(count).strip())
    except (TypeError, ValueError):
        return False, f"构建次数非法: {count!r}"
    if n < 0:
        return False, f"构建次数不能为负: {n}"
    return _write_base_constant(_COUNT_LINE_RE, "BUILD_COUNT",
                                f"BUILD_COUNT = {n}", n)


def snapshot_state():
    """构建前的**完整**版本状态快照（供构建失败时精确回退）。

    为什么是四项：`APP_VERSION` / `APP_PRERELEASE` / `BUILD_COUNT` / `PRERELEASE_COUNTS`
    都是同一次构建会推进的状态。少回退任何一项都会留下"失败也消耗编号"的痕迹 ——
    例如只回退版本号与构建次数、不回退标记计数，下一次自动构建的序号就会跳一格
    （ALPHA.7 失败 → 下次直接 ALPHA.9），序号出现空洞。

    读不到的值退回当前实现的默认（见各 current_* / _load_prerelease_counts），
    因此本函数**不会抛**：宁可回退到一个保守值，也不能因为快照读失败而让构建起不来。
    """
    return {
        "version": current_base_version(),
        "prerelease": current_prerelease(),
        "build_count": current_build_count(),
        "counts": _load_prerelease_counts(),
    }


def restore_state(snap):
    """把快照里的四项写回。返回 `(ok, [逐项说明…])`。

    **逐项写、逐项报告**：部分回退比不回退更危险（版本号回去了、计数没回去，
    下次构建出来的编号就与人对不上），所以任何一项失败都要能看见。
    """
    if not isinstance(snap, dict):
        return False, ["快照形状不对: %r" % (snap,)]
    results, ok = [], True
    if snap.get("version") is not None:
        good, msg = save_version(new_version=snap["version"],
                                 new_prerelease=snap.get("prerelease"))
        results.append("版本号+标记 → %s: %s" % (snap["version"], msg))
        ok = ok and good
    if snap.get("build_count") is not None:
        good, msg = save_build_count(snap["build_count"])
        results.append("构建次数 → %s: %s" % (snap["build_count"], msg))
        ok = ok and good
    if isinstance(snap.get("counts"), dict):
        # 注意：`_save_prerelease_counts` 返回的是 **bool**（不是 (ok, msg) 元组），
        # 与 save_version / save_build_count 不一样 —— 探针锁抓到过我这个解包错误。
        good = _save_prerelease_counts(snap["counts"])
        results.append("标记计数 → %s: %s" % (snap["counts"],
                                              "已写回" if good else "写回失败"))
        ok = ok and good
    return ok, results


def save_version(new_version=None, new_prerelease=None):
    """把版本号与预发布标记写回 toolkit_base.py（各改一行）。

    参数为 None 表示**不动**该字段；空串表示"清空"。
    返回 (ok, message)。会先把原文件备份到 backup/pre_version_change/。

    为什么标记也要落盘：构建产物名带标记（`... 1.0.1 BETA.1.exe`），
    但界面上还得让人一眼看出当前是哪个标记；而且运行时标题/日志也取这一份。
    只存版本号的话，下次打开构建器标记就重置成"无"，产物名和界面会对不上。
    """
    path = os.path.join(BASE, "toolkit_base.py")
    try:
        with open(path, encoding="utf-8") as f:
            src = f.read()
    except OSError as e:
        return False, f"读取失败: {e}"

    base = None
    if new_version is not None:
        base = normalize_base(new_version)
        if not base:
            return False, f"版本号非法: {new_version!r}（应为 X.Y.Z）"
        if not _BASE_RE.search(src):
            return False, "未在 toolkit_base.py 中找到 APP_VERSION"

    pre = None
    if new_prerelease is not None:
        raw = str(new_prerelease).strip()
        if raw and raw not in ("无", "none", "None"):
            pre = format_prerelease(raw)
            if not pre:
                return False, (f"标记非法: {new_prerelease!r}"
                               f"（支持 ALPHA/BETA/RC/PRE，如 BETA.1）")
        else:
            pre = ""          # 显式清空
    old_base = _BASE_RE.search(src).group(1) if _BASE_RE.search(src) else None
    old_pre = _PRE_RE.search(src).group(1) if _PRE_RE.search(src) else ""

    if base is not None and not _PRE_RE.search(src):
        # 老文件还没有 APP_PRERELEASE 这一行：在建版本号那一行后补一行
        src = _BASE_RE.sub(
            lambda m: m.group(0) + '\nAPP_PRERELEASE = "%s"' % (pre if pre is not None else ""),
            src, count=1)
        if pre is None:
            pre = ""

    if base is not None:
        if old_base == base and (pre is None or format_prerelease(old_pre) == pre):
            return True, f"版本号未变（{base}{(' ' + pre) if pre else ''}）"
    elif pre is not None and format_prerelease(old_pre) == pre:
        return True, f"标记未变（{pre or '无'}）"

    # 备份（与其它一次性改动一致，放在 backup/ 下）
    try:
        bak_dir = os.path.join(BASE, "backup", "pre_version_change")
        os.makedirs(bak_dir, exist_ok=True)
        bak = os.path.join(bak_dir, "toolkit_base.py")
        if not os.path.exists(bak):
            with open(path, encoding="utf-8") as f:
                with open(bak, "w", encoding="utf-8", newline="") as g:
                    g.write(f.read())
    except Exception:
        pass

    new_src = src
    if base is not None:
        new_src = _BASE_RE.sub(f'APP_VERSION = "{base}"', new_src, count=1)
    if pre is not None:
        new_src = _PRE_RE.sub(f'APP_PRERELEASE = "{pre}"', new_src, count=1)
    try:
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(new_src)
    except OSError as e:
        return False, f"写入失败: {e}"

    # 同步**进程内已加载的**模块属性：`import toolkit_base` 拿到的是缓存对象，
    # 只改文件的话，同一进程里紧接着的 current_base_version() / full_version()
    # 仍然读回旧值（构建器"保存后立刻构建"就会用错版本）。
    # 判据（真文件才同步、重定向副本不同步）在 _sync_module 里，与计数写回共用。
    if base is not None:
        _sync_module("APP_VERSION", base)
    if pre is not None:
        _sync_module("APP_PRERELEASE", pre)

    now_base = base if base is not None else (old_base or "?")
    now_pre = pre if pre is not None else format_prerelease(old_pre)
    return True, (f"版本号 {old_base or '?'} → {now_base}"
                  f"，标记 {format_prerelease(old_pre) or '无'} → {now_pre or '无'}"
                  f"（已写回 toolkit_base.py）")


def save_base_version(new_version):
    """兼容旧签名：只改基础版本，标记保持不动。"""
    return save_version(new_version=new_version)


# ─────────────────────────────────────────────────────────────
# 预发布标记的序号计数：每个 (完整版本串, 标记名) 一份
# ─────────────────────────────────────────────────────────────
# 存成 `toolkit_base.PRERELEASE_COUNTS` 一行（与 BUILD_COUNT / APP_PRERELEASE 并列，
# 见 toolkit_base.py 里的说明）：同一份"构建状态"只有一个真相，不再有第二个文件。
# 形如：PRERELEASE_COUNTS = {"1.0.1|ALPHA": 3, "1.0.1|BETA": 1}
# 值用 JSON 写法（`json.dumps`）保证既是合法 Python 字面量、又方便人读与手改。
def _sanitize_counts(data):
    """把任意来源的计数规整成 {str: int>=0}：坏值只丢那一条，非 dict 一律当空。

    半坏的来源（手改坏一行）不该把整个计数抹掉，只丢坏的那条键。
    """
    if not isinstance(data, dict):
        return {}
    counts = {}
    for key, val in data.items():
        try:
            num = int(val)
        except (TypeError, ValueError):
            continue
        if num >= 0:
            counts[str(key)] = num
    return counts


def _load_prerelease_counts():
    """读 `toolkit_base.PRERELEASE_COUNTS`；**缺失 / 空 / 损坏 / 形状不对当空**（{}）。

    这是构建路径上的读取：手改坏一行不该让构建直接开不起来 —— 归零重来最多让
    序号从 .1 重新数，比"构建器打不开"轻得多（下限规则还会把它兜回已发布的号）。
    """
    val = _constant_text("PRERELEASE_COUNTS", _COUNTS_LINE_RE)
    if val is _MISSING:
        return {}
    if isinstance(val, str):
        # 走文件正则兜底时拿到的是源码文本，用 ast 解析（不是 eval：只认字面量）
        try:
            val = ast.literal_eval(val.strip())
        except (ValueError, SyntaxError, TypeError):
            return {}
    return _sanitize_counts(val)


def _save_prerelease_counts(counts):
    """把计数写回 `toolkit_base.PRERELEASE_COUNTS` 一行（原子写，见 _write_base_constant）。

    * 只写**一行**、且用整行替换：不动同一文件里的 APP_VERSION / APP_PRERELEASE /
      BUILD_COUNT，也不会在坏值后面越追加越多行。
    * 写失败返回 False 而**不抛异常**：计数丢了顶多让序号重来一次，不该拦住
      一次已经配置好的构建。
    """
    data = _sanitize_counts(counts)
    line = ("PRERELEASE_COUNTS = "
            + json.dumps(data, ensure_ascii=False, sort_keys=True))
    ok, _msg = _write_base_constant(_COUNTS_LINE_RE, "PRERELEASE_COUNTS", line, data)
    return ok


def _counter_floor(base, name):
    """已保存标记给同一 (版本串, 标记名) 留下的序号下限。

    为什么需要下限：手工输入优先（`--prerelease` / 界面上手填）时**不动计数**，
    但那个值会写回 APP_PRERELEASE。假如下限不管它：PRERELEASE_COUNTS 里还是
    ALPHA:2、人却已经发到 ALPHA.7，下一次自动递增会给出 ALPHA.3 —— 序号倒着走，
    看着像回退。因此把"已保存标记的序号"当作该键的下限。
    计数现在与 APP_PRERELEASE 同处一个文件，读起来更直接，但**规则本身不变**：
    只有**版本串与标记名都对得上**才算；版本一变就是新键，必须从 .1 重来。
    """
    saved_name, saved_num = split_prerelease(current_prerelease())
    if not saved_name or not saved_num or saved_name != name:
        return 0
    if normalize_base(current_base_version()) != base:
        return 0
    return int(saved_num)


def next_prerelease(tag=None, base_version=None, consume=False):
    """下一个预发布标记：按 (完整版本串, 标记名) **各自独立**计数。

    语义（用户逐条确认过，run_build_probe 五个用例逐条断言）：
        * 同版本同标记连续构建：ALPHA.1 → ALPHA.2 → ALPHA.3（每次构建 +1）
        * 同版本换标记名（ALPHA→BETA）：是新键 → BETA.1
        * 换回用过的标记（ALPHA→BETA→ALPHA）：**续上** ALPHA 的原计数，不回到 .1
        * 基础版本串一变（1.0.1→1.0.2 或 1.0.1→1.1.0）：键变了 → 各标记都从 .1 起

    键为什么用**完整版本串**而不是 semver 主号：产物名里写的就是完整版本
    （`... 1.0.2 ALPHA.1.exe`），1.0.1 与 1.0.2 是两个并列的产物，序号必须各自
    从 1 数；只按主号算的话，1.0.2 的第一个 ALPHA 会叫 ALPHA.8，看着像 1.0.1 的第 8 版。

    `consume=False`（默认）**只读不写** —— 界面用它显示"下次标记"，看多少次都一样；
    `consume=True` 读出并**立即 +1 落盘** —— 只有真正要构建的那一次才调它。
    两者用的是同一段计算，因此"界面显示的"和"构建用掉的"必然是同一个值。

    标记无法识别（或本来就没有标记）时返回空串：没有东西可递增，也不凭空造一个。
    `tag` / `base_version` 默认取已保存值（APP_PRERELEASE / APP_VERSION）。
    """
    name, _num = split_prerelease(current_prerelease() if tag is None else tag)
    if not name:
        return ""
    base = normalize_base(base_version or current_base_version()) or "0.0.0"
    key = f"{base}|{name}"
    counts = _load_prerelease_counts()
    last = max(counts.get(key, 0), _counter_floor(base, name))
    nxt = last + 1
    if consume:
        counts[key] = nxt
        _save_prerelease_counts(counts)
    # 统一走 format_prerelease 归一化，界面/日志/产物名拿到的写法完全一致
    return format_prerelease(f"{name}.{nxt}")

