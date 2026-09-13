# -*- coding: utf-8 -*-
"""
DB 双向交叉验证：工程引擎（file_system/stalker_fs.py） ↔ 官方 converter.exe（下称 cv）

为什么必须"交叉"：两边是独立实现，任何一边**自产自销**都能对上（自己封自己解），
只有交叉才能证明"工具读得懂官方产物"且"官方认工具产物"。所以对每个格式尽量跑：

    方向 A  cv 封包 → 工具解包 → 与原始源文件逐字节比对    （工具读得懂官方产物）
    方向 B  工具封包 → cv 解包 → 与原始源文件逐字节比对    （官方认工具产物）
    方向 C  工具封包 → 工具解包                            （自洽性；便宜，全跑）

**源集合里包含目录条目**（`(path, b"", True)`，path 不带尾部反斜杠 —— 引擎的
build_header 自己会补 `\\`）。这一条是后补的关键覆盖：早先的版本只把文件喂给
pack_db，于是"目录条目"这条路径**从未被交叉验证过**；而 cv 恰恰只在处理目录条目时
才有已知缺陷（见 CV_UNPACK_BROKEN），测试集不含它就等于漏了一半。

cv 能力（2026-09 实测；封包侧每次运行仍会**重新判定**，不写死）：
    xdb / 2947ru / 2947ww   cv 能封、能解        → A + B + C
    2945 / 2215             cv **不能封**（`-pack` 返回 0 但不产出文件）→ B + C
    11xx                    cv 不能封；且解**含目录条目**的 11xx 包时栈溢出
                            （返回码 0xC00000FD = 3221225725）→ 记为 SKIP(cv 缺陷) + C
                            （不含目录条目的 11xx 包 cv 能解，见文末 LZHUF 专项）

cv 封包侧的两个**规范化行为**（实测，方向 A 的期望值必须照此校准，否则会误报）：
    1. **路径全部转小写**：源里的 `Config/Text/T.XML`、`README.md` 进包后就是
       `config/text/t.xml`、`readme.md`（cv 自己解自己的包也是小写）。所以方向 A
       只能**忽略大小写**比对；方向 B 里 cv 解工具包会**保留**原大小写，
       说明转小写是 cv 封包侧的行为，不是引擎丢信息。
    2. **只给"直接含文件的目录"写目录条目**，中间层目录（`deep`、`deep/a`…）包里没有，
       cv 解包时靠父目录推导补出来。所以方向 A **不能**要求中间层目录条目存在。

cv 的第三个行为：**文件名走本机 ANSI 代码页**（真实数据测出来的，2026-09）
    归档里的文件名按 **cp1251** 存字节；cv 读写文件名时把这些字节当**本机 ANSI 代码页**
    （`GetACP()`；中文系统是 cp936/GBK）去转。于是本机 ANSI ≠ cp1251 时：
        * 能转换的名字 → 写成**乱码名**（`Сценарий windows.cmd` → `仰屙囵栝 windows.cmd`）；
        * 无法转换的字节 → cv **直接丢弃**（不是替换成 U+FFFD），某些名字因此连文件都建不出来。
    实测 45 MB 真实俄文模组包（5375 条目）：**内容 5242 个文件逐字节全一致**，
    7 个西里尔文件名受影响（5 个丢失、2 个变成乱码名）。**这是 cv + 本机代码页的限制，
    不是引擎问题**——引擎正确解出了原名的西里尔文。
    所以 `run_cv_filename_codepage()` 单独把这条行为显式化：本机 ANSI == cp1251 时应 PASS，
    不同时按 SKIP 记录实测结果（绝不沉默）。

**SKIP 与 PASS 必须分得清**（否则就是假绿）：每个方向都打印 PASS / FAIL / SKIP(原因)，
末尾给计数，**只有出现 FAIL 才非零退出**。往 CV_UNPACK_BROKEN 里加条目等于把 FAIL
降级成 SKIP，因此那里面每条都必须附实测证据。

Usage:
    python cross_validate.py
"""
import locale
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "file_system"))
sys.path.insert(0, HERE)                     # toolkit_platform 在仓库根
import stalker_fs
from toolkit_platform import hidden_kwargs   # CREATE_NO_WINDOW，避免每次调 cv 闪控制台

# 官方 converter.exe 的位置：环境变量优先（run_ci 会把解析结果回传进来，两处判定
# 必然一致），否则用本机原路径。原先写死绝对路径 → 换台机器就永远 SKIP，
# "交叉校验"实际上只在作者本机能跑（run_ci 的两级门禁要能真跑起来就得能换路径）。
CV = (os.environ.get("STALKER_CONVERTER_EXE")
      or r"E:\Software\Games\STALKER\Localization\Tools\Tool\Stalker_Unpacker_2017\converter.exe")

# 每次运行一个**独立**的工作目录。
# 原先固定在 <repo>/cross_validate_out，而 run_ci.cleanup() 会整目录 rmtree
# 它 —— 两个 CI 同时跑（多终端 / 多代理 / IDE 里手点）就会互相删掉对方正在
# 比对的文件，症状是 "file set differs" 与毫无道理的 FileNotFoundError。
# 放在系统临时目录还顺带避免了污染仓库。
OUT = tempfile.mkdtemp(prefix="toolkit_xval_")

# Relative to STALKER_Toolkit root; ASCII paths only for cv compatibility.
# 只要求"小而稳定、必然存在"的 ASCII 路径文件；曾用 video_ogm_tool.cfg.json，
# 但那是运行期生成的含绝对路径的缓存，已删除（见 ARCHITECTURE.md 构建细节）。
SOURCE_FILES = [
    "README.md",
    "ARCHITECTURE.md",
    os.path.join("plugins", "nlc_sqfs.py"),
    "app_icon.ico",
]

FORMATS = [
    ("xdb", "-xdb"),
    ("2947ru", "-2947ru"),
    ("2947ww", "-2947ww"),
    ("2945", "-2945"),
    ("2215", "-2215"),
    ("11xx", "-11xx"),
]

# cv 自身缺陷（**只减不增**；加进来等于把 FAIL 降级成 SKIP，必须附实测证据）
CV_UNPACK_BROKEN = {
    "11xx": "cv 解**含目录条目**的 11xx 包时会递归到栈溢出：实测**约 21 秒**后以 "
            "0xC00000FD 结束（不是立刻崩、也不是死循环，所以超时给到 300s 才拿得到真返回码）；"
            "不含目录条目的包它 0.0s 就正常解出",
}

PASS = []
FAIL = []
SKIP = []

# 本机 ANSI 代码页：cv 读写文件名用的是它（不是归档里那套 cp1251）。
#
# ⚠ 不能用 `locale.getpreferredencoding(False)`（2026-09-12 外部审计查出的真缺陷）：
#   本机实测它返回 "utf-8"（Python 的 UTF-8 模式 / 环境变量都能影响它），
#   而 cv 走的是 Win32 `MultiByteToWideChar(CP_ACP)` —— 也就是 `GetACP()`（本机 936）。
#   两者不一致时，预测名会把西里尔字节**整段丢掉**，于是"cv 明明写得成合法乱码名"的
#   场景被预测成"写不成"，落到 `else` 分支 → **误报 FAIL**（实测名字：`Сценарий windows.cmd`
#   预测成 `' windows.cmd'`，而 cv 实际写成 `'仰屙囵栝 windows.cmd'`）。
def _windows_acp():
    if sys.platform != "win32":
        return locale.getpreferredencoding(False)
    try:
        import ctypes
        return "cp%d" % int(ctypes.windll.kernel32.GetACP())
    except Exception:
        return locale.getpreferredencoding(False)


ANSI_CP = _windows_acp()


def _acp_code():
    """`ANSI_CP` → Win32 代码页整数（"cp936" → 936）；拿不到返回 0（CP_ACP）。"""
    s = str(ANSI_CP).lower().replace("-", "").lstrip("cp")
    return int(s) if s.isdigit() else 0


def cv_written_name(name):
    """预测 cv 会把这个名字写成什么：归档字节(cp1251) 按本机 ANSI 代码页(GetACP) 转。

    **必须走 Win32 API**，不能用 Python 的 `decode(..., errors="ignore")`：
      * `MultiByteToWideChar(CP_ACP, …)` 对**无效前导字节**给的是私用区字符（实测 U+F8F5），
        而不是"丢弃"（旧实现的注释与归因文字都写错了）；
      * 真正让 cv 建不出文件的是转出来的 `?`(U+003F) —— Win32 文件名非法字符，
        `CreateFileW` 因此失败，cv 静默跳过。这才是"cv 侧少文件"的唯一原因。
    返回 None 表示无法预测（调用方按"不能判定"处理）。
    """
    try:
        raw = name.encode("cp1251")
    except Exception:
        return None
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            k32 = ctypes.WinDLL("kernel32", use_last_error=True)
            mb2wc = k32.MultiByteToWideChar
            mb2wc.argtypes = [wintypes.UINT, wintypes.DWORD, ctypes.c_char_p,
                              ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int]
            mb2wc.restype = ctypes.c_int
            cp = _acp_code()
            need = mb2wc(cp, 0, raw, len(raw), None, 0)
            if need > 0:
                buf = ctypes.create_unicode_buffer(need)
                got = mb2wc(cp, 0, raw, len(raw), buf, need)
                if got > 0:
                    return buf[:got]
        except Exception:
            pass                       # 落到下面的 Python 兜底（语义稍弱，但不会崩）
    try:
        return raw.decode(ANSI_CP, errors="ignore")
    except Exception:
        return None


def log(msg):
    print(f"[xval] {msg}")


def coverage_line(compared, total, uncovered=0, reason=""):
    """覆盖率行 —— 与套件 `bytewise_verify.py` / `real_db_xval.py` 同一格式。

    **必须显式报出**（用户口径 2026-09-12：全部要比真内容）：默认判定只管"正确性"
    （字节不同 / 无法解释的缺失才 FAIL），因此"跳过了一项"很容易被读成"比过了" ——
    覆盖率行就是不让这件事发生。
    """
    pct = (compared / total * 100.0) if total else 100.0
    tail = ""
    if uncovered:
        tail = "（未覆盖 %d 项%s）" % (uncovered, ("：" + reason) if reason else "")
    return "覆盖率: %d/%d = %.2f%%%s" % (compared, total, pct, tail)


def verdict_exit_code(strict, fails, uncovered):
    """退出码：**失败项 > 0 一律红**；`--strict` 下"已解释的不可比对项"也判红。

    分层语义（与套件脚本一致）：
      * 默认 —— 只对"真的不一致 / 真的丢了"判红；cv 侧限制（不支持该格式封包、
        11xx 栈溢出、名字含 Win32 非法字符）导致的不可比对项**单列但不判红**；
      * `--strict` —— 还要求 **100% 覆盖率**，只要有一项不可比对就判红。
    分开的理由：含西里尔文件名的真实包在 cv 侧**永久**写不出某几个文件，
    若把它们算失败，闸门就永远是红的（红久了就没人看）。
    """
    if fails:
        return 1
    if strict and uncovered:
        return 1
    return 0


def mark(kind, fmt, direction, detail=""):
    (PASS if kind == "PASS" else FAIL if kind == "FAIL" else SKIP).append(
        f"{fmt}:{direction}")
    log(f"  [{kind}] {fmt} / {direction}{(' — ' + detail) if detail else ''}")


def ensure_dir(p):
    os.makedirs(p, exist_ok=True)


def load_source_files():
    """Return [(rel_path_with_slash, data_bytes, is_dir)] for the chosen files."""
    files = []
    for rel in SOURCE_FILES:
        p = os.path.join(HERE, rel)
        if not os.path.isfile(p):
            log(f"SKIP missing source file: {rel}")
            continue
        with open(p, "rb") as f:
            data = f.read()
        files.append((rel.replace("\\", "/"), data, False))
    if len(files) < 2:
        raise SystemExit("not enough source files; check SOURCE_FILES")
    return files


# 样例文件也放进本次运行的独占目录：原先写 <repo>/cross_validate_samples，
# 既污染仓库（且没进 .gitignore），又会被并发运行互相覆盖。
SAMPLE_DIR = os.path.join(OUT, "_samples")


def generate_sample_files():
    """Generate a wider set of files (empty, tiny, text, random, deep path)."""
    ensure_dir(SAMPLE_DIR)
    samples = []

    def add(rel, data):
        p = os.path.join(SAMPLE_DIR, rel.replace("/", os.sep))
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        samples.append((rel.replace("\\", "/"), data, False))

    add("sample_empty.bin", b"")
    add("sample_one_byte.bin", b"\x00")
    add("sample_text.txt", ("STALKER cross-validation line\n" * 500).encode("utf-8"))
    add("sample_random_1k.bin", bytes(random.randrange(256) for _ in range(1024)))
    add("sample_random_512k.bin", bytes(random.randrange(256) for _ in range(512 * 1024)))
    add("deep/a/b/c/sample_deep.bin", b"deep path payload")
    return samples


def dirs_of(files):
    """从文件路径推导目录条目。**不带尾部反斜杠**：引擎的 build_header 自己会补。"""
    d = set()
    for rel, _data, is_dir in files:
        if is_dir:
            continue
        parts = rel.replace("\\", "/").split("/")
        for i in range(1, len(parts)):
            d.add("/".join(parts[:i]))
    return sorted(d)


def with_dirs(files):
    """目录条目排在文件前面（与 cv 产物的布局一致）。"""
    return [(d, b"", True) for d in dirs_of(files)] + list(files)


def write_source_tree(files, dst):
    if os.path.exists(dst):
        shutil.rmtree(dst)
    ensure_dir(dst)
    for rel, data, is_dir in files:
        p = os.path.join(dst, rel.replace("/", os.sep))
        if is_dir:
            os.makedirs(p, exist_ok=True)
            continue
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)


def dir_files(root):
    """Return {rel_path_normalized: absolute_path} for every file under root.

    **不再算哈希**（2026-09-12 口径订正）：用户口径是"双向验证都要求**字节级相同**"。
    哈希相等只是概率上等同，且不一致时给不出"首个不同字节在哪"。现在只收集路径，
    内容比对走 `first_byte_diff()` 逐字节做，**一次只读一对文件**（比原先把所有文件
    读进内存算摘要更省，对大包也友好）。
    """
    out = {}
    for dp, _dns, fns in os.walk(root):
        for fn in fns:
            p = os.path.join(dp, fn)
            out[os.path.relpath(p, root).replace("\\", "/")] = p
    return out


def first_byte_diff(path_a, path_b):
    """逐字节比较两个文件 → (相同?, 说明)。不同时说明里带**首异下标 + 两侧字节值 + 长度**。

    这正是哈希口径给不出的信息：没有它，"内容不同"只能靠人工再二分去找。
    """
    with open(path_a, "rb") as f:
        a = f.read()
    with open(path_b, "rb") as f:
        b = f.read()
    n = min(len(a), len(b))
    step = 1 << 16
    for off in range(0, n, step):
        ca, cb = a[off:off + step], b[off:off + step]
        if ca != cb:
            # ⚠ 逐个比到**两片里较短的那一个**为止：两文件长度不等时最后一片长度不同，
            # 按 len(ca) 迭代会在 cb 上越界（探针锁抓到过这个 IndexError）。
            for i in range(min(len(ca), len(cb))):
                if ca[i] != cb[i]:
                    return False, ("首异字节 @%d：%d(0x%02x) != %d(0x%02x)；长度 %d vs %d"
                                   % (off + i, ca[i], ca[i], cb[i], cb[i], len(a), len(b)))
    if len(a) != len(b):
        return False, "长度不同：%d vs %d（前 %d 字节相同）" % (len(a), len(b), n)
    return True, "逐字节相同（%d 字节）" % len(a)


def _compare_trees(expected_root, actual_root, label, lower=False):
    exp = dir_files(expected_root)
    act = dir_files(actual_root) if os.path.isdir(actual_root) else {}
    key = (lambda k: k.lower()) if lower else (lambda k: k)
    exp_m = {key(k): v for k, v in exp.items()}
    act_m = {key(k): v for k, v in act.items()}
    ok = True
    if exp_m.keys() != act_m.keys():
        missing = sorted(exp_m.keys() - act_m.keys())
        extra = sorted(act_m.keys() - exp_m.keys())
        log(f"    {label}: file set differs{'(忽略大小写)' if lower else ''}; "
            f"missing={missing[:5]} extra={extra[:5]}")
        ok = False
    for rel, pa in sorted(exp_m.items()):
        pb = act_m.get(rel)
        if pb is None:
            continue
        same, why = first_byte_diff(pa, pb)
        if not same:
            log(f"    {label}: 内容不同: {rel} — {why}")
            ok = False
    return ok


def compare_trees(expected_root, actual_root, label):
    """逐字节比对两棵树（路径区分大小写）。"""
    return _compare_trees(expected_root, actual_root, label, lower=False)


def compare_trees_ci(expected_root, actual_root, label):
    """忽略**路径大小写**的树比对 —— 方向 A 专用（cv 封包会把路径转小写，见文件头）。"""
    return _compare_trees(expected_root, actual_root, label, lower=True)


def all_dirs(files):
    """源里全部目录（小写、正斜杠、不含尾斜杠）。"""
    d = set()
    for rel, _data, _is_dir in files:
        parts = rel.replace("\\", "/").strip("/").split("/")
        for i in range(1, len(parts)):
            d.add("/".join(parts[:i]).lower())
    return d


def leaf_dirs(files):
    """**直接包含文件**的目录（小写）。cv 只给这些目录写条目，中间层不写（见文件头）。"""
    d = set()
    for rel, _data, is_dir in files:
        if is_dir:
            continue
        parent = os.path.dirname(rel.replace("\\", "/")).lower()
        if parent:
            d.add(parent)
    return d


def dirs_on_disk(root):
    """root 下所有目录（相对路径、正斜杠、不含 root 自身）。"""
    got = set()
    for dp, _dns, _fns in os.walk(root):
        rel = os.path.relpath(dp, root).replace("\\", "/")
        if rel != ".":
            got.add(rel)
    return got


def toolkit_unpack(db, fmt, dst):
    """工具解包到 dst，返回 (写出文件数, 目录条目集合)。"""
    ensure_dir(dst)
    entries = stalker_fs.unpack_db(db, fmt)
    count = 0
    dirs = set()
    for e in entries:
        rel = e["path"].replace("\\", "/").strip("/")
        if e.get("is_dir"):
            dirs.add(rel)
            continue
        data = stalker_fs.extract_file(db, e)
        if data is None:
            continue
        p = stalker_fs.safe_out_path(dst, rel)
        if p is None:
            continue          # 归档内路径逃逸：测试解包器与工具同一条纪律
        d = os.path.dirname(p)
        if d:
            os.makedirs(d, exist_ok=True)
        with open(p, "wb") as f:
            f.write(data)
        count += 1
    return count, dirs


def cv_pack(src_tree, flag, db_path):
    """cv 封包 → (是否产出, 说明)。

    cv 对**不支持的格式**返回码是 0 但**不写文件**，所以只看 returncode 会误判成成功。
    """
    if os.path.exists(db_path):
        os.remove(db_path)
    try:
        r = subprocess.run([CV, "-pack", flag, src_tree, "-out", db_path],
                           capture_output=True, text=True, timeout=300,
                           cwd=os.path.dirname(CV), **hidden_kwargs())
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT(300s)"
    if r.returncode != 0:
        return False, f"rc={r.returncode}"
    if not os.path.isfile(db_path) or os.path.getsize(db_path) == 0:
        return False, "rc=0 但未产出文件（cv 不支持该格式封包）"
    return True, f"{os.path.getsize(db_path)} bytes"


def cv_unpack(db_path, flag, dst):
    """cv 解包 → (是否成功, 说明)。超时与崩溃都算失败，由调用方决定 PASS/FAIL/SKIP。"""
    ensure_dir(dst)
    try:
        r = subprocess.run([CV, "-unpack", flag, db_path, "-dir", dst],
                           capture_output=True, text=True, timeout=300,
                           cwd=os.path.dirname(CV), **hidden_kwargs())
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT(300s)"
    if r.returncode != 0:
        return False, f"rc={r.returncode} (0x{r.returncode & 0xFFFFFFFF:08X})"
    return True, ""


def build_11xx_lzhuf_db(files):
    """Manually build an 11xx DB with LZHUF-compressed file payloads.
    Entry layout: name\\0 + uncompressed(4) + offset(4) + size(4).
    File payload: lzhuf.encode(content) (textsize header + bitstream).
    目录条目**刻意不写**：cv 解含目录条目的 11xx 包会栈溢出（见 CV_UNPACK_BROKEN），
    这条用例的目的正是"让 cv 也能读到一个 11xx 包"，所以避开它已知的崩溃路径。"""
    header = bytearray()
    data = bytearray()
    for rel, content, is_dir in files:
        if is_dir:
            continue
        comp = stalker_fs.lzhuf.encode(content)
        path = rel.replace("/", "\\")
        header += path.encode("cp1251") + b"\x00"
        header += struct.pack("<III", 0, 8 + len(data), len(comp))  # uncompressed=0
        data += comp
    comp_header = stalker_fs.lzhuf.encode(bytes(header))
    db = struct.pack("<II", 0, len(data)) + bytes(data)
    db += struct.pack("<I", 0x80000001) + struct.pack("<I", len(comp_header)) + comp_header
    return bytes(db)


def run_format(fmt, flag, files):
    """对一个格式跑 A / B / C 三个方向。files 已含目录条目。"""
    fmt_dir = os.path.join(OUT, fmt)
    ensure_dir(fmt_dir)
    src_tree = os.path.join(fmt_dir, "src")
    write_source_tree(files, src_tree)
    want_dirs = set(dirs_of(files))

    # ── 方向 A：cv 封包 → 工具解包 ────────────────────────────────────────
    cv_db = os.path.join(fmt_dir, f"cv_{fmt}.db")
    ok_pack, pack_info = cv_pack(src_tree, flag, cv_db)
    if not ok_pack:
        mark("SKIP", fmt, "A cv封→工具解", pack_info)
    else:
        raw = open(cv_db, "rb").read()
        tk_out = os.path.join(fmt_dir, "A_tk_out")
        shutil.rmtree(tk_out, ignore_errors=True)
        n, got_dirs = toolkit_unpack(raw, fmt, tk_out)
        # 忽略大小写（cv 封包转小写）；内容仍须逐字节一致
        ok = compare_trees_ci(src_tree, tk_out, "A 工具解出的文件")
        # 目录条目：cv 只写"直接含文件的目录"，所以
        #   * 这些叶子目录**必须**被工具认出来（缺了就是引擎漏读目录条目）；
        #   * 工具报出来的目录必须都是源里真实存在的（多了就是解析出错）；
        #   * 中间层目录**不作要求**（cv 根本没写，不能算引擎的错）。
        missing = leaf_dirs(files) - got_dirs
        extra = {d for d in got_dirs if d not in all_dirs(files)}
        dir_ok = not missing and not extra
        if missing:
            log(f"    A 叶子目录条目缺失: {sorted(missing)[:5]}")
        if extra:
            log(f"    A 出现了源里不存在的目录条目: {sorted(extra)[:5]}")
        if ok and dir_ok:
            mark("PASS", fmt, "A cv封→工具解", f"cv {pack_info}，工具解出 {n} 文件")
        else:
            mark("FAIL", fmt, "A cv封→工具解", f"文件一致={ok} 目录条目={dir_ok}")

    # ── 方向 B：工具封包 → cv 解包 ────────────────────────────────────────
    db = stalker_fs.pack_db(files, fmt)
    tool_db = os.path.join(fmt_dir, f"tool_{fmt}.db")
    with open(tool_db, "wb") as f:
        f.write(db)
    cv_out = os.path.join(fmt_dir, "B_cv_out")
    shutil.rmtree(cv_out, ignore_errors=True)
    ok_un, un_info = cv_unpack(tool_db, flag, cv_out)
    if not ok_un and fmt in CV_UNPACK_BROKEN:
        mark("SKIP", fmt, "B 工具封→cv解", f"{un_info}；已知 cv 缺陷：{CV_UNPACK_BROKEN[fmt]}")
    elif not ok_un:
        mark("FAIL", fmt, "B 工具封→cv解", f"cv 解包失败 {un_info}")
    else:
        ok = compare_trees(src_tree, cv_out, "B cv解出的文件")
        dir_ok = want_dirs <= dirs_on_disk(cv_out)   # cv 应把目录也建出来
        if not dir_ok:
            log(f"    B 目录缺失: {sorted(want_dirs - dirs_on_disk(cv_out))[:5]}")
        if ok and dir_ok:
            mark("PASS", fmt, "B 工具封→cv解", f"工具封 {len(db)}B")
        else:
            mark("FAIL", fmt, "B 工具封→cv解", f"文件一致={ok} 目录完整={dir_ok}")

    # ── 方向 C：工具封包 → 工具解包（自洽）───────────────────────────────
    tk_out2 = os.path.join(fmt_dir, "C_tk_out")
    shutil.rmtree(tk_out2, ignore_errors=True)
    n2, got_dirs2 = toolkit_unpack(db, fmt, tk_out2)
    ok2 = compare_trees(src_tree, tk_out2, "C 工具解出的文件")
    dir_ok2 = got_dirs2 >= want_dirs
    if not dir_ok2:
        log(f"    C 目录条目缺失: {sorted(want_dirs - got_dirs2)[:5]}")
    if ok2 and dir_ok2:
        mark("PASS", fmt, "C 工具封→工具解", f"{n2} 文件")
    else:
        mark("FAIL", fmt, "C 工具封→工具解", f"文件一致={ok2} 目录条目完整={dir_ok2}")


def run_11xx_lzhuf(files):
    """11xx LZHUF 载荷专项：工具构造（不含目录条目）→ cv 解 + 工具解，两边都要对。

    这是**唯一**能让 cv 读到一个 11xx 包的用例（cv 自己封不出 11xx，
    解含目录条目的 11xx 包又会栈溢出）。
    """
    fmt = "11xx"
    d = os.path.join(OUT, "11xx_lzhuf")
    ensure_dir(d)
    payload = [f for f in files if not f[2] and f[1]]     # 跳过目录与空文件
    src_tree = os.path.join(d, "src")
    write_source_tree(payload, src_tree)

    db = build_11xx_lzhuf_db(payload)
    db_path = os.path.join(d, "toolkit_11xx_lzhuf.db")
    with open(db_path, "wb") as f:
        f.write(db)

    cv_out = os.path.join(d, "cv_out")
    shutil.rmtree(cv_out, ignore_errors=True)
    ok_un, un_info = cv_unpack(db_path, "-11xx", cv_out)
    if not ok_un:
        mark("FAIL", fmt, "LZHUF 工具封→cv解", f"cv 解包失败 {un_info}")
    else:
        mark("PASS" if compare_trees(src_tree, cv_out, "LZHUF cv解出的文件") else "FAIL",
             fmt, "LZHUF 工具封→cv解", f"工具封 {len(db)}B（载荷 LZHUF 压缩）")

    tk_out = os.path.join(d, "tk_out")
    shutil.rmtree(tk_out, ignore_errors=True)
    n, _dirs = toolkit_unpack(db, fmt, tk_out)
    mark("PASS" if compare_trees(src_tree, tk_out, "LZHUF 工具解出的文件") else "FAIL",
         fmt, "LZHUF 工具封→工具解", f"{n} 文件")


def run_cv_filename_codepage():
    """把 cv 的"文件名走本机 ANSI 代码页"这条行为**显式化**（真实数据测出来的）。

    **两个名字各测一遍**（2026-09-12 外部审计后的加固）：
      * `имя_тест_кириллица.txt` —— ACP 转出来含 `?`(U+003F)，Win32 非法字符 → cv 建不出文件；
      * `Сценарий windows.cmd`    —— ACP 转出来是**合法**的乱码名 → cv 会照写。
    为什么必须两个都测：只测第一个的话，"预测名算错"会**碰巧躲过** —— 旧实现用
    `locale.getpreferredencoding(False)`（本机 utf-8）预测，两个名字都落进"没建出文件"
    分支，于是那个真缺陷一直没暴露（实测：第一个名字预测 `'__.txt'`、cv 实际含 `?`，
    巧合一致；第二个名字预测 `' windows.cmd'`、cv 实际 `'仰屙囵栝 windows.cmd'` → 会误报 FAIL）。

    判定（每个名字一份）：
      * 本机 ANSI == cp1251 → cv 原名保持 → **PASS**
      * 本机 ANSI != cp1251 → **SKIP**（附实测名与预测名），因为这是 cv 的代码页行为、非引擎问题
      * 本机 ANSI == cp1251 却仍然变了 → **FAIL**（与模型矛盾，必须查）
    """
    fmt, flag = "xdb", "-xdb"
    d = os.path.join(OUT, "filename_cp")
    ensure_dir(d)
    for name in ("имя_тест_кириллица.txt", "Сценарий windows.cmd"):
        _cv_filename_case(name, fmt, flag, d)


def classify_cv_name(name, got, predicted=None):
    """判定 cv 侧的西里尔文件名结果 → `(kind, detail)`。纯函数，便于探针直接锁。

    判定表（`got` = cv 实际落盘的名字集合）：
      * 原名在 → **PASS**；
      * 预测的乱码名在 → **SKIP**（cv 自身的代码页行为，非引擎问题；本机 ANSI 若是 cp1251 则算 FAIL）；
      * 预测名含 `?`(U+003F) → **SKIP** 并说明"Win32 非法字符导致 CreateFileW 失败"
        （**不是**"字节被丢弃"：无效前导字节会变成私用区字符 U+F8F5）；
      * 什么都没落盘 → **SKIP**（附预测名）；
      * 落了别的名字 → **FAIL**（模型与实测矛盾，必须查）。
    """
    if predicted is None:
        predicted = cv_written_name(name)
    not_ru = ANSI_CP.lower().replace("-", "") != "cp1251"
    tag = "SKIP" if not_ru else "FAIL"
    if name in got:
        return "PASS", f"本机 ANSI={ANSI_CP}，cv 原名保持：{name!r}"
    if predicted is not None and predicted in got:
        return tag, (f"本机 ANSI={ANSI_CP} ≠ cp1251：cv 把 {name!r} 按代码页写成了乱码名 "
                     f"{predicted!r}（cv 自身行为，非引擎问题）")
    if predicted is not None and "?" in predicted:
        return tag, (f"本机 ANSI={ANSI_CP} ≠ cp1251：预测名 {predicted!r} 含 '?'(U+003F) —— "
                     f"Win32 文件名非法字符，CreateFileW 失败、cv 静默跳过（这才是「cv 侧少文件」"
                     f"的原因；不是「字节被丢弃」：无效前导字节会变成私用区字符 U+F8F5）")
    if not got:
        return tag, (f"本机 ANSI={ANSI_CP} ≠ cp1251：cv 连文件都没建出来（预测名 {predicted!r}）")
    return "FAIL", (f"cv 写出的名字既非原名也非预测值：实际 {sorted(got)[:3]}，"
                    f"预测 {predicted!r}")


def _cv_filename_case(name, fmt, flag, d):
    """单个西里尔文件名的"工具封 → cv 解"对照（判定走 classify_cv_name）。"""
    payload = b"cyrillic filename payload\n"
    db = stalker_fs.pack_db([(name, payload, False)], fmt)
    db_path = os.path.join(d, "tool_%d.db" % len(name))
    with open(db_path, "wb") as f:
        f.write(db)

    # 工具侧：必须能原名读出（这是引擎能力的正向断言，与 cv 无关）
    tk_out = os.path.join(d, "tk_out_%d" % len(name))
    shutil.rmtree(tk_out, ignore_errors=True)
    n, _dirs = toolkit_unpack(db, fmt, tk_out)
    tk_ok = os.path.isfile(os.path.join(tk_out, name))
    mark("PASS" if tk_ok and n == 1 else "FAIL", "文件名·工具侧",
         f"工具原名读出 {name!r} = {tk_ok}")

    cv_out = os.path.join(d, "cv_out_%d" % len(name))
    shutil.rmtree(cv_out, ignore_errors=True)
    ok_un, un_info = cv_unpack(db_path, flag, cv_out)
    if not ok_un:
        mark("SKIP", "文件名·cv 侧", f"cv 解包失败 {un_info}")
        return
    got = set()
    for dp, _dns, fns in os.walk(cv_out):
        for fn in fns:
            got.add(os.path.relpath(os.path.join(dp, fn), cv_out).replace("\\", "/"))
    kind, detail = classify_cv_name(name, got)
    mark(kind, "文件名·cv 侧", detail)


def main():
    args = sys.argv[1:]
    strict = "--strict" in args
    if strict:
        args = [a for a in args if a != "--strict"]
    if args:
        raise SystemExit("用法: python cross_validate.py [--strict]"
                         "（--strict = 要求 100% 覆盖率：任何因 cv 侧限制而"
                         "无法比对的项也算失败）")
    if not os.path.isfile(CV):
        raise SystemExit(f"converter.exe not found: {CV}")
    ensure_dir(OUT)

    files = with_dirs(load_source_files() + generate_sample_files())
    log(f"源集合：{sum(1 for _p, _d, d in files if not d)} 文件 + "
        f"{sum(1 for _p, _d, d in files if d)} 目录条目")

    for fmt, flag in FORMATS:
        log(f"=== {fmt} ===")
        run_format(fmt, flag, files)

    log("=== 11xx LZHUF 载荷专项（不含目录条目，cv 唯一能读 11xx 的路径）===")
    run_11xx_lzhuf(files)

    log("=== 文件名代码页：cv 走本机 ANSI，不保证与归档的 cp1251 一致 ===")
    run_cv_filename_codepage()

    print()
    print("=" * 68)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    # 覆盖率：单位是"比对项"（一个格式 × 一个方向算一项；文件名代码页专项各算一项）。
    # 所有 SKIP 都是 cv 侧限制（不支持封包 / 11xx 栈溢出 / 名字非法），逐条列在下面。
    print(coverage_line(len(PASS) + len(FAIL), len(PASS) + len(FAIL) + len(SKIP),
                        len(SKIP), "全是 cv 侧限制（见下方清单）"))
    if SKIP:
        print("跳过项（不是通过，只是没测成）：")
        for s in SKIP:
            print("  - " + s)
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print("  - " + f)
    print("=" * 68)
    if not FAIL:
        print("ALL CROSS-VALIDATION PASSED" + ("（含 SKIP）" if SKIP else ""))
    else:
        print("CROSS-VALIDATION FAILED; see messages above")
    if strict and SKIP:
        print("--strict：%d 个不可比对项 → 判红（默认模式下它们只列明、不判红）" % len(SKIP))
    # 本次运行自己的工作目录自己收拾（OUT 由 mkdtemp 创建，独占）。
    shutil.rmtree(OUT, ignore_errors=True)
    sys.exit(verdict_exit_code(strict, len(FAIL), len(SKIP)))


if __name__ == "__main__":
    main()
