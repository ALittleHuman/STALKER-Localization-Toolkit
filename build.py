# -*- coding: utf-8 -*-
"""
Build STALKER Localization Toolkit with PyInstaller (onedir).

Usage:
    python build.py                          # 构建到 builds/build_N（默认）
    python build.py --out DIR                # 构建到指定目录
    python build.py --version 1.2.0          # 指定基础版本号（写回）
    python build.py --prerelease BETA.1      # 附预发布标记（写回；清空用 --prerelease ""）
    python build_gui.py                      # 带界面的构建器（推荐）

命名规则：
    * 外层目录恒为 `builds/build_N`（N = `toolkit_base.BUILD_COUNT`）——**不带版本号**，
      这样翻 builds/ 时按编号排序不会被版本串打断；
    * 版本号体现在**产物内侧的应用名**上：
          builds/build_2/STALKER Localization Toolkit 1.0.0 BETA.1/
          builds/build_2/STALKER Localization Toolkit 1.0.0 BETA.1.exe
      用户解压/移动后仍能一眼看出是哪个版本，多版本也可并排共存。

版本号与标记（都在 `toolkit_base.py`，同一处）：
    * `APP_VERSION`    基础版本，如 "1.0.1"；
    * `APP_PRERELEASE` 预发布标记，如 "ALPHA.1"（""=无标记）；
    * `--version` / `--prerelease` 都会**写回**这两行（与 build GUI 的"保存"同一实现），
      不带参数直接构建则沿用上次保存的值 —— 标记不会每次重置成"无"；
    * **不给 `--prerelease` 时标记的序号自动 +1**：按 (完整版本串, 标记名) 各自
      计数（`toolkit_base.PRERELEASE_COUNTS`，见 `toolkit_version.next_prerelease`），
      因此连续构建不用每次手改序号；显式给了 `--prerelease` 则原样使用且
      **不动计数**（手工输入优先，与构建次数同一条规矩）；
    * 运行时标题/日志也读这两行，因此产物叫什么、界面就显示什么。

构建计数 `toolkit_base.BUILD_COUNT` 与上面两项**并列写回同一份文件**：
产物编号和版本号/标记合起来才是"这次构建的状态"，分散存放必然对不上。

构建事务（用户口径 2026-09-12）——**存在的构建都是成功的构建**：
    * 构建前自动保存（不再需要 GUI 上那个"保存"按钮），并把四项状态
      （版本号 / 标记 / 构建次数 / 标记计数）拍一张**快照**；
    * 成功 → 什么都不动，删掉快照文件；
    * 失败 → 四项**精确回退**到快照，并把这次构建的目录按
      `builds/FAIL/build_<构建数>_<年>_<月>_<日>_<时>_<分>_<秒>/` 归档
      （产物为空则删掉该目录，日志直接落在 `builds/FAIL/` 下，日志与目录同名）；
    * 构建过程中的**全部输出**（自身打印 + PyInstaller 的管道输出）落在日志里，
      成功即丢、失败即随目录归档；
    * 崩溃/强杀留下的快照，下次构建开始时自动回退（不白烧一个编号）。

Plugins ship with the bundle: every plugins/*.py present at build time is copied
into <bundle>/plugins (next to the exe — that is where the loader scans), the
closed-source plugins/nlc_sqfs.py **included** (it is only moved out while
PyInstaller runs, so it is never frozen into the exe, but it does ship).
ffmpeg.exe / ffprobe.exe are copied next to the exe when present locally.
"""
import contextlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))

# App constants come from the toolkit itself.
sys.path.insert(0, BASE)
from toolkit import APP_NAME  # noqa: E402
import toolkit_version as VER  # noqa: E402
from toolkit_platform import hidden_kwargs  # noqa: E402

BUILDS_DIR = os.path.join(BASE, "builds")
# 失败归档目录名与"未收尾快照"文件名（快照放 builds/ 而不是 temp/：
# temp/build 是 PyInstaller 的工作目录、构建结束就被删，撑不到"下次启动"；
# builds/ 是产物区，CI 的 cleanup() 也不碰它）。
FAIL_DIRNAME = "FAIL"
SNAPSHOT_NAME = ".build_snapshot.json"


def next_build_dir():
    """递增 `toolkit_base.BUILD_COUNT` 并创建本次默认产物目录。

    目录名恒为 `builds/build_N`（编号来自 `toolkit_base.BUILD_COUNT` —— 计数的
    单一事实来源，与 APP_VERSION / APP_PRERELEASE 并列，读写都在 toolkit_version）。
    **版本号不放这里**：它体现在产物内侧的应用名上（见 `app_name_for()`）——
    `builds/build_2/STALKER Localization Toolkit 1.0.0 BETA.1/`。
    这样同一轮构建的目录始终叫 build_N，翻 builds/ 时按编号排序不会被版本串打断。

    只在真正执行构建时调用 —— `import build` 不再有副作用
    （此前 import 就会 +1 并建目录，IDE 索引 / 测试导入都会误触发）。

    `builds/` 下的历史版本是**有意保留的对照物**，因此这里绝不覆盖既有目录：
    计数被手改成已用过的值、或那一行坏掉（当 0 读）时，往后找第一个空号。
    """
    count = VER.current_build_count()

    while True:
        count += 1
        out = os.path.join(BUILDS_DIR, f"build_{count}")
        if not os.path.exists(out):
            break

    VER.save_build_count(count)
    os.makedirs(out, exist_ok=True)
    return out


def build_time_stamp(when=None):
    """归档用的时刻串：`YYYY_MM_DD_HH_MM_SS`（本地时间，精确到秒）。

    年份用 4 位：可读、按名字就能排序、跨世纪不歧义。用户给的字面格式是
    `build_x_xx_xx_xx_xx_xx_xx`（构建数 + 6 组），4 位年份只是把其中一组写全。
    """
    return time.strftime("%Y_%m_%d_%H_%M_%S", time.localtime(when))


def fail_entry_name(number, stamp=None):
    """失败归档名：`build_<构建数>_<年>_<月>_<日>_<时>_<分>_<秒>`。

    日志文件与它**同名**（见 `archive_failed`）—— 用户口径：日志命名规则和文件夹一样。
    """
    return f"build_{number}_{stamp or build_time_stamp()}"


def build_dir_number(path):
    """从 `builds/build_N` 取出 N；不是这个形状就返回 None。"""
    m = re.fullmatch(r"build_(\d+)", os.path.basename(os.path.normpath(path)))
    return int(m.group(1)) if m else None


def _unique_path(path):
    """目录/文件已存在时加 `_2`/`_3`… —— 失败现场**不许互相覆盖**。

    时间戳精确到秒，但同一秒里连点两次"开始构建"是可能的（尤其失败很快时）。
    若直接 os.replace，前一次的现场会被无声吃掉，正是本机制要避免的事。
    """
    if not os.path.exists(path):
        return path
    for i in range(2, 1000):
        cand = f"{path}_{i}"
        if not os.path.exists(cand):
            return cand
    raise RuntimeError(f"同名归档太多，放弃: {path}")


def dir_stats(path):
    """产物目录的 (文件数, 字节数)；目录不存在或读不动时给 (0, 0)。"""
    files = size = 0
    if os.path.isdir(path):
        for dp, _dn, fn in os.walk(path):
            for n in fn:
                files += 1
                try:
                    size += os.path.getsize(os.path.join(dp, n))
                except OSError:
                    pass
    return files, size


def is_inside(path, parent):
    """path 是否在 parent 之下（同卷比较；跨盘/形状不对一律 False）。"""
    try:
        p = os.path.abspath(path)
        q = os.path.abspath(parent)
        return os.path.commonpath([p, q]) == q and p != q
    except (ValueError, OSError):
        return False


def archive_failed(target, number, log_text, reason, *, stamp=None, builds_dir=None,
                   elapsed=None):
    """把一次失败的构建归档到 `builds/FAIL/`，返回结果字典（供打印与探针断言）。

    规则（用户口径）：
      * 产物目录**非空** → 整体移入 `FAIL/<名>/`，日志写在**该目录内**、与目录同名；
      * 产物目录**为空/不存在** → 删掉它，日志直接落在 `FAIL/<名>.log`；
      * 名字 = `build_<构建数>_<年>_<月>_<日>_<时>_<分>_<秒>`，同名加 `_2`。

    **只动 `builds/` 下的东西**：`--out` 指向用户自己的目录时绝不移除/搬走任何文件
    （历史上就因为 rmtree 用户目录出过一次事故），那种情况只把日志放进 FAIL。
    日志开头永远有一段现场信息（版本/编号/原因/耗时/体积），即使日志正文为空也有据可查。
    """
    builds_dir = builds_dir or BUILDS_DIR
    fail_dir = os.path.join(builds_dir, FAIL_DIRNAME)
    os.makedirs(fail_dir, exist_ok=True)
    entry = os.path.basename(_unique_path(os.path.join(fail_dir, fail_entry_name(number, stamp))))

    files, size = dir_stats(target)
    moved_to = None
    deleted = False
    if os.path.isdir(target) and files:
        if is_inside(target, builds_dir):
            dst = os.path.join(fail_dir, entry)
            shutil.move(target, dst)          # 同卷；跨卷时 move 会自己复制
            moved_to = dst
        # 否则：这是用户用 --out 指定的目录 → 原地不动
    elif os.path.isdir(target) and is_inside(target, builds_dir):
        shutil.rmtree(target, ignore_errors=True)   # 一个文件都没产出 → 连目录一起删
        deleted = True

    header = [
        "=== 构建失败现场 ===",
        f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"构建编号: {number}",
        f"归档名: {entry}",
        f"产物目录: {target}",
        f"产物文件数: {files}    产物体积: {size} 字节",
        f"耗时: {'%.1f 秒' % elapsed if elapsed is not None else '未知'}",
        f"失败原因: {reason}",
        f"目录处置: {'移入 FAIL' if moved_to else ('已删除（无产出）' if deleted else '原地保留（--out 用户目录）')}",
        "",
    ]
    if moved_to:
        log_path = os.path.join(moved_to, entry + ".log")
    else:
        log_path = os.path.join(fail_dir, entry + ".log")
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(header))
            f.write(log_text or "（构建过程没有输出）\n")
    except OSError as e:
        print(f"[FAIL] 日志写入失败: {e}")
        log_path = None
    return {"entry": entry, "moved_to": moved_to, "deleted": deleted,
            "log_path": log_path, "files": files, "bytes": size}


# ── 未收尾快照（崩溃/强杀自愈）────────────────────────────────────────
def snapshot_path():
    return os.path.join(BUILDS_DIR, SNAPSHOT_NAME)


def write_pending_snapshot(snap, extra=None):
    """构建前把快照落盘：进程被强杀也能在下次构建时把编号回退。"""
    data = dict(snap)
    data["_written"] = time.strftime("%Y-%m-%d %H:%M:%S")
    if extra:
        data.update(extra)
    try:
        os.makedirs(BUILDS_DIR, exist_ok=True)
        with open(snapshot_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"注意：快照写入失败（崩溃时不会自动回退）: {e}")
        return False


def read_pending_snapshot():
    try:
        with open(snapshot_path(), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def clear_pending_snapshot():
    try:
        os.remove(snapshot_path())
    except OSError:
        pass


def recover_pending_snapshot():
    """上次构建没正常收尾（崩溃 / 被强杀）→ 先回退到那张快照，再开始新构建。

    这是构建器自己的自愈：不清的话，那一次失败的写入会永久留在磁盘上
    （版本号涨了、编号烧了），而"失败的构建不该留下痕迹"正是本次改造的要点。
    """
    snap = read_pending_snapshot()
    if not snap:
        return None
    print("[恢复] 上次构建没有正常结束，先回退到当时的快照：")
    print(f"       快照时间 {snap.get('_written')}  版本 {snap.get('version')}"
          f" {snap.get('prerelease') or '无'}  构建次数 {snap.get('build_count')}")
    ok, msgs = VER.restore_state(snap)
    for m in msgs:
        print("       " + m)
    clear_pending_snapshot()
    if not ok:
        print("[恢复] 有项目回退失败（见上），请人工核对 toolkit_base.py")
    return snap


# ── 构建日志（自身输出 + 子进程输出）──────────────────────────────────
class _BuildLog:
    """把构建期间的全部输出**同时**写到真实 stdout 与内存缓冲。

    为什么要 tee：PyInstaller 是子进程，若把它的 stdout 直接继承给控制台，
    Python 层就拿不到那部分输出，失败时"日志"会缺掉最关键的一段（报错原因）。
    所以子进程改成管道 + 逐行转发（控制台/GUI 仍**实时**可见），
    再由本类统一收集；成功即丢弃，失败即随 FAIL 目录归档。
    """

    def __init__(self):
        self._buf = []
        self._real = None

    def text(self):
        return "".join(self._buf)

    @contextlib.contextmanager
    def capture(self):
        old_out, old_err = sys.stdout, sys.stderr
        self._real, self._real_err = old_out, old_err
        sys.stdout = sys.stderr = self
        try:
            yield self
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def write(self, s):
        if not isinstance(s, str):
            s = str(s)
        self._buf.append(s)
        try:
            if self._real is not None:
                self._real.write(s)
                self._real.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            if self._real is not None:
                self._real.flush()
        except Exception:
            pass

    def isatty(self):
        return False


def run_logged(cmd, cwd):
    """跑子进程并把输出逐行转发到当前 stdout（被 `_BuildLog` 捕获）。

    与 `subprocess.check_call` 的区别只有一个：多了这层转发 —— 于是失败时我们
    手里有完整日志，而控制台/GUI 依旧是实时的。非 0 退出抛 CalledProcessError。
    """
    proc = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", bufsize=1)
    assert proc.stdout is not None
    for line in proc.stdout:
        print(line.rstrip("\n"), flush=True)
    code = proc.wait()
    if code != 0:
        raise subprocess.CalledProcessError(code, cmd)
    return code


def finish_build(*, ok, reason, target, number, snap, log_text, elapsed=None,
                 out_override=False, builds_dir=None):
    """构建收尾的**唯一出口**：成功提交 / 失败回退 + 归档。

    只有一个出口是刻意的：先前"写回在构建之前、失败什么也不做"的写法，
    意味着任何一条新的失败路径都可能忘记回退；把两条路径收在这里，
    "忘了回退"从结构上就不容易发生。

    成功 = 调用方已确认产出（`build()` 在 bundle/exe 缺失时会抛）。
    """
    if ok:
        clear_pending_snapshot()
        print("构建成功：版本号与构建次数保持本次值（快照已清除）")
        return {"ok": True, "archived": None, "rollback_ok": None}
    print(f"\n[FAIL] 构建失败：{reason}")
    rollback_ok, msgs = VER.restore_state(snap)
    print("[回退] 版本号 / 标记 / 构建次数 / 标记计数 → 构建前：")
    for m in msgs:
        print("       " + m)
    if not rollback_ok:
        print("[回退] 有项目失败（见上）—— 请人工核对 toolkit_base.py")
    info = archive_failed(target, number, log_text, reason, elapsed=elapsed,
                          builds_dir=builds_dir)
    clear_pending_snapshot()
    if info["moved_to"]:
        print(f"[FAIL] 失败现场已归档: {info['moved_to']}")
    elif info["deleted"]:
        print(f"[FAIL] 无产出，已删除 {target}")
    else:
        print(f"[FAIL] 产物目录原地保留（--out 指定的用户目录）: {target}")
    if info["log_path"]:
        print(f"[FAIL] 构建日志: {info['log_path']}")
    print(f"[FAIL] 构建编号 {number} 与版本号均已回到构建前，下次构建不会跳号"
          if rollback_ok else "[FAIL] 回退未完全成功，请人工核对")
    return {"ok": False, "archived": info, "rollback_ok": rollback_ok}


def app_name_for(prerelease="", base_version=None):
    """本次构建的**应用名**（= 产物内侧的文件夹名与 exe 名，不含扩展名）。

    命名规则：`<APP_NAME> <完整版本串>`，例如
        STALKER Localization Toolkit 1.0.0
        STALKER Localization Toolkit 1.0.0 BETA.1

    版本号放在应用名后面（而不是 `build_N` 后面），是为了让**产物自己**带版本：
    用户解压/移动后仍能一眼看出是哪个版本，且多个版本可以并排放在同一处而不冲突。
    目录名仍然是 build_N，翻 builds/ 时按编号排序不会被版本串打断。
    """
    return f"{APP_NAME} {VER.full_version(base_version, prerelease)}"


def bundle_paths(out_dir, app_name):
    """产物内侧目录与 exe 路径。

    单独抽出来是因为这两条路径必须与 PyInstaller 的 `--name` 用**同一个**
    `app_name` —— 应用名现在带版本串，任何一处漏改都会让构建在"找不到产物"
    处失败（而那时已经跑完几分钟的 PyInstaller）。`run_build_probe.py` 直接
    对这三个值做一致性断言。
    """
    bundle = os.path.join(out_dir, app_name)
    return bundle, os.path.join(bundle, f"{app_name}.exe")


def ensure_pyinstaller():
    # 用 find_spec 而不是 `import PyInstaller`：后者只为探测存在性，
    # 却会因为"导入后未使用"被静态检查报成死导入（pyflakes 不认 noqa）。
    if importlib.util.find_spec("PyInstaller") is None:
        print("PyInstaller not found, installing...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("PyInstaller installed.")


def write_version_info(path, version_tuple, exe_name=None):
    """Windows 版本资源：四段纯数字（不能带字母），由版本模块推导。

    `exe_name` 用于 OriginalFilename —— 它必须与实际 exe 文件名一致，
    而应用名现在带版本串，不能再写死 `APP_NAME.exe`。
    """
    v = ", ".join(str(int(x)) for x in version_tuple)
    original = exe_name or f"{APP_NAME}.exe"
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({v}),
    prodvers=({v}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'ALittleHuman'),
         StringStruct('FileDescription', '{APP_NAME}'),
         StringStruct('FileVersion', '{v.replace(', ', '.')}'),
         StringStruct('InternalName', '{APP_NAME}'),
         StringStruct('LegalCopyright', 'ALittleHuman'),
         StringStruct('OriginalFilename', '{original}'),
         StringStruct('ProductName', '{APP_NAME}'),
         StringStruct('ProductVersion', '{v.replace(', ', '.')}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def build(out_dir, prerelease="", base_version=None):
    ensure_pyinstaller()

    # 版本资源用四段数字；显示串（含预发布标记）进**应用名**，不进目录名。
    # base_version/prerelease 由调用方显式给：不要在保存之后再回头读模块状态，
    # 那条路依赖"写文件时同步了内存模块"，一旦不同步就会用旧值构建（实测踩到）。
    vtuple = VER.version_tuple(base_version, prerelease)
    vfull = VER.full_version(base_version, prerelease)
    app_name = app_name_for(prerelease, base_version)
    bundle_dir, exe_path = bundle_paths(out_dir, app_name)
    print(f"版本: {vfull}   (资源版本 {'%d.%d.%d.%d' % vtuple})")
    print(f"应用名: {app_name}")

    # Kill a stale running instance if it is locking previous build output.
    # 只按**精确 exe 名**匹配（先做形状校验，避免应用名被改坏后误杀无关进程），
    # 并且不再吞掉返回值：没找到进程时 taskkill 返回 128，属正常；其它非 0 打出来。
    # 注意：exe 名带版本串，所以这里只会结束**同一版本**的残留实例，
    # 不会误杀用户正在跑的其他版本。
    exe_name = f"{app_name}.exe"
    if sys.platform == "win32" and re.fullmatch(r"[\w.\- ]+\.exe", exe_name):
        proc = subprocess.run(
            ["taskkill", "/F", "/IM", exe_name],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            **hidden_kwargs(),
        )
        if proc.returncode == 0:
            print(f"已结束正在运行的 {exe_name}")
        elif proc.returncode != 128:
            print(f"taskkill 返回 {proc.returncode}: "
                  f"{(proc.stderr or proc.stdout or '').strip()}")

    # ★ 不整目录清空：`--out` 可以指向**任意既有目录**，而 `shutil.rmtree(out_dir)` 会把它
    #   静默清空 —— 指到 ~/Documents 这种地方就是数据丢失，且没有任何确认或提示。
    #   PyInstaller 自己带 `--noconfirm`，会替换它要写的那个产物子目录（<out>/<应用名>），
    #   所以这里只需要保证 out_dir 存在；已有内容一律不动，只提示一句。
    if os.path.isdir(out_dir):
        others = [n for n in os.listdir(out_dir) if n != app_name]
        if others:
            print(f"输出目录已存在其它内容，保持不变（只替换 {app_name}/）："
                  f"{', '.join(sorted(others)[:5])}"
                  f"{' …' if len(others) > 5 else ''}")
    os.makedirs(out_dir, exist_ok=True)

    # Remove caches before bundling so no .pyc of the closed-source
    # plugin can leak into the build.
    # 只清**活代码**的缓存：builds/ 是历史产物、backup/ 是重构前快照，
    # 它们是有意保留的对照物，不该被构建顺手改动。
    for dp, dn, fn in os.walk(BASE):
        dn[:] = [d for d in dn if d not in ("builds", "backup", "deps", ".git")]
        if "__pycache__" in dn:
            shutil.rmtree(os.path.join(dp, "__pycache__"), ignore_errors=True)
            dn.remove("__pycache__")

    temp_dir = os.path.join(BASE, "temp", "build")
    work_dir = os.path.join(temp_dir, "work")
    spec_dir = os.path.join(temp_dir, "spec")
    for d in (work_dir, spec_dir):
        os.makedirs(d, exist_ok=True)

    version_info = os.path.join(temp_dir, "version_info.txt")
    write_version_info(version_info, vtuple, exe_name=f"{app_name}.exe")

    # nlc_sqfs.py 仍只在 PyInstaller 期间移出：`--paths plugins` 会让 PyInstaller 有机会
    # 静态分析到它，而闭源件不该被冷冻进 exe。移出只影响 exe，不影响随包 —— 上面那份
    # 名单已经把它记下了，构建结束后照单复制到 exe 旁。
    nlc_src = os.path.join(BASE, "plugins", "nlc_sqfs.py")
    nlc_tmp = os.path.join(BASE, "nlc_sqfs.py.build_backup")
    nlc_backed_up = False
    if os.path.isfile(nlc_src):
        os.replace(nlc_src, nlc_tmp)
        nlc_backed_up = True
        print("Temporarily moved plugins/nlc_sqfs.py out of PyInstaller's view.")

    try:
        cmd = [
            sys.executable, "-m", "PyInstaller",
            "--noconfirm", "--clean", "--onedir", "--windowed",
            "--name", app_name,
            "--icon", os.path.join(BASE, "app_icon.ico"),
            "--version-file", version_info,
            # sniff_encoding 里的 chardet 是**函数内延迟导入**，静态分析有时
            # 抓不稳，显式声明为隐藏导入；未安装时 PyInstaller 只发 WARNING。
            "--hidden-import", "chardet",
            "--paths", os.path.join(BASE, "file_system"),
            "--paths", os.path.join(BASE, "font_pack"),
            "--paths", os.path.join(BASE, "plugins"),
            "--add-data", f"{os.path.join(BASE, 'apps')};apps",
            "--add-data", f"{os.path.join(BASE, 'file_system')};file_system",
            "--add-data", f"{os.path.join(BASE, 'font_pack')};font_pack",
            "--add-data", f"{os.path.join(BASE, 'deps')};deps",
            "--add-data", f"{os.path.join(BASE, 'app_icon.ico')};.",
            "--distpath", out_dir,
            "--workpath", work_dir,
            "--specpath", spec_dir,
            os.path.join(BASE, "stalker_toolkit.py"),
        ]
        print("Running PyInstaller...")
        run_logged(cmd, BASE)
    finally:
        if nlc_backed_up and os.path.isfile(nlc_tmp):
            os.replace(nlc_tmp, nlc_src)
            print("Restored plugins/nlc_sqfs.py.")
        shutil.rmtree(temp_dir, ignore_errors=True)

    # bundle_dir / exe_path 已在入口处按 app_name 算好（见 bundle_paths）
    if not os.path.isdir(bundle_dir):
        raise RuntimeError(f"Build output not found: {bundle_dir}")

    # Remove git placeholder files and any __pycache__ from the bundle.
    for dp, dn, fn in os.walk(bundle_dir):
        for f in fn:
            if f == ".gitkeep":
                os.unlink(os.path.join(dp, f))
        for d in dn:
            if d == "__pycache__":
                shutil.rmtree(os.path.join(dp, d), ignore_errors=True)

    # Runtime-writable directories live next to the exe, not inside _internal.
    for sub in ("plugins", "logs"):
        d = os.path.join(bundle_dir, sub)
        os.makedirs(d, exist_ok=True)
        print(f"Created {d}")

    # 插件随包：**就地过滤**后复制到 **exe 旁** —— 加载器扫的就是这个目录。
    # 不预先攒名单：复制发生在 nlc_sqfs.py 已经搬回来之后，所以它照样随包（用户口径：
    # 构建默认把 plugins/ 里的都带上；不带它的那一侧是 git，不是发布包）。过滤只排除
    # "永远不要的两类"：非 .py，以及 `_` 开头的辅助文件（与加载器自己的忽略规则一致）。
    # 不能用 `--add-data plugins;plugins` 代替：onedir 模式下它落在 `_internal/plugins`，
    # 而加载器只看 exe 旁的 plugins/，结果插件"在包里却看不见"。
    plugin_src = os.path.join(BASE, "plugins")
    bundled = []
    if os.path.isdir(plugin_src):
        for f in sorted(os.listdir(plugin_src)):
            if not f.endswith(".py") or f.startswith("_"):
                continue
            src = os.path.join(plugin_src, f)
            if not os.path.isfile(src):
                continue
            shutil.copy2(src, os.path.join(bundle_dir, "plugins", f))
            bundled.append(f)
    print("Plugins bundled: %d (%s)"
          % (len(bundled), ", ".join(bundled) if bundled else "none"))

    # logs/ 里放一个说明文件：既让目录非空（打包/拷贝时不会丢空目录），
    # 也把"每次启动一个新日志文件"的命名规范直接写给打开这个目录的人看。
    # 不要再造一个假的 runtime.log —— 真实日志由 toolkit_log 按启动时刻命名。
    logs_readme = os.path.join(bundle_dir, "logs", "README.txt")
    if not os.path.isfile(logs_readme):
        with open(logs_readme, "w", encoding="utf-8") as f:
            f.write(
                "本目录保存每次运行的日志。\n"
                "\n"
                "命名：runtime_YYYYMMDD_HHMMSS.log\n"
                "      YYYYMMDD_HHMMSS = 该次启动的时刻（精确到秒）。\n"
                "      每次启动程序都会新建一个文件，不会覆盖或追加旧日志。\n"
                "\n"
                "另外，程序里点「导出」会生成 log_YYYYMMDD_HHMMSS.txt，\n"
                "内容是当时界面上的简略日志 + 当次 runtime 日志的合集。\n"
            )

    for exe in ("ffmpeg.exe", "ffprobe.exe"):
        src = os.path.join(BASE, exe)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(bundle_dir, exe))
            print(f"Copied {exe} -> {bundle_dir}")

    if not os.path.isfile(exe_path):
        raise RuntimeError(f"exe not found: {exe_path}")

    print("Build complete.")
    print("Output:", bundle_dir)
    print("Exe:", exe_path)
    print("Version:", vfull)
    print("Note: all plugins/*.py bundled (incl. nlc_sqfs.py); only git excludes them.")
    return bundle_dir


def parse_args(argv):
    """解析 --out / --version / --prerelease。返回 (out, version, prerelease)。"""
    out = version = prerelease = None
    for flag in ("--out", "--version", "--prerelease"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                raise SystemExit(f"{flag} 需要一个参数")
            val = argv[i + 1]
            if flag == "--out":
                out = os.path.abspath(val)
            elif flag == "--version":
                version = val
            else:
                prerelease = val
    return out, version, prerelease


def main():
    out, version, prerelease = parse_args(sys.argv)

    # 0) 上次构建若没正常收尾（崩溃 / 被强杀），先把编号与版本号退回那张快照 ——
    #    否则那一次失败的写入会永久留在磁盘上（版本号涨了、编号烧了）。
    recover_pending_snapshot()

    # 本次构建的基础版本：命令行显式值优先，否则用**已保存值**（若上面刚回退过，
    # 这里读到的就是回退后的值 —— 顺序不能反）。注意不要"保存完再回头读模块状态"：
    # 那条路依赖写文件时同步了内存模块，一旦同步没发生（例如 BASE 被重定向）就会拿旧值构建。
    eff_base = version or VER.current_base_version()

    # 1) 快照：本次构建会推进四项状态（版本号 / 标记 / 构建次数 / 标记计数），
    #    失败时要精确退回。**在写入之前**拍 —— 这是"失败不消耗编号"的前提。
    snap = VER.snapshot_state()

    # 日志：构建期间的全部输出都进这里（成功即丢、失败随目录归档）
    log = _BuildLog()
    started = time.time()
    number = None
    target = None
    ok = True
    reason = None
    try:
        with log.capture():
            # 2) 构建前**自动保存**（GUI 上那个"保存版本号与标记"按钮已删除：
            #    它曾是第二条写盘路径，与"单一事实来源"相冲突）。
            #    标记也落盘的理由：产物名带标记，界面/标题/日志都得显示同一个。
            if prerelease is not None:
                # 显式给了标记：**原样使用**，并且完全不碰计数 —— 手工输入优先，
                # 与构建计数同一条规矩（手填的值不会被自动 ++ 悄悄改掉）。
                good, msg = VER.save_version(new_version=version,
                                             new_prerelease=prerelease)
                print(msg)
                if not good:
                    raise RuntimeError(msg)
                eff_pre = prerelease
            else:
                # 没给标记：按 (完整版本串, 标记名) 独立计数**自动 +1** 并写回。
                # 为什么推进点放在这里而不是界面里：只此一处，`python build.py` 直接跑
                # 与从构建器点「开始构建」才会得到同一套序号；构建器在自动模式下干脆
                # 不传 --prerelease（见 build_gui._marker_args），让这里来推。
                # 无标记（APP_PRERELEASE == ""）时返回 ""：没有可递增的东西，
                # 也不凭空造一个 —— 产物就该继续不带标记。
                eff_pre = VER.next_prerelease(base_version=eff_base, consume=True)
                if eff_pre:
                    good, msg = VER.save_version(new_version=version,
                                                 new_prerelease=eff_pre)
                    print(msg)
                    if not good:
                        raise RuntimeError(msg)
                elif version:
                    # 没有标记可推进，但版本号本身仍要落盘（与旧行为一致）
                    good, msg = VER.save_version(new_version=version)
                    print(msg)
                    if not good:
                        raise RuntimeError(msg)

            # 本次构建实际使用的值：命令行显式值优先，否则用上面算出的自增值。
            print(f"本次构建: {VER.full_version(eff_base, eff_pre)}"
                  f"（基础 {VER.normalize_base(eff_base) or eff_base}，"
                  f"标记 {eff_pre or '无'}）")

            # 只有用默认位置构建时才递增计数、才创建 build_N 目录。
            # 注：目录名不含版本号（版本号在产物内侧的应用名上），因此这里不需要 prerelease。
            target = out or next_build_dir()
            number = build_dir_number(target) or (snap.get("build_count") or 0) + 1
            # 快照落盘（崩溃自愈用）必须在真正开始构建之前
            write_pending_snapshot(snap, {"number": number, "target": target,
                                          "out_override": bool(out)})
            build(target, prerelease=eff_pre, base_version=eff_base)
    except BaseException as e:                       # noqa: BLE001 — 失败要归档，不挑类型
        ok = False
        reason = f"{type(e).__name__}: {e}"

    # 3) 收尾：两条路径的唯一出口（成功提交 / 失败回退 + 归档）
    res = finish_build(ok=ok, reason=reason, target=target, number=number, snap=snap,
                       log_text=log.text(), elapsed=time.time() - started,
                       out_override=bool(out))
    if not res["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
