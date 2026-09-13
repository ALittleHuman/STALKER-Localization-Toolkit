# -*- coding: utf-8 -*-
"""构建器自检（只读/临时目录，不触发真实 PyInstaller 构建）。

覆盖：
    * 版本模块：解析、组合、四段数字推导、写回（在临时副本上做）
    * 构建次数与标记序号：都存 `toolkit_base.py`（BUILD_COUNT / PRERELEASE_COUNTS），
      旧的两个计数文件已删除；读取容错与原子写都在副本上验证
    * build.py 的命令行参数解析
    * build_gui 的无头构造与交互逻辑（预览/解析/保存）

所有"写回 / 计数"用例都打在 **toolkit_base.py 临时副本** 上（重定向 `V.BASE`），
真仓库文件一个字节都不动。

用法: python run_build_probe.py   （退出码 0=全过）
"""
import ast
import json
import os
import shutil
import sys
import tempfile
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

PASS, FAIL, SKIP = [], [], []


def check(name, fn):
    """fn 抛异常即 FAIL；**显式返回 False 也算 FAIL**。

    早期只判异常，于是 `check("x", lambda: a == b)` 这类"纯布尔表达式"永远不会失败
    —— False 被静默丢弃，断言空转但 PASS 照加。返回 None 仍算通过。
    """
    try:
        r = fn()
    except Exception as e:
        FAIL.append(name)
        print("  FAIL %s -> %s: %s" % (name, type(e).__name__, e))
        for line in traceback.format_exc().strip().splitlines()[-3:]:
            print("       " + line.strip())
        return
    if r is False:
        FAIL.append(name)
        print("  FAIL %s -> 断言返回 False" % name)
        return
    PASS.append(name)
    print("  PASS %s" % name)


def skip(name, why=""):
    """记一条 SKIP：**不计 FAIL、不影响退出码**，但汇总里单独计数。

    SKIP 与 PASS 必须分得清（同仓 cross_validate.py 的纪律）：只有"环境不满足"
    （机器上没有可用桌面等）才允许走这里；真实失败必须进 FAIL。
    """
    SKIP.append(name)
    print("  SKIP %s%s" % (name, ("   <- " + why) if why else ""))


# ── 临时副本工具 ────────────────────────────────────────────
# 版本号 / 标记 / 构建次数 / 标记序号现在都是 toolkit_base.py 里的模块级常量，
# 因此"别动真文件"的唯一做法就是：把 `toolkit_version.BASE` 指到临时目录，在
# 那份**副本**上读写（与 test_save_base_version 的做法一致）。历史上计数各存一个
# 独立文件、探针只要重定向那一个路径即可；现在存储变成源文件本身，重定向的
# 粒度也就变成了 BASE 本身 —— 探针改的是**副本**，真仓库一个字节都不动。
def _base_copy(dirpath, version="1.0.1", prerelease="",
               build_count=None, counts=None):
    """写一份 toolkit_base.py 临时副本，返回其路径。

    `build_count` / `counts` 给 None = **不写这一行**（模拟老文件 / 行被手删），
    给字符串 = 原样写进去（用来喂坏值）；`counts` 给 dict 则按 JSON 写。
    """
    os.makedirs(dirpath, exist_ok=True)
    path = os.path.join(dirpath, "toolkit_base.py")
    lines = ["# -*- coding: utf-8 -*-",
             '"""探针临时副本：真 toolkit_base.py 的替身。"""',
             'APP_NAME = "STALKER Localization Toolkit"',
             'APP_VERSION = "%s"' % version,
             'APP_PRERELEASE = "%s"' % prerelease]
    if build_count is not None:
        lines.append("BUILD_COUNT = %s" % build_count)
    if counts is not None:
        lines.append("PRERELEASE_COUNTS = %s"
                     % (json.dumps(counts, sort_keys=True)
                        if isinstance(counts, dict) else counts))
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write("\n".join(lines) + "\n")
    return path


def _set_base_line(path, pattern, line):
    """把副本里的某一行换成 `line`（没有该行就追加）—— 用来喂"缺失/损坏"情形。"""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    if pattern.search(src):
        src = pattern.sub(lambda _m: line, src, count=1)
    else:
        src = src.rstrip("\n") + "\n" + line + "\n"
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(src)


def _drop_base_line(path, pattern):
    """删掉副本里的某一行 —— 模拟"老文件还没有这个常量"。"""
    with open(path, encoding="utf-8") as f:
        src = f.read()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(pattern.sub("", src, count=1))


def _base_line(path, pattern):
    """取副本里某个常量行等号右侧的文本；没有该行返回 None。"""
    with open(path, encoding="utf-8") as f:
        m = pattern.search(f.read())
    return m.group(1).strip() if m else None


def _counts_in(path):
    """把副本里 PRERELEASE_COUNTS 那行解析成 dict；解析不了返回 None。"""
    import toolkit_version as V
    raw = _base_line(path, V._COUNTS_LINE_RE)
    if raw is None:
        return None
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return None


def _read_bytes(path):
    with open(path, "rb") as f:
        return f.read()


def test_version_module():
    import toolkit_version as V
    check("解析 1.0.0", lambda: V.parse_full_version("1.0.0") == ("1.0.0", ""))
    check("解析 v1.0.0", lambda: V.parse_full_version("v1.0.0") == ("1.0.0", ""))
    check("解析 1.0.0-beta.2", lambda: V.parse_full_version("1.0.0-beta.2") == ("1.0.0", "BETA.2"))
    check("解析 v1.0.0 BETA.1", lambda: V.parse_full_version("v1.0.0 BETA.1") == ("1.0.0", "BETA.1"))
    check("解析 1.2-beta1 补位", lambda: V.parse_full_version("1.2-beta1") == ("1.2.0", "BETA.1"))
    check("解析 2.0.0-rc.3", lambda: V.parse_full_version("2.0.0-rc.3") == ("2.0.0", "RC.3"))
    check("无法解析的串返回 None", lambda: V.parse_full_version("garbage") == (None, ""))
    check("非法基础版本返回 None", lambda: V.normalize_base("abc") is None)

    check("组合：带标记", lambda: V.full_version("1.0.0", "BETA.1") == "1.0.0 BETA.1")
    check("组合：无标记", lambda: V.full_version("1.0.0", "") == "1.0.0")
    check("标记别名归一（b1 → BETA.1）", lambda: V.format_prerelease("b1") == "BETA.1")
    check("标记别名归一（alpha → ALPHA.1）", lambda: V.format_prerelease("alpha") == "ALPHA.1")

    check("四段数字：无标记", lambda: V.version_tuple("1.0.0", "") == (1, 0, 0, 0))
    check("四段数字：BETA.1 → 第4段=1", lambda: V.version_tuple("1.0.0", "BETA.1") == (1, 0, 0, 1))
    check("四段数字：RC.3 → 第4段=3", lambda: V.version_tuple("2.1.0", "RC.3") == (2, 1, 0, 3))
    check("四段数字恒为 4 项纯整数",
          lambda: all(isinstance(x, int) for x in V.version_tuple("1.2.3", "ALPHA.9")))

    # Windows 版本资源只能是四段纯数字：带 ALPHA/BETA/RC 标记时也必须如此，
    # 否则 PyInstaller 会拒绝 version-file，或者 exe 属性里显示不出东西。
    def _version_info_numeric():
        import re
        import build
        tmp = tempfile.mkdtemp(prefix="verinfo_probe_")
        try:
            path = os.path.join(tmp, "version_info.txt")
            for pre in ("", "BETA.1", "ALPHA.3", "RC.12"):
                build.write_version_info(path, V.version_tuple(prerelease=pre))
                txt = open(path, encoding="utf-8").read()
                m = re.search(r"filevers=\(([^)]*)\)", txt)
                assert m, "version_info 里找不到 filevers"
                parts = [x.strip() for x in m.group(1).split(",")]
                assert len(parts) == 4, "filevers 不是 4 段: %r" % (parts,)
                assert all(x.isdigit() for x in parts), \
                    "标记 %r 时 filevers 含非数字: %r" % (pre, parts)
                assert "prodvers=(%s)" % m.group(1) in txt, "prodvers 与 filevers 不一致"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("Windows 版本资源：带标记时仍为四段纯数字", _version_info_numeric)


def test_save_base_version():
    """在**临时副本**上验证写回逻辑，绝不改真实 toolkit_base.py。"""
    import toolkit_version as V
    tmp = tempfile.mkdtemp(prefix="ver_probe_")
    try:
        target = os.path.join(tmp, "toolkit_base.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write('APP_NAME = "X"\nAPP_VERSION = "1.0.0"\nOTHER = 1\n')
        # 重定向模块内的路径常量
        real_base, real_re = V.BASE, V._BASE_RE
        V.BASE = tmp
        try:
            ok, msg = V.save_base_version("2.5.1")
            check("写回：返回成功", lambda: ok is True)
            content = open(target, encoding="utf-8").read()
            check("写回：APP_VERSION 已更新",
                  lambda: 'APP_VERSION = "2.5.1"' in content)
            check("写回：其它内容未受影响",
                  lambda: 'APP_NAME = "X"' in content and "OTHER = 1" in content)
            check("写回：备份已生成",
                  lambda: os.path.isfile(os.path.join(tmp, "backup",
                                                      "pre_version_change", "toolkit_base.py")))
            ok2, _m = V.save_base_version("not-a-version")
            check("写回：非法版本号被拒绝", lambda: ok2 is False)
        finally:
            V.BASE, V._BASE_RE = real_base, real_re
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_version_and_marker_persistence():
    """版本号**与标记**都要落盘（在临时副本上验证，绝不改真实文件）。

    标记不落盘的后果：产物名带标记（`... 1.0.1 ALPHA.1.exe`），而界面/标题
    只显示基础版本，下次打开构建器标记还重置成"无" —— 产物与界面对不上。
    """
    import toolkit_version as V
    import toolkit_base as TB
    tmp = tempfile.mkdtemp(prefix="mark_probe_")
    try:
        target = os.path.join(tmp, "toolkit_base.py")
        with open(target, "w", encoding="utf-8") as f:
            f.write('APP_NAME = "X"\nAPP_VERSION = "1.0.0"\nOTHER = 1\n')
        real_base = V.BASE
        in_mem = (TB.APP_VERSION, getattr(TB, "APP_PRERELEASE", None))
        V.BASE = tmp
        try:
            ok, _msg = V.save_version(new_version="2.5.1", new_prerelease="BETA.2")
            content = open(target, encoding="utf-8").read()

            def _both_lines():
                assert ok is True
                assert 'APP_VERSION = "2.5.1"' in content
                assert 'APP_PRERELEASE = "BETA.2"' in content
                assert 'APP_NAME = "X"' in content and "OTHER = 1" in content
            check("标记落盘：一次写入版本号与标记，其它行不动", _both_lines)

            # 老文件没有 APP_PRERELEASE 行时应当补一行，而不是静默丢弃标记
            check("标记落盘：老文件缺 APP_PRERELEASE 行时自动补上",
                  lambda: content.count("APP_PRERELEASE") == 1)

            # 只改标记：版本号不动
            V.save_version(new_prerelease="RC.3")
            c2 = open(target, encoding="utf-8").read()
            check("标记落盘：只改标记时版本号不动",
                  lambda: 'APP_VERSION = "2.5.1"' in c2
                  and 'APP_PRERELEASE = "RC.3"' in c2)

            # 清空标记
            V.save_version(new_prerelease="")
            c3 = open(target, encoding="utf-8").read()
            check("标记落盘：可清空为 \"\"（=无标记）",
                  lambda: 'APP_PRERELEASE = ""' in c3)

            # 非法标记被拒绝
            bad, _ = V.save_version(new_prerelease="GAMMA.1")
            check("标记落盘：不支持的通道被拒绝", lambda: bad is False)

            # **关键**：重定向 BASE 写临时副本时，不得改动进程内已加载的模块属性
            check("标记落盘：重定向写副本时不污染进程内模块",
                  lambda: (TB.APP_VERSION, getattr(TB, "APP_PRERELEASE", None)) == in_mem)
        finally:
            V.BASE = real_base
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    # 运行时读的就是保存值：full_version() 不带参数时应当带出已保存的标记
    def _runtime_reads_saved_marker():
        import toolkit_version as V
        saved = V.current_prerelease()
        assert V.full_version() == V.full_version(prerelease=saved), \
            "full_version() 没读保存的标记"
        assert V.full_version(prerelease="") == V.normalize_base(V.current_base_version())
    check("运行时 full_version() 带出已保存的标记", _runtime_reads_saved_marker)


def test_prerelease_counter():
    """预发布标记序号：按 **(完整版本串, 标记名)** 各自独立计数。

    逐条覆盖用户确认过的五种情形：
        1. 同版本同标记连续构建 → 1、2、3
        2. 同版本换标记名 → 新键，从 1 开始
        3. 换回用过的标记 → **续上**原计数（不回到 1）
        4. 补丁位变化（1.0.1→1.0.2）→ 键变了，从 1 重来
        5. 次版本变化（1.0.1→1.1.0）→ 同样是新键，从 1 重来
    键用**完整版本串**而不是 semver 主号：产物名里写的就是完整版本
    （`... 1.0.2 ALPHA.1.exe`），1.0.1 与 1.0.2 是并列的两个产物，序号必须各数各的。

    用例里用 9.9.x 代替 1.0.x：仓库里已保存的标记（如 1.0.1 ALPHA.2）会给同键留下
    "序号下限"（见 toolkit_version._counter_floor），拿 1.0.x 测就变成依赖仓库当前
    值、而不是在验证计数逻辑本身。两种版本的语义完全一样。

    每个用例一份**独立的 toolkit_base.py 副本**（把 `V.BASE` 指到它自己的临时
    目录，做法与 test_next_build_dir 一致）：存储就是副本里的 `PRERELEASE_COUNTS`
    一行，故障注入时能一眼看清究竟是哪条断言被打破，而不是前一条把计数写脏后
    连带后面全红。
    """
    import toolkit_version as V
    tmp = tempfile.mkdtemp(prefix="precount_probe_")
    real_base = V.BASE
    BASEV = "9.9.9"

    def fresh(name, version="1.0.1", prerelease="ALPHA.2", counts=None):
        """换上一份干净的副本，返回它的路径（存储 = 副本里的 PRERELEASE_COUNTS）。"""
        d = os.path.join(tmp, name)
        path = _base_copy(d, version=version, prerelease=prerelease, counts=counts)
        V.BASE = d
        return path

    try:
        def _consecutive():
            fresh("c1")
            assert V.next_prerelease("ALPHA.1", BASEV, consume=True) == "ALPHA.1"
            assert V.next_prerelease("ALPHA.1", BASEV, consume=True) == "ALPHA.2"
            assert V.next_prerelease("ALPHA.2", BASEV, consume=True) == "ALPHA.3"
        check("标记计数：同版本同标记连续构建 → ALPHA.1/2/3", _consecutive)

        def _marker_switch():
            fresh("c2")
            V.next_prerelease("ALPHA.1", BASEV, consume=True)
            V.next_prerelease("ALPHA.1", BASEV, consume=True)
            # 换标记名 = 同版本下的新键：必须从 .1 开始，不能接着 ALPHA 的数
            assert V.next_prerelease("BETA.1", BASEV, consume=True) == "BETA.1"
        check("标记计数：同版本换标记名 → 从 .1 开始（新键）", _marker_switch)

        def _resume_previous_marker():
            fresh("c3")
            V.next_prerelease("ALPHA.1", BASEV, consume=True)   # ALPHA.1
            V.next_prerelease("ALPHA.1", BASEV, consume=True)   # ALPHA.2
            assert V.next_prerelease("BETA.1", BASEV, consume=True) == "BETA.1"
            # 换回 ALPHA：该键的计数要**续上**（2 → 3），不能回到 1
            assert V.next_prerelease("ALPHA.1", BASEV, consume=True) == "ALPHA.3"
        check("标记计数：换回用过的标记 → 续上原序号（2 → 3）", _resume_previous_marker)

        def _patch_version_restart():
            fresh("c4")
            V.next_prerelease("ALPHA.1", "9.9.9", consume=True)
            assert V.next_prerelease("ALPHA.1", "9.9.9", consume=True) == "ALPHA.2"
            # 补丁位变了（1.0.1→1.0.2 的等价情形）：键变了 → ALPHA 从 .1 重来
            assert V.next_prerelease("ALPHA.2", "9.9.10", consume=True) == "ALPHA.1"
        check("标记计数：补丁位变化（1.0.1→1.0.2 等价）→ 从 .1 重来",
              _patch_version_restart)

        def _minor_version_restart():
            fresh("c5")
            V.next_prerelease("ALPHA.1", "9.9.9", consume=True)
            assert V.next_prerelease("ALPHA.1", "9.9.9", consume=True) == "ALPHA.2"
            # 次版本变了（1.0.1→1.1.0 的等价情形）：**同样是新键**，从 .1 起 ——
            # 键是完整版本串，不是 semver 主号（用户明确确认过）
            assert V.next_prerelease("ALPHA.2", "9.10.0", consume=True) == "ALPHA.1"
        check("标记计数：次版本变化（1.0.1→1.1.0 等价）→ 从 .1 重来",
              _minor_version_restart)

        def _store_shape():
            path = fresh("shape")
            V.next_prerelease("ALPHA.1", BASEV, consume=True)
            V.next_prerelease("ALPHA.1", BASEV, consume=True)
            V.next_prerelease("BETA.1", BASEV, consume=True)
            # 存储就是副本里的那一行（不再有第二个文件）
            assert _counts_in(path) == {"9.9.9|ALPHA": 2, "9.9.9|BETA": 1}, _counts_in(path)
        check("计数落盘：键为 '<完整版本>|<标记名>'，值为已用序号（写在 toolkit_base.py）",
              _store_shape)

        def _peek_has_no_side_effect():
            path = fresh("peek")
            before = _read_bytes(path)
            assert V.next_prerelease("ALPHA.1", BASEV, consume=False) == "ALPHA.1"
            assert V.next_prerelease("ALPHA.1", BASEV, consume=False) == "ALPHA.1"
            assert _read_bytes(path) == before, "只读的 peek 竟然改了 toolkit_base.py"
        check("计数落盘：peek（consume=False）不写盘", _peek_has_no_side_effect)

        def _robust_missing_empty_corrupt():
            path = fresh("robust")
            # ① 副本里根本没有 PRERELEASE_COUNTS 行（老文件）→ 当空，从 1 开始，不抛异常
            assert V.next_prerelease("ALPHA.1", BASEV, consume=True) == "ALPHA.1"
            # ② 空 dict → 同样当空
            _set_base_line(path, V._COUNTS_LINE_RE, "PRERELEASE_COUNTS = {}")
            assert V.next_prerelease("ALPHA.1", BASEV) == "ALPHA.1"
            # ③ 半截字面量（写到一半崩掉的样子）→ 当空，而不是把构建打断；
            #    而且下一次 consume 要把它**覆盖**掉，而不是在坏行后面再追加一行
            _set_base_line(path, V._COUNTS_LINE_RE,
                           'PRERELEASE_COUNTS = {"9.9.9|ALPHA": ')
            assert V.next_prerelease("ALPHA.1", BASEV, consume=True) == "ALPHA.1"
            with open(path, encoding="utf-8") as f:
                assert f.read().count("PRERELEASE_COUNTS") == 1, "坏行没被覆盖，常量出现了两遍"
            # ④ 语法合法但顶层形状不对（被手改成数组）→ 当空
            _set_base_line(path, V._COUNTS_LINE_RE, "PRERELEASE_COUNTS = [1, 2, 3]")
            assert V.next_prerelease("ALPHA.1", BASEV) == "ALPHA.1"
            # ⑤ 单条值坏了 → 只丢那一条，别的键照常可用（半坏的存储不该抹掉全部）
            _set_base_line(path, V._COUNTS_LINE_RE,
                           'PRERELEASE_COUNTS = {"9.9.9|ALPHA": "x", "9.9.9|BETA": 4}')
            assert V.next_prerelease("BETA.1", BASEV, consume=True) == "BETA.5"
        check("计数落盘：缺失/空/损坏/形状不对 → 当空且不抛异常",
              _robust_missing_empty_corrupt)

        def _no_marker_is_noop():
            path = fresh("nomarker")
            before = _read_bytes(path)
            # 没有标记就什么都没得递增，也不凭空造一个（返回空串）
            assert V.next_prerelease("", BASEV, consume=True) == ""
            assert V.next_prerelease("GAMMA.1", BASEV, consume=True) == ""
            assert _read_bytes(path) == before, "无标记时不该改 toolkit_base.py"
        check("标记计数：无标记/无法识别的标记 → 返回空串且不写文件",
              _no_marker_is_noop)

        def _saved_marker_is_floor():
            """已保存标记的序号是该键的**下限**：手工发到 ALPHA.7 后不能倒回 ALPHA.3。

            手工输入优先（`--prerelease` / 界面手填）时**不动计数**，但那个值会写回
            APP_PRERELEASE；没有这条下限的话，下一次自动递增会给出比已发布产物更小的
            序号（看着像回退）。计数与 APP_PRERELEASE 现在同处一份文件，读起来更直接，
            但规则不变：版本串对不上时下限**不生效**（换版本就是新键）。
            """
            path = fresh("floor", version="7.7.7", prerelease="ALPHA.7",
                         counts={"7.7.7|ALPHA": 2})
            before = _read_bytes(path)
            assert V.next_prerelease(base_version="7.7.7") == "ALPHA.8"
            assert V.next_prerelease(base_version="7.7.8") == "ALPHA.1"
            assert _read_bytes(path) == before, "上面两次都是 peek，不该写盘"
        check("标记计数：已保存标记的序号是该键的下限（不回退）", _saved_marker_is_floor)
    finally:
        V.BASE = real_base
        shutil.rmtree(tmp, ignore_errors=True)


def test_counters_in_toolkit_base():
    """构建次数与标记序号的**存储位置**：都在 toolkit_base.py，不再有独立计数文件。

    为什么单独把这条拎出来断言：这正是用户的要求（"还有 build 计数也放这里好了"）。
    位置一旦回退（又冒出第二个文件），两份状态迟早不同步 —— 而那种缺陷在构建成功
    时看不出来，只有产物编号 / 序号对不上时才暴露。
    读取的容错与写回的原子性都在 **toolkit_base.py 副本**上做，真文件不动。
    """
    import toolkit_base as TB
    import toolkit_version as V
    repo = os.path.dirname(os.path.abspath(__file__))

    def _constants_exist():
        assert isinstance(getattr(TB, "BUILD_COUNT", None), int), \
            "toolkit_base.BUILD_COUNT 必须是 int"
        assert isinstance(getattr(TB, "PRERELEASE_COUNTS", None), dict), \
            "toolkit_base.PRERELEASE_COUNTS 必须是 dict"
        assert TB.BUILD_COUNT >= 1, TB.BUILD_COUNT
        assert all(k.count("|") == 1 for k in TB.PRERELEASE_COUNTS), TB.PRERELEASE_COUNTS
    check("计数存储：toolkit_base 里有 BUILD_COUNT(int) / PRERELEASE_COUNTS(dict)",
          _constants_exist)

    check("计数存储：current_build_count() 与 toolkit_base.BUILD_COUNT 同源",
          lambda: V.current_build_count() == TB.BUILD_COUNT)

    def _reexported_by_toolkit():
        """两个计数也能从**公共层** `toolkit` 导入，且与 toolkit_base 是同一对象。

        为什么单列一条：调用方一律 `from toolkit import ...`，计数若只落在
        toolkit_base 而没进 re-export 清单，子工具就得绕过公共层直接摸底层 ——
        分层约定会被逐渐蛀空。比 is 而不是 == ：要求的是**同一份值**，
        不是"恰好相等的第二份拷贝"。
        """
        import toolkit as TK
        assert TK.BUILD_COUNT is TB.BUILD_COUNT, TK.BUILD_COUNT
        assert TK.PRERELEASE_COUNTS is TB.PRERELEASE_COUNTS, TK.PRERELEASE_COUNTS
    check("计数存储：toolkit 公共层 re-export 了 BUILD_COUNT / PRERELEASE_COUNTS（同一对象）",
          _reexported_by_toolkit)

    def _load_honours_module_store():
        """读取认的是 tk.base 的**模块属性**（真实进程里就是这条路径）。

        真实仓库的 store 当前是空的，直接比 "== {}" 是空转断言；这里临时往模块
        属性里塞一个真值，验证读取（含 next_prerelease）确实认它，用完还原。
        """
        old = TB.PRERELEASE_COUNTS
        TB.PRERELEASE_COUNTS = {"9.9.9|ALPHA": 6}
        try:
            assert V._load_prerelease_counts() == {"9.9.9|ALPHA": 6}, V._load_prerelease_counts()
            assert V.next_prerelease("ALPHA.1", "9.9.9") == "ALPHA.7"
        finally:
            TB.PRERELEASE_COUNTS = old
    check("计数存储：_load_prerelease_counts() 读的就是 toolkit_base.PRERELEASE_COUNTS",
          _load_honours_module_store)

    def _retired_files_gone():
        for name in ("build_count.txt", "prerelease_count.json"):
            p = os.path.join(repo, name)
            assert not os.path.exists(p), "旧计数文件还在：%s（两份状态必然不同步）" % p
    check("计数存储：旧计数文件已删除（不再是事实来源）", _retired_files_gone)

    def _no_live_reference():
        for name in ("toolkit_base.py", "toolkit.py", "toolkit_version.py",
                     "build.py", "build_gui.py"):
            with open(os.path.join(repo, name), encoding="utf-8") as f:
                src = f.read()
            for old in ("build_count.txt", "prerelease_count.json"):
                assert old not in src, "%s 里还引用着旧计数文件 %s" % (name, old)
    check("计数存储：活代码里不再引用旧计数文件名", _no_live_reference)

    tmp = tempfile.mkdtemp(prefix="counts_probe_")
    real_base = V.BASE
    try:
        src_dir = os.path.join(tmp, "src")
        path = _base_copy(src_dir, version="1.0.1", prerelease="ALPHA.2",
                          build_count=None, counts=None)
        V.BASE = src_dir

        def _missing_or_bad_is_zero():
            # ① 行不存在（老文件 / 被手删）→ 当 0，不抛异常
            assert V.current_build_count() == 0
            # ② 坏值（非数字 / 空）→ 同样当 0
            _set_base_line(path, V._COUNT_LINE_RE, "BUILD_COUNT = 五")
            assert V.current_build_count() == 0
            _set_base_line(path, V._COUNT_LINE_RE, "BUILD_COUNT = ")
            assert V.current_build_count() == 0
        check("构建计数：行缺失/坏值一律当 0（不打断构建）", _missing_or_bad_is_zero)

        def _roundtrip():
            ok, _msg = V.save_build_count(7)
            assert ok is True
            assert _base_line(path, V._COUNT_LINE_RE) == "7", _base_line(path, V._COUNT_LINE_RE)
            assert V.current_build_count() == 7
            # 覆盖坏值：整行替换 → 文件里始终只有一行 BUILD_COUNT
            with open(path, encoding="utf-8") as f:
                assert f.read().count("BUILD_COUNT") == 1
        check("构建计数：save_build_count 写回同一行（整行替换，只留一行）", _roundtrip)

        def _append_when_missing():
            _drop_base_line(path, V._COUNT_LINE_RE)
            assert V.current_build_count() == 0
            ok, _msg = V.save_build_count(3)
            assert ok is True
            assert _base_line(path, V._COUNT_LINE_RE) == "3"
        check("构建计数：行不存在时补写（老文件也存得下计数）", _append_when_missing)

        def _other_lines_untouched():
            # 写计数只动自己那一行：版本号与标记必须原样（同一个文件里的三件事）
            assert _base_line(path, V._BASE_RE) == "1.0.1", _base_line(path, V._BASE_RE)
            assert _base_line(path, V._PRE_RE) == "ALPHA.2", _base_line(path, V._PRE_RE)
        check("计数存储：写 BUILD_COUNT / PRERELEASE_COUNTS 不动版本号与标记",
              _other_lines_untouched)

        def _no_tmp_leftover():
            V.save_build_count(4)
            V.next_prerelease("ALPHA.1", "3.3.3", consume=True)
            left = [n for n in os.listdir(src_dir) if n.endswith(".tmp")]
            assert not left, left
        check("计数存储：原子写不留 .tmp 残留", _no_tmp_leftover)

        def _next_prerelease_writes_same_file():
            before = _read_bytes(path)
            assert V.next_prerelease("ALPHA.1", "4.4.4", consume=True) == "ALPHA.1"
            assert _read_bytes(path) != before, "consume=True 竟然没改 toolkit_base.py"
            assert _counts_in(path) == {"3.3.3|ALPHA": 1, "4.4.4|ALPHA": 1}, _counts_in(path)
        check("计数存储：next_prerelease(consume=True) 写进 toolkit_base.py（无 JSON 文件）",
              _next_prerelease_writes_same_file)

        def _sync_when_writing_real_file():
            """写的是"真文件"时同步进程内模块属性（写完立刻读得到新值）。

            探针平时把 `BASE` 指向副本、同步被**故意**跳过（否则污染当前进程）；
            这里把 `_REAL_BASE` 也临时指到副本目录，等于"这份副本就是真文件"，
            从而单独验证同步那一段 —— 不做的话，同一进程里"保存后立刻构建/刷新"
            仍会读回旧值（`import toolkit_base` 拿到的是缓存对象）。
            """
            import toolkit_base as _TB
            old_real = V._REAL_BASE
            old_mem = (_TB.BUILD_COUNT, _TB.PRERELEASE_COUNTS)
            V._REAL_BASE = src_dir
            try:
                V.save_build_count(11)
                assert _TB.BUILD_COUNT == 11, _TB.BUILD_COUNT
                V.next_prerelease("ALPHA.1", "5.5.5", consume=True)
                assert _TB.PRERELEASE_COUNTS.get("5.5.5|ALPHA") == 1, _TB.PRERELEASE_COUNTS
            finally:
                V._REAL_BASE = old_real
                _TB.BUILD_COUNT, _TB.PRERELEASE_COUNTS = old_mem
        check("计数存储：写真文件时同步进程内模块（保存后立刻读得到）",
              _sync_when_writing_real_file)
    finally:
        V.BASE = real_base
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_args():
    import build
    check("参数：默认全空", lambda: build.parse_args(["build.py"]) == (None, None, None))
    check("参数：--version",
          lambda: build.parse_args(["b", "--version", "1.2.0"])[1] == "1.2.0")
    check("参数：--prerelease",
          lambda: build.parse_args(["b", "--prerelease", "BETA.1"])[2] == "BETA.1")
    check("参数：--out 转绝对路径",
          lambda: os.path.isabs(build.parse_args(["b", "--out", "rel/dir"])[0]))
    check("参数：三者可同时给出",
          lambda: build.parse_args(["b", "--out", "d", "--version", "2.0.0",
                                    "--prerelease", "alpha2"])[1:] == ("2.0.0", "alpha2"))


def test_next_build_dir():
    """产物目录编号：绝不覆盖既有历史版本目录（在临时目录里做，不碰真 builds/）。

    `builds/` 下的历史版本是有意保留的对照物，因此计数被改成已用过的值、或那一行
    坏掉时，必须往后找空号，而不是把 `build_1` 整目录删掉重建。

    计数存在 **toolkit_base.py 副本**里（`V.BASE` 重定向到临时目录）：这里既不碰
    真 `builds/`，也不碰真 `toolkit_base.py`。
    """
    import build
    import toolkit_version as V
    tmp = tempfile.mkdtemp(prefix="builddir_probe_")
    real_dir, real_base = build.BUILDS_DIR, V.BASE
    try:
        build.BUILDS_DIR = os.path.join(tmp, "builds")
        os.makedirs(build.BUILDS_DIR)
        src_dir = os.path.join(tmp, "src")
        # 副本镜像真仓库的版本/标记（应用名用例要比对它们），但**不带 BUILD_COUNT 行**
        # —— 正好验证"老文件 / 行被手删"时从 build_1 开始且写回时会补上这一行。
        base_py = _base_copy(src_dir, version=V.current_base_version(),
                             prerelease=V.current_prerelease(), build_count=None)
        V.BASE = src_dir
        try:
            check("产物目录：计数不存在时从 build_1 开始",
                  lambda: os.path.basename(build.next_build_dir()) == "build_1")
            check("产物目录：第二次为 build_2",
                  lambda: os.path.basename(build.next_build_dir()) == "build_2")

            def _count_reset_to_1():
                _set_base_line(base_py, V._COUNT_LINE_RE, "BUILD_COUNT = 1")
                got = os.path.basename(build.next_build_dir())
                assert got == "build_3", "实际 %s（不能覆盖已存在的 build_1/build_2）" % got
            check("产物目录：计数被手改回已用过的值时自动跳过", _count_reset_to_1)

            def _count_garbage():
                _set_base_line(base_py, V._COUNT_LINE_RE, "BUILD_COUNT = garbage")
                return os.path.basename(build.next_build_dir())
            check("产物目录：计数行损坏时不崩且继续往后编号",
                  lambda: _count_garbage() == "build_4")

            # 命名规则：**目录名不含版本号**，版本号进产物内侧的应用名
            check("产物目录：恒为 build_N（不带版本号）",
                  lambda: os.path.basename(build.next_build_dir()) == "build_5")

            # 计数**写回 toolkit_base**（不再是第二个文件）：上面每次调用都应把
            # BUILD_COUNT 那一行改成刚用掉的编号，且文件里始终只有一行。
            def _count_written_back():
                assert _base_line(base_py, V._COUNT_LINE_RE) == "5", \
                    _base_line(base_py, V._COUNT_LINE_RE)
                with open(base_py, encoding="utf-8") as f:
                    assert f.read().count("BUILD_COUNT") == 1
            check("产物目录：计数写回 toolkit_base.BUILD_COUNT（只留一行）",
                  _count_written_back)

            def _app_name_carries_version():
                import toolkit_version as V
                base = V.current_base_version()
                plain = build.app_name_for("")
                marked = build.app_name_for("BETA.1")
                assert plain == f"{build.APP_NAME} {base}", plain
                assert marked == f"{build.APP_NAME} {base} BETA.1", marked
                assert "/" not in marked and "\\" not in marked, marked
                assert marked.endswith("BETA.1"), marked
            check("应用名：版本号跟在应用名后面（含预发布标记）", _app_name_carries_version)

            def _version_info_original_filename():
                import re
                import toolkit_version as V
                path = os.path.join(tmp, "vi.txt")
                name = build.app_name_for("ALPHA.2")
                build.write_version_info(path, V.version_tuple(prerelease="ALPHA.2"),
                                         exe_name=f"{name}.exe")
                txt = open(path, encoding="utf-8").read()
                got = re.search(r"StringStruct\('OriginalFilename', '([^']*)'\)", txt)
                assert got and got.group(1) == f"{name}.exe", \
                    "OriginalFilename 没跟上应用名：%r" % (got.group(1) if got else None)
            check("版本资源：OriginalFilename 与实际 exe 名一致", _version_info_original_filename)

            # --name / bundle_dir / exe_path 必须用**同一个** app_name：
            # 应用名现在带版本串，漏改任何一处都会让构建在"找不到产物"处失败，
            # 而那时已经跑完几分钟的 PyInstaller。
            def _paths_share_app_name():
                name = build.app_name_for("BETA.1")
                bundle, exe = build.bundle_paths(os.path.join(tmp, "out"), name)
                assert os.path.basename(bundle) == name, bundle
                assert exe == os.path.join(bundle, name + ".exe"), exe
                src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                        "build.py"), encoding="utf-8").read()
                assert '"--name", app_name' in src, \
                    "PyInstaller 的 --name 没有用 app_name（改名漏了一处）"
                assert 'f"{app_name}.exe"' in src or "app_name}.exe" in src
            check("命名一致性：--name / 内侧目录 / exe 用同一个应用名",
                  _paths_share_app_name)
        finally:
            build.BUILDS_DIR, V.BASE = real_dir, real_base
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_prerelease_auto_increment():
    """build.py 的两条规矩：不给 `--prerelease` 就自动 +1，给了就原样用且不动计数。

    直接跑 `build.main()`（把 `build.build` 换成记录用的桩，不触发真实 PyInstaller），
    并把 `V.BASE` 指到临时目录：`save_version` / `next_prerelease` /
    `save_build_count` 写的都只是那份 toolkit_base.py 副本，仓库真文件分毫不动
    —— 与 test_save_base_version 的重定向做法一致。
    """
    import build
    import toolkit_version as V
    tmp = tempfile.mkdtemp(prefix="buildmain_probe_")
    real = (V.BASE, build.BUILDS_DIR, build.build, list(sys.argv))
    calls = []
    try:
        src_dir = os.path.join(tmp, "src")
        base_now = V.current_base_version()
        pre_now = V.current_prerelease()
        target = _base_copy(src_dir, version=base_now, prerelease=pre_now,
                            build_count=0, counts={})
        V.BASE = src_dir
        build.BUILDS_DIR = os.path.join(tmp, "builds")
        build.build = lambda out_dir, prerelease="", base_version=None: calls.append(
            (out_dir, prerelease, base_version))

        def saved_pre():
            """读**副本**里的 APP_PRERELEASE（save_version 写的就是它）。"""
            return _base_line(target, V._PRE_RE)

        def counts_line():
            """读**副本**里 PRERELEASE_COUNTS 那一行 —— 判断计数有没有被推进。"""
            return _base_line(target, V._COUNTS_LINE_RE)

        def run(argv):
            sys.argv = ["build.py"] + argv
            build.main()

        def _auto_increment():
            expected = V.next_prerelease(base_version=base_now, consume=False)
            before = counts_line()
            run([])
            assert counts_line() != before, \
                "自动模式下 toolkit_base.py 的 PRERELEASE_COUNTS 没有落盘"
            assert _counts_in(target), "自动 +1 之后计数应当非空：%r" % (counts_line(),)
            assert saved_pre() == expected, \
                "没自增写回：副本里是 %r，应为 %r" % (saved_pre(), expected)
            assert calls and calls[-1][1] == expected, \
                "构建实际用的标记不是自增后的值：%r" % (calls[-1][1] if calls else None)
        check("build.py：未给 --prerelease → 自动 +1 并写回", _auto_increment)

        def _build_count_advanced():
            got = _base_line(target, V._COUNT_LINE_RE)
            assert got == "1", "默认位置构建后 BUILD_COUNT 应为 1，实际 %r" % got
        check("build.py：默认位置构建把 BUILD_COUNT 推进到 build_1", _build_count_advanced)

        def _explicit_wins():
            before = counts_line()
            run(["--prerelease", "BETA.9"])
            assert saved_pre() == "BETA.9", saved_pre()
            assert calls[-1][1] == "BETA.9", calls[-1][1]
            assert counts_line() == before, "显式 --prerelease 竟然推进了计数"
        check("build.py：显式 --prerelease 原样使用且不动计数", _explicit_wins)

        def _explicit_empty_clears():
            # 界面上把标记选「无」时传的就是 `--prerelease ""`：清空标记，同样不动计数
            before = counts_line()
            run(["--prerelease", ""])
            assert saved_pre() == "", repr(saved_pre())
            assert calls[-1][1] == "", calls[-1][1]
            assert counts_line() == before, '显式 --prerelease "" 竟然推进了计数'
        check('build.py：--prerelease ""（选「无」）→ 清空且不动计数',
              _explicit_empty_clears)
    finally:
        (V.BASE, build.BUILDS_DIR, build.build, argv0) = real
        sys.argv = argv0
        shutil.rmtree(tmp, ignore_errors=True)


def test_build_transaction():
    """构建事务：失败回退 + FAIL 归档 + 日志同名 + 崩溃快照（用户口径 2026-09-12）。

    "每一次存在的构建都是成功的构建"要变成机器判据，否则它只是口号：
      * 非空失败目录 → 移入 `builds/FAIL/<名>/`，日志**放在目录内且与目录同名**；
      * 空目录（一个文件都没产出）→ 删掉，日志直接落在 `FAIL/` 下；
      * 同秒的第二次失败 → 加 `_2`，**不许互相覆盖**；
      * `--out` 指向用户目录 → 原地不动（只回退 + 日志进 FAIL）；
      * 失败 → 四项状态（版本号/标记/构建次数/标记计数）全部回退。

    全部在临时沙箱里造；`toolkit_base.py` 用 `V.BASE` 重定向到副本（真实文件绝不被改）。
    """
    import build
    import toolkit_base as TB
    import toolkit_version as V

    def _mem_state():
        return {"APP_VERSION": TB.APP_VERSION, "APP_PRERELEASE": TB.APP_PRERELEASE,
                "BUILD_COUNT": TB.BUILD_COUNT, "PRERELEASE_COUNTS": dict(TB.PRERELEASE_COUNTS)}

    def _mem_restore(st):
        TB.APP_VERSION = st["APP_VERSION"]
        TB.APP_PRERELEASE = st["APP_PRERELEASE"]
        TB.BUILD_COUNT = st["BUILD_COUNT"]
        TB.PRERELEASE_COUNTS = st["PRERELEASE_COUNTS"]

    def _new_builds(tmp):
        b = os.path.join(tmp, "builds")
        os.makedirs(b, exist_ok=True)
        return b

    def _archive_nonempty():
        tmp = tempfile.mkdtemp(prefix="txn_a_")
        try:
            builds = _new_builds(tmp)
            t = os.path.join(builds, "build_11")
            os.makedirs(os.path.join(t, "app"))
            with open(os.path.join(t, "app", "x.exe"), "wb") as f:
                f.write(b"x" * 100)
            r = build.archive_failed(t, 11, "Traceback (most recent call last): boom\n",
                                     "CalledProcessError: 1",
                                     stamp="2026_09_12_13_45_07", builds_dir=builds)
            assert r["moved_to"] and not r["deleted"], r
            assert os.path.basename(r["moved_to"]) == "build_11_2026_09_12_13_45_07", r["entry"]
            assert os.path.basename(r["log_path"]) == r["entry"] + ".log", r["log_path"]
            assert os.path.dirname(r["log_path"]) == r["moved_to"], "日志必须与归档目录同处"
            assert not os.path.exists(t), "原 build_N 目录应已整体移走"
            body = open(r["log_path"], encoding="utf-8").read()
            assert "boom" in body and "失败原因" in body, body[:200]
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：非空失败目录移入 FAIL\\<名>，日志与目录同名且在目录内",
          _archive_nonempty)

    def _archive_empty_deletes():
        tmp = tempfile.mkdtemp(prefix="txn_b_")
        try:
            builds = _new_builds(tmp)
            t = os.path.join(builds, "build_12")
            os.makedirs(t)                     # 一个文件都没有
            r = build.archive_failed(t, 12, "", "boom", stamp="2026_09_12_14_00_00",
                                     builds_dir=builds)
            assert r["deleted"] and not r["moved_to"], r
            assert not os.path.exists(t), "空产出目录必须删掉"
            assert os.path.dirname(r["log_path"]) == os.path.join(builds, "FAIL"), r["log_path"]
            assert os.path.basename(r["log_path"]) == "build_12_2026_09_12_14_00_00.log", r
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：空产出目录被删除，日志直接落在 FAIL\\ 下（同名规则）",
          _archive_empty_deletes)

    def _same_second_coexists():
        tmp = tempfile.mkdtemp(prefix="txn_c_")
        try:
            builds = _new_builds(tmp)
            names = []
            for i in (1, 2):
                t = os.path.join(builds, "build_13")
                os.makedirs(os.path.join(t, "app"))
                open(os.path.join(t, "app", "x.exe"), "wb").write(b"x")
                r = build.archive_failed(t, 13, "log %d\n" % i, "boom",
                                         stamp="2026_09_12_15_00_00", builds_dir=builds)
                names.append(r["entry"])
            assert names == ["build_13_2026_09_12_15_00_00",
                             "build_13_2026_09_12_15_00_00_2"], names
            fail = os.path.join(builds, "FAIL")
            assert sorted(os.listdir(fail)) == sorted(names), os.listdir(fail)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：同一秒的第二次失败加 _2，两份现场共存不覆盖", _same_second_coexists)

    def _out_dir_untouched():
        tmp = tempfile.mkdtemp(prefix="txn_d_")
        try:
            builds = _new_builds(tmp)
            user = os.path.join(tmp, "user_out")     # 用户用 --out 指定的目录
            os.makedirs(os.path.join(user, "app"))
            keep = os.path.join(user, "app", "my_file.txt")
            open(keep, "w", encoding="utf-8").write("mine")
            r = build.archive_failed(user, 14, "log\n", "boom",
                                     stamp="2026_09_12_16_00_00", builds_dir=builds)
            assert os.path.isfile(keep), "用户目录被搬动/删除了！"
            assert r["moved_to"] is None and not r["deleted"], r
            assert os.path.dirname(r["log_path"]) == os.path.join(builds, "FAIL")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：--out 用户目录原地不动（只把日志放进 FAIL）", _out_dir_untouched)

    def _name_format():
        import re as _re
        n = build.fail_entry_name(11)
        assert _re.fullmatch(r"build_11_\d{4}_\d{2}_\d{2}_\d{2}_\d{2}_\d{2}", n), n
    check("构建事务：归档名 = build_<构建数>_<4位年>_<月>_<日>_<时>_<分>_<秒>",
          _name_format)

    def _finish_failure_rolls_back():
        tmp = tempfile.mkdtemp(prefix="txn_r_")
        real_base, real_builds = V.BASE, build.BUILDS_DIR
        st = _mem_state()
        try:
            with open(os.path.join(tmp, "toolkit_base.py"), "w", encoding="utf-8") as f:
                f.write('APP_NAME = "X"\nAPP_VERSION = "1.0.1"\n'
                        'APP_PRERELEASE = "ALPHA.7"\nBUILD_COUNT = 10\n'
                        'PRERELEASE_COUNTS = {"1.0.1|ALPHA": 7}\n')
            V.BASE = tmp
            builds = _new_builds(tmp)
            build.BUILDS_DIR = builds
            V._sync_module("APP_VERSION", "1.0.1")
            V._sync_module("APP_PRERELEASE", "ALPHA.7")
            V._sync_module("BUILD_COUNT", 10)
            V._sync_module("PRERELEASE_COUNTS", {"1.0.1|ALPHA": 7})
            snap = V.snapshot_state()
            # 模拟构建开头那几步推进了状态（版本号/标记/计数/标记计数）
            V.save_version(new_version="1.0.1", new_prerelease="ALPHA.8")
            V.save_build_count(11)
            V._save_prerelease_counts({"1.0.1|ALPHA": 8})
            build.write_pending_snapshot(snap, {"number": 11})
            t = os.path.join(builds, "build_11")
            os.makedirs(os.path.join(t, "app"))
            open(os.path.join(t, "app", "x.exe"), "wb").write(b"x")
            res = build.finish_build(ok=False, reason="InjectedFailure: boom", target=t,
                                     number=11, snap=snap, log_text="构建日志正文\n",
                                     builds_dir=builds)
            txt = open(os.path.join(tmp, "toolkit_base.py"), encoding="utf-8").read()
            assert res["ok"] is False, res
            assert res["rollback_ok"] is True, res
            assert 'APP_PRERELEASE = "ALPHA.7"' in txt, txt
            assert "BUILD_COUNT = 10" in txt, txt
            assert '"1.0.1|ALPHA": 7' in txt, txt
            assert res["archived"] and res["archived"]["moved_to"], res
            assert not os.path.exists(build.snapshot_path()), "快照文件应在收尾时清除"
        finally:
            V.BASE, build.BUILDS_DIR = real_base, real_builds
            _mem_restore(st)
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：失败时四项状态全部回退 + 归档 + 清快照", _finish_failure_rolls_back)

    def _finish_success_keeps_state():
        tmp = tempfile.mkdtemp(prefix="txn_s_")
        real_builds = build.BUILDS_DIR
        try:
            builds = _new_builds(tmp)
            build.BUILDS_DIR = builds
            t = os.path.join(builds, "build_15")
            os.makedirs(os.path.join(t, "app"))
            open(os.path.join(t, "app", "x.exe"), "wb").write(b"x")
            build.write_pending_snapshot({"version": "1.0.1"}, {"number": 15})
            res = build.finish_build(ok=True, reason=None, target=t, number=15,
                                     snap={"version": "1.0.1"}, log_text="ok\n",
                                     builds_dir=builds)
            assert res["ok"] is True and res["archived"] is None, res
            assert os.path.isdir(t), "成功的构建目录必须保留"
            fail = os.path.join(builds, build.FAIL_DIRNAME)
            assert not os.path.exists(fail), "成功不该产生 FAIL 目录"
            assert not os.path.exists(build.snapshot_path()), "成功也要清快照"
        finally:
            build.BUILDS_DIR = real_builds
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：成功时保留产物目录、不建 FAIL、清快照", _finish_success_keeps_state)

    def _snapshot_roundtrip():
        tmp = tempfile.mkdtemp(prefix="txn_snap_")
        real_builds = build.BUILDS_DIR
        try:
            build.BUILDS_DIR = _new_builds(tmp)
            snap = {"version": "1.0.1", "prerelease": "ALPHA.7", "build_count": 10,
                    "counts": {"1.0.1|ALPHA": 7}}
            assert build.write_pending_snapshot(snap, {"number": 11}), "快照写入失败"
            got = build.read_pending_snapshot()
            assert got and got["version"] == "1.0.1" and got["number"] == 11, got
            build.clear_pending_snapshot()
            assert build.read_pending_snapshot() is None
        finally:
            build.BUILDS_DIR = real_builds
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：未收尾快照可写可读可清（崩溃自愈的载体）", _snapshot_roundtrip)

    def _recover_rolls_back():
        """崩溃/强杀留下的快照：下次构建开始时必须自动回退并清掉快照。

        没有这条自愈，被强杀的那次构建会**永久**把版本号与编号留在磁盘上
        （回退代码根本没机会运行），而"失败的构建不留痕迹"正是本次改造的要点。
        """
        tmp = tempfile.mkdtemp(prefix="txn_rec_")
        real_base, real_builds = V.BASE, build.BUILDS_DIR
        st = _mem_state()
        try:
            with open(os.path.join(tmp, "toolkit_base.py"), "w", encoding="utf-8") as f:
                f.write('APP_NAME = "X"\nAPP_VERSION = "1.0.1"\n'
                        'APP_PRERELEASE = "ALPHA.9"\nBUILD_COUNT = 11\n'
                        'PRERELEASE_COUNTS = {"1.0.1|ALPHA": 9}\n')
            V.BASE = tmp
            build.BUILDS_DIR = _new_builds(tmp)
            V._sync_module("APP_VERSION", "1.0.1")
            V._sync_module("APP_PRERELEASE", "ALPHA.9")
            V._sync_module("BUILD_COUNT", 11)
            V._sync_module("PRERELEASE_COUNTS", {"1.0.1|ALPHA": 9})
            # 假装上一次构建在写盘之后被强杀：磁盘上是"推进后"的值，快照是"构建前"
            build.write_pending_snapshot(
                {"version": "1.0.1", "prerelease": "ALPHA.8", "build_count": 10,
                 "counts": {"1.0.1|ALPHA": 8}}, {"number": 11})
            snap = build.recover_pending_snapshot()
            txt = open(os.path.join(tmp, "toolkit_base.py"), encoding="utf-8").read()
            assert snap and snap["prerelease"] == "ALPHA.8", snap
            assert 'APP_PRERELEASE = "ALPHA.8"' in txt, txt
            assert "BUILD_COUNT = 10" in txt, txt
            assert not os.path.exists(build.snapshot_path()), "恢复后快照必须清掉"
        finally:
            V.BASE, build.BUILDS_DIR = real_base, real_builds
            _mem_restore(st)
            shutil.rmtree(tmp, ignore_errors=True)
    check("构建事务：强杀留下的快照在下次构建时自动回退并清除（崩溃自愈）",
          _recover_rolls_back)

    def _gui_marks_failure_lines():
        src = open(os.path.join(BASE, "build_gui.py"), encoding="utf-8").read()
        for mark in ("[FAIL]", "[回退]"):
            assert '"%s"' % mark in src or "'%s'" % mark in src, \
                "构建器不再把 %s 行标成错误色/提示 —— 失败在现场完全没有痕迹" % mark
    check("构建器：build.py 的 [FAIL]/[回退] 收尾行会被标色显示", _gui_marks_failure_lines)


def test_build_gui_construction():
    import tkinter as tk
    for mod, fn in (("tkinter.messagebox", "showinfo"), ("tkinter.messagebox", "showwarning")):
        pass
    from tkinter import messagebox
    messagebox.showinfo = lambda *a, **k: "ok"
    messagebox.showwarning = lambda *a, **k: "ok"
    messagebox.showerror = lambda *a, **k: "ok"

    try:
        import build_gui
    except Exception as e:
        raise AssertionError("build_gui 导入失败: %s" % e)

    root = tk.Tk()
    root.withdraw()
    try:
        app = build_gui.BuildGUI(root)
        check("GUI：可无头构造", lambda: app is not None)
        check("GUI：初始版本号已填充",
              lambda: bool(app.var_version.get()))
        check("GUI：标记下拉含 ALPHA/BETA/RC",
              lambda: {"ALPHA", "BETA", "RC"}.issubset(set(build_gui.CHANNELS)))
        check("GUI：状态栏显示基础版本",
              lambda: "基础版本" in app.lbl_current.cget("text"))
        # 标记也必须从**已保存的值**预填，否则产物名带标记、界面却是"无"
        import toolkit_version as _V
        _saved_ch, _saved_no = _V.split_prerelease(_V.current_prerelease())
        def _marker_prefilled():
            assert app.var_channel.get() == (_saved_ch or "无"), \
                "实际 %r，保存值 %r" % (app.var_channel.get(), _saved_ch or "无")
        check("GUI：标记下拉从已保存值预填", _marker_prefilled)
        # 序号栏显示的是**本次构建将使用的**序号（用户口径 2026-09-12），
        # 而不是"上次已经构建过的"号 —— 后者与同一行旁边那句「下次标记」自相矛盾。
        def _seq_shows_this_build_number():
            nxt = _V.next_prerelease(base_version=app.var_version.get() or None,
                                     consume=False)
            want = _V.split_prerelease(nxt)[1] if nxt else None
            got = app.var_seq.get()
            assert got == (str(want) if want else "1"), \
                "序号栏应显示本次将使用的 %r，实际 %r（已保存的旧号是 %r）" % (
                    want, got, _saved_no)
        check("GUI：序号栏显示**本次构建将使用**的序号（不是上次构建过的）",
              _seq_shows_this_build_number)

        # 下一次构建会用到的标记必须写在「当前」框里，且与 build.py 用**同一个**
        # VER.next_prerelease()。这里是 peek（consume=False）：看一眼界面不该涨序号。
        def _count_line_shows_next_marker():
            expect = _V.next_prerelease(base_version=app.var_version.get() or None,
                                        consume=False) or "无"
            text = app.lbl_count.cget("text")
            assert "已构建次数(BUILD_COUNT)" in text, text
            assert "下次标记" in text, text
            assert expect in text, "%r 不在 %r" % (expect, text)
        check("GUI：构建次数行显示「下次标记」（与 build.py 同源）",
              _count_line_shows_next_marker)

        # 构建次数必须来自 toolkit_base（不再是界面自己读第二个文件）：
        # 界面显示的编号与实际 next_build_dir() 建的目录共用一个来源。
        def _build_count_from_toolkit_base():
            import toolkit_base as _TB
            assert app._build_count() == _TB.BUILD_COUNT, app._build_count()
            assert ("已构建次数(BUILD_COUNT): %d" % _TB.BUILD_COUNT) in app.lbl_count.cget("text")
        check("GUI：构建次数来自 toolkit_base.BUILD_COUNT（无第二实现）",
              _build_count_from_toolkit_base)

        def _auto_mode_passes_no_prerelease():
            # 自动模式：界面**不传** --prerelease，让 build.py 单点推进计数
            app.var_marker_manual = False
            app._refresh_count_line()
            assert app._marker_args() == [], app._marker_args()
            assert "自动递增" in app.lbl_count.cget("text"), app.lbl_count.cget("text")
        check("GUI：自动模式不传 --prerelease（计数只由 build.py 推进）",
              _auto_mode_passes_no_prerelease)

        def _manual_mode_passes_marker_verbatim():
            app.var_marker_manual = True
            app.var_channel.set("BETA")
            app.var_seq.set("5")
            assert app._marker_args() == ["--prerelease", "BETA.5"], app._marker_args()
            # 手改优先这条规则要看得见（用户不必猜"为什么序号没动"）
            assert "手动" in app.lbl_count.cget("text"), app.lbl_count.cget("text")
            # 选「无」也必须显式传空串：不传的话 build.py 会把已保存的标记自动 +1 用上，
            # 正好与"不要标记"相反。
            app.var_channel.set("无")
            assert app._marker_args() == ["--prerelease", ""], app._marker_args()
        check("GUI：手动模式显式传标记（含空串=无标记）",
              _manual_mode_passes_marker_verbatim)

        # 上面几条把标记切成了"手动"；后面还有预览/解析用例，先还原成"打开构建器
        # 时的样子"（自动模式 + 已保存值），免得几条用例互相影响。
        app.var_marker_manual = False
        app._refresh_current()
        check("GUI：「当前」行同时显示标记与完整版本",
              lambda: "标记" in app.lbl_current.cget("text")
              and _V.full_version() in app.lbl_current.cget("text"))
        def _no_save_button():
            """「保存版本号与标记」按钮必须消失（用户口径 2026-09-12）。

            它是**第二条写盘路径**：按钮写一次、构建时 build.py 再写一次，
            两条路径可以给出不同结果（"我明明保存了 BETA.5，构建出来却是别的"）。
            现在版本号/标记只在构建开始时自动保存，失败还会自动回退。
            """
            assert not hasattr(app, "btn_save"), "「保存版本号与标记」按钮应已删除"
            assert not hasattr(app, "_on_save"), "保存逻辑应已删除（构建前自动保存）"
            src = open(os.path.join(BASE, "build_gui.py"), encoding="utf-8").read()
            # 查**控件构造与回调**，不是查字符串：注释里提到按钮名是正常的
            # （要解释为什么删掉它），先前把注释也算进去结果自己把自己判红。
            assert "self._on_save" not in src, "仍留有 _on_save 的调用点"
            assert 'tool_button(bar, "保存' not in src, "操作栏里仍有保存按钮"
        check("GUI：没有「保存版本号与标记」按钮（构建前自动保存、失败自动回退）",
              _no_save_button)
        app._set_status("构建中…", "running")
        check("GUI：状态栏可写且带语义色",
              lambda: app.lbl_state.cget("text").startswith("构建中")
              and bool(app.lbl_state.cget("fg")))
        app._set_status("构建成功", "ok")
        check("GUI：状态栏语义切换生效",
              lambda: app.lbl_state.cget("text") == "构建成功")

        # 预览：切到 BETA 序号 2
        app.var_version.set("1.0.0")
        app.var_channel.set("BETA")
        app.var_seq.set("2")
        app._refresh_preview()
        check("GUI：预览随标记更新",
              lambda: "BETA.2" in app.lbl_preview.cget("text"))

        # 解析：粘贴完整版本串
        app.var_version.set("v2.0.0-rc.3")
        app._on_parse()
        check("GUI：解析完整串后基础版本正确",
              lambda: app.var_version.get() == "2.0.0")
        check("GUI：解析完整串后通道正确",
              lambda: app.var_channel.get() == "RC")
        check("GUI：解析完整串后序号正确",
              lambda: app.var_seq.get() == "3")

        # 无标记时预览不应含通道名
        app.var_version.set("1.0.0")
        app.var_channel.set("无")
        app._refresh_preview()
        check("GUI：无标记预览不带通道",
              lambda: "ALPHA" not in app.lbl_preview.cget("text")
              and "BETA" not in app.lbl_preview.cget("text"))
        check("GUI：标记选择项完整", lambda: build_gui.CHANNELS[0] == "无")
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def test_ci_cleanup_excludes_builder_temp():
    r"""CI 的 temp 清理白名单里**不得**出现构建器的工作目录。

    归属原则：谁创建谁清理。`temp/build/` 是 `build.py` 的 PyInstaller 工作目录
    （work/spec），由它自己的 finally 清；CI 一旦顺手删掉，正在运行的构建会在
    `create_base_library_zip` 处报
    `FileNotFoundError: ...work\<应用名>\base_library.zip` 而夭折（实测发生过）。
    这条锁把它钉死：谁再把 "build" 加回清理名单，CI 立刻红。

    用**源码级**检查而不是 import run_ci —— 后者是脚本，import 会连带执行其模块级
    逻辑（含清理），对探针不安全。
    """
    import re as _re
    src = open(os.path.join(BASE, "run_ci.py"), encoding="utf-8").read()

    def _names():
        m = _re.search(r"^CLEAN_TEMP_NAMES\s*=\s*\(([^)]*)\)", src, _re.M)
        assert m, "run_ci.py 里找不到 CLEAN_TEMP_NAMES（清理名单被改名或删除了）"
        return _re.findall(r"[\"']([^\"']+)[\"']", m.group(1))

    def _names_are_plain_dirs():
        """名单必须是**非空的纯目录名**。

        原断言是 `isinstance(_names(), list)`，而 `_names()` 就是 `re.findall(...)`
        —— 永远返回 list，于是那条断言**恒真**（把名单改成 `("*",)` 或函数也照过）。
        """
        ns = _names()
        assert ns, "清理名单是空的"
        bad = [x for x in ns if (not isinstance(x, str)) or (not x)
               or ("/" in x) or ("\\" in x) or ("*" in x) or ("?" in x)]
        assert not bad, "名单里有不是纯目录名的项: %r" % (bad,)
        return True
    check("CI 清理名单存在且为非空纯目录名（不是通配符/路径）", _names_are_plain_dirs)
    check("CI 清理名单**不含**构建器的工作目录 temp/build（删它会让构建夭折）",
          lambda: "build" not in _names())

    def _builder_owns_it():
        b = open(os.path.join(BASE, "build.py"), encoding="utf-8").read()
        assert '"temp", "build"' in b, \
            "build.py 不再用 temp/build 当工作目录？那这条锁的前提变了，请复核"
        return True

    check("build.py 确实以 temp/build 为工作目录（锁的前提成立）", _builder_owns_it)

    def _cleanup_actually_run():
        """**行为**断言：在**真实位置**造一个 `temp/build` 标记，真调一次 `run_ci.cleanup()`，
        断言它还在；再用一个真实存在的 `logs/*.log` 断言 `logs/` 没被动。

        为什么不再只读源码名单：那只能覆盖三条删除路径中的一条（61 行根级 rmtree、
        84-87 的白名单、88-98 的前缀循环各是一条），而这里要钉的是**实测踩过的事故**
        （删 `temp/build` 让构建在 `base_library.zip` 处夭折）。
        为什么不做"改 `rc.HERE` 指向沙箱再调"：cleanup 读的是模块全局 `HERE`，本探针里
        实测该手法行为不一致（沙箱现场会被整体清掉，原因未查明）；而**真实位置**才是
        当年事故的场景。cleanup 本身也是 CI 每次都会跑的收尾动作，在这里调一次无副作用。
        """
        import importlib
        rc = importlib.import_module("run_ci")
        marker = os.path.join(BASE, "temp", "build", "dsh_probe_marker.txt")
        os.makedirs(os.path.dirname(marker), exist_ok=True)
        with open(marker, "w", encoding="utf-8") as f:
            f.write("ci cleanup probe")
        logs_dir = os.path.join(BASE, "logs")
        a_log = None
        if os.path.isdir(logs_dir):
            for n in sorted(os.listdir(logs_dir)):
                if n.endswith(".log"):
                    a_log = os.path.join(logs_dir, n)
                    break
        rc.cleanup()
        assert os.path.isfile(marker), \
            "cleanup() 删掉了 temp/build —— 构建会因此在 base_library.zip 处夭折！"
        if a_log is not None:
            assert os.path.isfile(a_log), "cleanup() 动了 logs/（那是排障依据）"
        try:                        # 自己造的标记自己清
            os.remove(marker)
            d = os.path.dirname(marker)
            if os.path.isdir(d) and not os.listdir(d):
                os.rmdir(d)
        except OSError:
            pass
    check("CI 清理**真跑一次**：temp/build 与 logs/ 保留（在真实位置验证）",
          _cleanup_actually_run)


def test_ci_gate_tiers():
    """run_ci 的三档门禁（fast / local / release）与"未覆盖清单"。

    方案 3 的全部价值在于：**缺外部前提时，发版档必须红、公开 CI 档必须绿**。
    所以这节钉的是那两个"退化了也不会有人发现"的地方：
      * `prereq_missing` 若忽略 `release` 参数 → 发版门禁变成"和平时一样"；
      * 收尾若忘了检查清单 → 清单记了也没人看，`--release` 白设。
    另外两条是**跨文件漂移锁**：run_ci 靠字面量识别 run_ui_smoke 的 SKIP、
    靠环境变量把 converter 路径传给 cross_validate —— 任一边改名都要在这里报出来。
    """
    import importlib
    rc = importlib.import_module("run_ci")

    check("run_ci：无参数 = local 档", lambda: rc.mode_of([]) == "local")
    check("run_ci：--fast / --release 各自解析正确",
          lambda: rc.mode_of(["--fast"]) == "fast"
          and rc.mode_of(["--release"]) == "release")

    def _both_flags_rejected():
        try:
            rc.mode_of(["--fast", "--release"])
        except ValueError:
            return
        raise AssertionError("--fast 与 --release 同时给出必须报错（两者判定相反，不许静默取其一）")
    check("run_ci：--fast 与 --release 同时给出报错", _both_flags_rejected)

    def _env_override():
        old = os.environ.get(rc.CONVERTER_ENV)
        try:
            os.environ[rc.CONVERTER_ENV] = r"X:\fake\converter.exe"
            assert rc.converter_exe() == r"X:\fake\converter.exe", "环境变量没被采纳"
            del os.environ[rc.CONVERTER_ENV]
            assert rc.converter_exe() == rc.CONVERTER_DEFAULT, "无环境变量时应回落到默认路径"
        finally:
            if old is None:
                os.environ.pop(rc.CONVERTER_ENV, None)
            else:
                os.environ[rc.CONVERTER_ENV] = old
    check("run_ci：converter 路径可被 %s 覆盖（否则换台机器永远 SKIP）" % rc.CONVERTER_ENV,
          _env_override)

    def _prereq_tiers():
        import contextlib
        import io
        saved = list(rc._NOT_COVERED)
        try:
            rc._NOT_COVERED.clear()
            buf = io.StringIO()
            # 这段会把 SKIP/FAIL 打进 stdout —— 探针自己的输出里不该出现无主的 FAIL，
            # 所以捕获起来顺便当作断言用（两档的措辞必须分别是 SKIP / FAIL）。
            with contextlib.redirect_stdout(buf):
                assert rc.prereq_missing("X 项", "没有 X", release=False) is True, \
                    "local 档缺前提不该判失败"
                assert len(rc._NOT_COVERED) == 1, "缺前提必须记进未覆盖清单（SKIP ≠ PASS）"
                assert rc.prereq_missing("X 项", "没有 X", release=True) is False, \
                    "release 档缺前提必须判失败"
            said = buf.getvalue()
            assert "SKIP" in said and "FAIL" in said, \
                "两档的输出措辞必须分别是 SKIP / FAIL：%r" % said
        finally:
            rc._NOT_COVERED[:] = saved
    check("run_ci：缺前提 local 档记 SKIP+清单、release 档判 FAIL", _prereq_tiers)

    def _final_gate():
        saved = list(rc._NOT_COVERED)
        try:
            rc._NOT_COVERED.clear()
            assert rc.final_ok(True, release=True) is True, "零未覆盖时 release 应可通过"
            rc.note_uncovered("Y 项", "没有 Y")
            assert rc.final_ok(True, release=True) is False, "release 档有未覆盖项必须整体 FAIL"
            assert rc.final_ok(True, release=False) is True, "非 release 档不该被清单影响"
            assert rc.final_ok(False, release=False) is False, "原有的 FAIL 不能被洗成 PASS"
        finally:
            rc._NOT_COVERED[:] = saved
    check("run_ci：release 档有未覆盖项即整体 FAIL（且不掩盖原有 FAIL）", _final_gate)

    def _skip_mark_matches():
        src = open(os.path.join(BASE, "run_ui_smoke.py"), encoding="utf-8").read()
        assert rc.UI_SMOKE_SKIP_MARK in src, (
            "run_ci 用 %r 识别「无桌面」的 SKIP，而 run_ui_smoke.py 里没有这个字面量："
            "两边一旦漂移，无桌面时 run_ci 会把 SKIP 当失败（或反之当通过）"
            % rc.UI_SMOKE_SKIP_MARK)
    check("run_ci：UI 冒烟的 SKIP 标识与 run_ui_smoke.py 一致（防漂移）", _skip_mark_matches)

    def _xv_env_matches():
        src = open(os.path.join(BASE, "cross_validate.py"), encoding="utf-8").read()
        assert rc.CONVERTER_ENV in src, (
            "cross_validate.py 没读 %s：run_ci 回传的路径会被它忽略" % rc.CONVERTER_ENV)
    check("run_ci：cross_validate.py 与 run_ci 读同一个 converter 环境变量", _xv_env_matches)


def main():
    print("=" * 62)
    print("构建器自检（不触发真实构建）")
    print("=" * 62)
    print("\n[1] 版本模块")
    test_version_module()
    print("\n[2] 版本号写回")
    test_save_base_version()
    print("\n[3] 版本号与标记的持久化")
    test_version_and_marker_persistence()
    print("\n[4] 预发布标记的序号计数（按 (完整版本, 标记名) 各自计数）")
    test_prerelease_counter()
    print("\n[5] 构建次数与标记序号的存储位置（都在 toolkit_base.py）")
    test_counters_in_toolkit_base()
    print("\n[6] build.py 参数解析")
    test_build_args()
    print("\n[7] build.py 的标记自增 / 显式优先（不触发真实构建）")
    test_build_prerelease_auto_increment()
    print("\n[8] 产物目录编号（不覆盖历史版本）")
    test_next_build_dir()
    print("\n[9] build_gui 无头构造与交互")
    try:
        test_build_gui_construction()
    except Exception as e:
        # 只有"机器上没有可用桌面"（tkinter 抛 TclError）才允许降级成 SKIP。
        # 原先这里是 catch-all：`BuildGUI` 构造失败这种**真回归**会打一行 SKIP、
        # PASS 计数不变、RESULT 仍 PASS —— 正是本仓库反复治理的"假绿"。
        # 用类型名判断而不是 `except tk.TclError`：本探针不在模块级 import tkinter
        # （pyflakes 会报 undefined name），而 tkinter 只在 [9] 段内部局部导入。
        if type(e).__name__ == "TclError":
            skip("build_gui 无头构造与交互", "无桌面环境: %s" % e)
        else:
            FAIL.append("build_gui 无头构造与交互（真实失败，不是环境问题）")
            print("  FAIL build_gui 无头构造与交互 -> %s: %s" % (type(e).__name__, e))
            for line in traceback.format_exc().strip().splitlines()[-3:]:
                print("       " + line.strip())
    print("\n[10] CI 清理范围不得包含构建器的工作目录")
    test_ci_cleanup_excludes_builder_temp()
    print("\n[11] run_ci 三档门禁（fast / local / release）与未覆盖清单")
    test_ci_gate_tiers()
    print("\n[12] 构建事务（失败回退 / FAIL 归档 / 日志同名 / 崩溃快照）")
    test_build_transaction()
    print("\n" + "=" * 62)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        for n in FAIL:
            print("  - " + n)
    if SKIP:
        for n in SKIP:
            print("  ~ SKIP " + n)
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
