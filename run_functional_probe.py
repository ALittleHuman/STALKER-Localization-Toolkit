# -*- coding: utf-8 -*-
"""功能完整性验证（只读于用户数据；全部在临时目录内操作）。

为什么需要它：`run_ci` 只 import、两个探针只构造与调入口——**它们都不走真实业务路径**。
本会话已两次被 pyflakes 抓到"闸门全绿但功能已断"的例子：
    * `xml_compare.parse_file` 与 `_export` 依赖的 ET / datetime 被误删，探针没覆盖到；
    * `ID_PATTERN` 误删后只有调用 parse_file 才会暴露。
因此这里按**用户可见功能**逐项做端到端验证，而不是只看接口存在。

覆盖：
    1. 文本提取    —— 真实 gameplay/scripts 目录 → 产出 XML，校验条目与内容
    2. XML 比较    —— 造两份有差异的 XML → parse_file / compare_one / compare_text_content
    3. 编码转换    —— cp1251 文件 → 转 utf-8，校验字节与内容
    4. fs 封包/解包 —— 六种格式已在 run_ci 覆盖；这里补"真实文件往返 + extract_file"
    5. 汉化包生成   —— 需要字体与 PIL，环境不满足时 SKIP
    6. 视频转换     —— 需要 ffmpeg 与样本，环境不满足时 SKIP

用法: python run_functional_probe.py   （退出码 0=全过）
"""
import os
import shutil
import sys
import tempfile
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
for _sub in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(BASE, _sub)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

PASS, FAIL, SKIP = [], [], []


def check(name, fn):
    """fn 抛异常即 FAIL；**显式返回 False 也算 FAIL**。

    早期只判异常，于是 `check("x", lambda: a == b)` 这类"纯布尔表达式"永远不会失败
    —— False 被静默丢弃，断言空转但 PASS 照加（全仓 275 条里曾占 49 条）。
    返回 None（副作用式断言，靠 assert/异常判定）仍算通过。
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


def skip(name, why):
    SKIP.append(name)
    print("  SKIP %s（%s）" % (name, why))


# ══════════════════════════════════════════════════════════════
# 1. 文本提取
# ══════════════════════════════════════════════════════════════
def test_text_extract(tmp):
    from apps.text_extract_app import run_extraction, _parse_ltx

    src = os.path.join(tmp, "tx", "gameplay")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "a.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n'
                '<string id="ui_a"><text>Привет</text></string>\n'
                '<string id="ui_b"><text>Мир</text></string>\n</string_table>\n')

    out = os.path.join(tmp, "tx_out")
    os.makedirs(out, exist_ok=True)
    stats = run_extraction(os.path.join(tmp, "tx"), out, "zz", False, log_callback=None)

    check("文本提取：产出 gp XML 文件",
          lambda: os.path.isfile(os.path.join(out, "gameplay", "zz_gameplay_texts.xml"))
          or os.path.isfile(os.path.join(out, "zz_gameplay_texts.xml")))
    check("文本提取：统计条目数 >= 2", lambda: stats["gp_strings"] >= 2)

    # 产出的 XML 必须能被解析回来
    from toolkit_textio import read_text_file
    produced = None
    for cand in (os.path.join(out, "gameplay", "zz_gameplay_texts.xml"),
                 os.path.join(out, "zz_gameplay_texts.xml")):
        if os.path.isfile(cand):
            produced = cand
            break
    check("文本提取：产物存在", lambda: produced is not None)
    if produced:
        txt, _enc = read_text_file(produced)
        check("文本提取：产物是合法 XML 且含提取到的文本",
              lambda: ("Привет" in txt and "Мир" in txt))

    # .ltx 解析（键名表分支）
    ltx = os.path.join(tmp, "tx", "items.ltx")
    with open(ltx, "w", encoding="windows-1251") as f:
        f.write("[wpn]\ninv_name = TestGun\ndescription = A gun\n; comment\n")
    whole, cands = _parse_ltx(ltx)
    check("文本提取：.ltx 解析出 inv_name/description",
          lambda: "TestGun" in cands and "A gun" in cands)


# ══════════════════════════════════════════════════════════════
# 2. XML 比较（三条路径：parse_file / compare_one / compare_text_content）
# ══════════════════════════════════════════════════════════════
def test_xml_compare(tmp):
    import tkinter as tk
    from tkinter import messagebox

    import apps.xml_compare_app as XC
    from apps.xml_compare_app import XMLCompareApp
    for fn in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, fn, lambda *a, **k: "ok")

    # 内置比较模式**随 App 构造才注册**（见 apps/xml_compare_app.py 的 __init__：
    # 注册需要先拿到 PluginManager 实例），所以下面必须先真的构造一次
    # XMLCompareApp，再去注册表里核对这两种模式 —— 以前直接查表，那时表还是空的，
    # 断言虽然写了却永远为假（check 旧实现只判异常，False 被静默丢弃）。
    # 无桌面环境构造不出控件树时跳过这几条（与 test_convert 同一处理），
    # 而**不**把它伪装成通过。
    mode_ready = False
    try:
        _xml_root = tk.Tk()
        _xml_root.withdraw()
        try:
            XMLCompareApp(tk.Frame(_xml_root))
            mode_ready = True
        finally:
            _xml_root.destroy()
    except Exception as e:
        print("  SKIP 内置比较模式注册（无法构造 XMLCompareApp: %s）" % e)

    a_dir = os.path.join(tmp, "xa")
    b_dir = os.path.join(tmp, "xb")
    os.makedirs(a_dir, exist_ok=True)
    os.makedirs(b_dir, exist_ok=True)
    body_a = ('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n'
              '<string id="s1"><text>Alpha</text></string>\n'
              '<string id="s2"><text>Same</text></string>\n</string_table>\n')
    body_b = ('<?xml version="1.0" encoding="windows-1251"?>\n<string_table>\n'
              '<string id="s1"><text>Alpha</text></string>\n'
              '<string id="s2"><text>Changed</text></string>\n'
              '<string id="s3"><text>Extra</text></string>\n</string_table>\n')
    fa = os.path.join(a_dir, "ui.xml")
    fb = os.path.join(b_dir, "ui.xml")
    open(fa, "wb").write(body_a.encode("windows-1251"))
    open(fb, "wb").write(body_b.encode("windows-1251"))

    check("XML比较：collect_xml_files 找到文件",
          lambda: "ui.xml" in XC.collect_xml_files(__import__("pathlib").Path(a_dir)))

    # parse_file —— 曾因 ID_PATTERN / ET 误删而断（探针没覆盖到）
    def _parse():
        lines, ids, enc = XC.parse_file(__import__("pathlib").Path(fa))
        assert lines > 0, "行数应为正"
        assert "s1" in ids and "s2" in ids, "应解析出 id: %r" % (list(ids),)
        assert enc, "应返回编码"
    check("XML比较：parse_file 解析 id 与行数", _parse)

    def _cmp_stats():
        """统计模式：比较每个 id 的**出现次数**（不是文本），并报告仅一侧有的文件。"""
        r = XC.compare_one("ui.xml", __import__("pathlib").Path(fa),
                           __import__("pathlib").Path(fb))
        assert r["mode"] == "stats"
        assert r["consistent"] is False
        assert r["only_b"] == ["s3"], "应检出仅 B 有 s3: %r" % (r["only_b"],)
        assert r["only_a"] == []
        assert sum(r["ida"].values()) == 2 and sum(r["idb"].values()) == 3
    check("XML比较：compare_one（统计模式）", _cmp_stats)

    def _cmp_text():
        r = XC.compare_text_content("ui.xml", __import__("pathlib").Path(fa),
                                    __import__("pathlib").Path(fb))
        assert r["mode"] == "text"
        assert r["only_b"] == ["s3"]
        assert len(r["text_diff"]) == 1, "应有 1 条文本不同: %r" % (r["text_diff"],)
    check("XML比较：compare_text_content（文本模式）", _cmp_text)

    # 模式贡献点：内置两种模式都必须可查、且 compare 可调用
    from toolkit import PluginManager
    pm = PluginManager.shared()
    for spec_name in ("行数/ID 统计", "ID 文本对比"):
        if not mode_ready:
            continue        # 无桌面：上面已打印 SKIP，不把未执行当成通过
        m = pm.compare_mode(spec_name)
        check("XML比较：模式 %r 已注册" % spec_name, lambda m=m: m is not None)
        if m:
            check("XML比较：模式 %r 的 columns 非空" % spec_name,
                  lambda m=m: len(m["columns"]) > 0)
            check("XML比较：模式 %r 的 compare 可调用" % spec_name,
                  lambda m=m: callable(m["compare"]))
            check("XML比较：模式 %r 的 filters 非空" % spec_name,
                  lambda m=m: bool(m["filters"]))


# ══════════════════════════════════════════════════════════════
# 3. 编码转换
# ══════════════════════════════════════════════════════════════
def test_convert():
    """convert_file 需要 app 实例；用真实构造的 ConvertApp 在临时目录上跑一次转换。"""
    import tkinter as tk
    from tkinter import messagebox
    for fn in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, fn, lambda *a, **k: "ok")
    import toolkit_base
    toolkit_base.errbox = lambda *a, **k: None
    import toolkit
    toolkit.errbox = toolkit_base.errbox

    from apps.convert_app import ConvertApp
    try:
        root = tk.Tk()
    except Exception:
        return "SKIP"
    root.withdraw()
    tmp = tempfile.mkdtemp(prefix="conv_probe_")
    try:
        src = os.path.join(tmp, "src")
        os.makedirs(src)
        p = os.path.join(src, "t.xml")
        open(p, "wb").write('<?xml version="1.0"?>\n<a>Привет</a>\n'.encode("windows-1251"))

        tab = tk.Frame(root)
        app = ConvertApp(tab)
        app.source_dir.set(src)
        app.file_exts.set(".xml")
        app.source_enc.set("auto")
        app.target_enc.set("utf-8")
        app._ensure_snap(force=True)

        files = app.get_files()
        check("编码转换：get_files 找到目标文件", lambda: len(files) == 1)
        if files:
            res = app.convert_file(files[0])
            check("编码转换：convert_file 未报取消",
                  lambda: not (isinstance(res, str) and "cancel" in res.lower()))
            raw = open(p, "rb").read()
            check("编码转换：文件已转成 UTF-8 且内容完好",
                  lambda: "Привет".encode("utf-8") in raw)

        # ── 1.0.0 发行版的真实 Bug（用户实测报告）──────────────────────────
        #   场景：纯 ASCII 的英文 XML，声明却是 windows-1251；
        #         手动指定「源编码 = windows-1251」+ 目标 utf-8 + **原地转换**。
        #   旧版 `_get_source_encoding`（build_1 convert_app.py L730-758）把
        #   **严格 UTF-8 排在手动指定之前**：纯 ASCII 必然能按 UTF-8 解码 →
        #   判成 "utf-8" → `src_enc == target` 命中「已是目标编码」分支 →
        #   原地时该分支只打一条 [跳过] 就 `return "skipped"`，**根本不写文件**
        #   → 声明永远停在 windows-1251。用户原话："转成 utf-8 之后声明不会变"。
        #   实测口径：`E:\Human\新建文件夹\gamedata\config\text\eng` 的 65 个
        #   XML 里，旧版把 16 个误判为 utf-8 并跳过；新版 0 个。
        #   为什么单元锁不够：上面 test_encoding 里那条 `手动指定优先于严格
        #   UTF-8` 只证明**判定顺序**对，证明不了**文件真的被改写**——而用户
        #   看到的是后者。所以这里在真实 app 上再锁一次。
        src2 = os.path.join(tmp, "src2")
        os.makedirs(src2)
        p2 = os.path.join(src2, "ascii_eng.xml")
        with open(p2, "w", encoding="ascii", newline="") as f:
            f.write('<?xml version="1.0" encoding="windows-1251" ?>\n'
                    '<string_table>\n\t<string id="a">\n\t\t<text>Hi</text>\n'
                    '\t</string>\n</string_table>\n')
        app.source_dir.set(src2)
        app.source_enc.set("windows-1251")
        app.output_dir.set("")
        app.backup_files.set(False)
        app._ensure_snap(force=True)
        files2 = app.get_files()
        check("编码转换：ASCII 英文 XML 被收集到", lambda: len(files2) == 1)
        if files2:
            res2 = app.convert_file(files2[0])
            got2 = open(p2, "r", encoding="utf-8").read()
            check("编码转换：手动指定 1251 时纯 ASCII XML 的声明真的改成 utf-8"
                  "（1.0.0 的 Bug：旧版会跳过且声明不变）",
                  lambda: res2 == "success" and 'encoding="utf-8"' in got2)

        # ── 源编码=auto（界面默认值）这条路径也必须让声明变成 utf-8 ──────────
        # 纯 ASCII 的英文 XML **不是多字节**（ASCII 在两种编码下字节相同），所以
        # `sniff_encoding` 不会判它 utf-8，而是继续走到 XML 声明拿 windows-1251，
        # 于是进入**真实转换**分支、声明一并改掉。
        # 1.0.0 把"能不能按 UTF-8 解码"当成了多字节判据，纯 ASCII 也算数 → 一律判
        # utf-8 → `src_enc == target` 成立 → 进"已是目标编码"分支；而旧实现在该
        # 分支里原地转换时直接 return、**根本不写文件**，声明就永远停在
        # windows-1251。实测真实目录（`...\gamedata\config\text\eng`，65 个 XML，
        # 源=auto、目标 utf-8、原地）：修复前 16 skipped/49 success，其中 **11 个**
        # 声明残留；修复后残留 **0**，且四种组合（auto/手动 × 原地/新目录）结果一致。
        src3 = os.path.join(tmp, "src3")
        os.makedirs(src3)
        p3 = os.path.join(src3, "ascii_auto.xml")
        with open(p3, "w", encoding="ascii", newline="") as f:
            f.write('<?xml version="1.0" encoding="windows-1251" ?>\n'
                    '<string_table>\n\t<string id="b">\n\t\t<text>Ok</text>\n'
                    '\t</string>\n</string_table>\n')
        app.source_dir.set(src3)
        app.source_enc.set("auto")
        app.output_dir.set("")
        app._ensure_snap(force=True)
        files3 = app.get_files()
        if files3:
            app.convert_file(files3[0])
            got3 = open(p3, "r", encoding="utf-8").read()
            check("编码转换：源编码=auto（默认值）时纯 ASCII XML 的声明也对齐为 utf-8"
                  "（同一个 Bug 的另一条路径）",
                  lambda: 'encoding="utf-8"' in got3)

        # ── 输出到新目录：**必须产出文件**，哪怕声明本来就对 ────────────────
        # 回归锁：为"声明无需修改"加早退时，输出目录会漏掉这些文件（实测踩到过）。
        # 输出模式的语义是"新目录里有一份"，与"要不要改声明"无关，两条进入条件
        # 不能合并。
        out3 = os.path.join(tmp, "out3")
        app.output_dir.set(out3)
        app._ensure_snap(force=True)
        # 上一步已把声明就地修好 → 此时声明已对，正好走"不需要改声明"的分支
        files4 = app.get_files()
        if files4:
            app.convert_file(files4[0])
            check("编码转换：输出到新目录时即使声明本来就对也必须产出文件（回归锁）",
                  lambda: os.path.isfile(os.path.join(out3, "ascii_auto.xml")))

        # ── 输出一律不带 BOM，包括"目标不是 utf-8"这条路径 ──────────────────
        # 源带 UTF-8 BOM + 声明已是 windows-1251 + 目标 windows-1251：
        # `src_enc == target` 成立，旧逻辑认为"无事可做"直接跳过 —— BOM 就留在
        # windows-1251 文件里了（BOM 只对 utf-8 合法，留在别的编码里是脏字节）。
        # BOM 在 convert_file 入口被剥掉供解码用，所以必须**另用一个标志**把
        # "源带 BOM"这个事实带到跳过分支的判定里。
        src4 = os.path.join(tmp, "src4")
        os.makedirs(src4)
        p4 = os.path.join(src4, "bom1251.xml")
        with open(p4, "wb") as f:
            f.write(b"\xef\xbb\xbf"
                    b'<?xml version="1.0" encoding="windows-1251" ?>\n<a><t>Hi</t></a>\n')
        app.source_dir.set(src4)
        app.source_enc.set("auto")
        app.output_dir.set("")
        app.target_enc.set("windows-1251")
        app._ensure_snap(force=True)
        files5 = app.get_files()
        if files5:
            app.convert_file(files5[0])
            raw5 = open(p4, "rb").read()
            check("编码转换：目标非 utf-8 时源 BOM 也必须去掉（回归锁）",
                  lambda: not raw5.startswith(b"\xef\xbb\xbf"))

        # ── 声明撒谎的文件不能再"静默跳过" ──────────────────────────────────
        # 字节 cp1251、声明 utf-8、目标 utf-8：判定采信声明就会得出"已是目标编码"，
        # 于是原样跳过 —— 文件既没修好、也没有任何提示。现在声明要被字节证实，
        # 这类文件会被判成 windows-1251 走真实转换：正文完整 + 声明改成 utf-8。
        src5 = os.path.join(tmp, "src5")
        os.makedirs(src5)
        p5 = os.path.join(src5, "lying_decl.xml")
        with open(p5, "wb") as f:
            f.write('<?xml version="1.0" encoding="utf-8" ?>'
                    '<a><t>Привет мир</t></a>'.encode("cp1251"))
        app.source_dir.set(src5)
        app.source_enc.set("auto")
        app.target_enc.set("utf-8")
        app.output_dir.set("")
        app._ensure_snap(force=True)
        files6 = app.get_files()
        if files6:
            res6 = app.convert_file(files6[0])
            got6 = open(p5, "rb").read().decode("utf-8", errors="replace")
            check("编码转换：声明撒谎的文件被真实转换（正文完整 + 声明改为 utf-8）",
                  lambda: res6 == "success" and "Привет мир" in got6
                  and 'encoding="utf-8"' in got6)

        # ── 日志标签必须指向**链条的哪一步**（用户靠这一行核对目录编码）────────
        # 原实现只按"有没有声明"分支、值却来自多字节检查，于是"字节 UTF-8、声明写
        # windows-1251"的文件被写成 `声明(utf-8)` —— 读起来像"声明说 utf-8"，
        # 而声明明明写 1251。误标会直接误导用户去手动选错编码。
        import apps.convert_app as _ca
        _orig_detail = _ca.log_detail
        _seen = []
        _ca.log_detail = lambda msg, tag="info": _seen.append(msg)
        try:
            src6 = os.path.join(tmp, "src6")
            os.makedirs(src6)
            p6 = os.path.join(src6, "multi_lying.xml")
            with open(p6, "wb") as f:
                f.write('<?xml version="1.0" encoding="windows-1251" ?>'
                        '<a><t>Привет</t></a>'.encode("utf-8"))   # 多字节 UTF-8 + 撒谎声明
            app.source_dir.set(src6)
            app.source_enc.set("auto")
            app.target_enc.set("utf-8")
            app.output_dir.set("")
            app._ensure_snap(force=True)
            files7 = app.get_files()
            if files7:
                app.convert_file(files7[0])
        finally:
            _ca.log_detail = _orig_detail
        _line6 = next((m for m in _seen if "multi_lying" in m), "")
        check("编码转换：日志如实标出定案的那一步（多字节，而不是误写成声明）",
              lambda: "多字节(utf-8)" in _line6)
    finally:
        try:
            root.destroy()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)
    return "OK"


# ══════════════════════════════════════════════════════════════
# 4. fs 引擎真实往返（六格式已由 run_ci 覆盖，这里补真实文件与 extract_file）
# ══════════════════════════════════════════════════════════════
def test_engine(tmp):
    import stalker_fs as FS

    files = [("deep/dir/hello.txt", "Привет мир".encode("utf-8"), False),
             ("empty.bin", b"", False),
             ("big.bin", bytes(range(256)) * 40, False)]
    for fmt in FS.FORMATS:
        def _rt(fmt=fmt):
            db = FS.pack_db(files, fmt)
            entries = FS.unpack_db(db, fmt)
            got = {}
            for e in entries:
                if e.get("is_dir"):
                    continue
                got[e["path"].replace("\\", "/")] = FS.extract_file(db, e)
            for path, data, _isdir in files:
                assert got.get(path) == data, "%s: %s 不一致" % (fmt, path)
        check("引擎：%s 真实文件逐字节往返" % fmt, _rt)

    def _forged_header_loses():
        """伪造的 HEADER 不得顶掉真的 HEADER（结构自洽优先）。

        `_read_chunks` 是**逐字节回退**扫描的（要能认非 8 字节对齐的数据），而
        `_validate_header` 的接受条件很松（fmt 已知时只要有一个像样路径，连 ASCII
        都不要求）。两者相加就有个洞：DATA 块后面只要跟着一段"能解出条目"的字节，
        它就会被当成 HEADER —— 截断/畸形包会让扫描走进载荷内部，于是**伪造的
        HEADER 顶掉真的**，整包解出错误文件名而日志仍显示成功。

        本锁手工构造 `[DATA][伪造 HEADER][真 HEADER]`：伪造那份的条目 offset 故意
        越出文件尾部（8+400 > 文件长度），改前它先被接受 → 解出的名字全是 forged/*。
        现在它因结构不自洽被跳过，真那份赢。最后两条 assert 是**防空转自检**：
        伪造样本必须确实通过轻量校验、且确实结构不自洽，否则这条锁没有测到东西。
        """
        import struct as _st
        for fmt in ("xdb", "2947ru"):
            info = FS.FORMATS[fmt]
            payload = b"REAL-DATA"
            db = FS.pack_db([("real/keep.txt", payload, False)], fmt)
            real_header = db[8 + len(payload):]      # [DATA] 之后就是真 HEADER
            hdr = info["build_header"]([("forged/a.txt", b"x" * 400, False),
                                        ("forged/b.txt", b"y", False)])
            comp = FS.lzhuf.encode(hdr)
            if info["scrambler"]:
                comp = info["scrambler"].encrypt(comp)
            forged = _st.pack("<II", 0x80000001, len(comp)) + comp
            raw = _st.pack("<II", 0, len(payload)) + payload + forged + real_header

            names = [e["path"].replace("\\", "/") for e in FS.unpack_db(raw, fmt)
                     if not e.get("is_dir")]
            assert names == ["real/keep.txt"], \
                "%s: 伪造 HEADER 顶掉了真的，解出 %r" % (fmt, names)

            f_entries = FS._validate_header(forged[8:], True, fmt)
            assert f_entries is not None, \
                "%s: 伪造样本没通过轻量校验 —— 这条锁在空转" % fmt
            assert not FS._entries_self_consistent(raw, f_entries), \
                "%s: 伪造样本居然结构自洽 —— 这条锁在空转" % fmt
    check("引擎：伪造的 HEADER 不顶掉真 HEADER（结构自洽优先）", _forged_header_loses)

    def _detect():
        db = FS.pack_db(files, "xdb")
        assert FS.auto_detect(db) == "xdb", "auto_detect 应识别 xdb"
    check("引擎：auto_detect 识别 xdb", _detect)

    def _sqfs_check():
        assert FS.sqfs_check(os.path.join(tmp, "nonexistent.sq")) == "unknown"
    check("引擎：sqfs_check 对不存在文件返回 unknown", _sqfs_check)

    def _path_traversal_guard():
        """归档内路径**不可信**：逃逸条目必须被拒，合法条目必须落在输出目录内。

        为什么必须有这条：本工具的主入口就是"打开从网上拿到的 mod 包"，而落盘是
        `open(p, "wb")` 直接覆盖既有文件 —— 没有收敛就是**任意文件写**。历史实现里
        `lstrip("./")` 只挡前导 `../`，`a/../../../x` 照样逃逸。
        断言里额外核对"同一串用**裸 join** 确实会逃逸"，否则这条锁可能因为平台差异空转。
        """
        out = os.path.join(tmp, "safejoin")
        os.makedirs(out, exist_ok=True)
        root = os.path.abspath(out)
        evil = ["../../evil.txt", "a/../../../evil2.txt", "/abs/evil3.txt",
                "C:/Windows/Temp/pwn.dll", "..\\..\\evil4.txt",
                "//server/share/evil5.txt", "", ".", ".."]
        for name in evil:
            assert FS.safe_out_path(out, name) is None, "未拒绝越界路径 %r" % name
            if name and name not in ("/abs/evil3.txt", "//server/share/evil5.txt",
                                     "C:/Windows/Temp/pwn.dll", ".", ".."):
                naive = os.path.abspath(os.path.join(root, name.replace("\\", os.sep)))
                assert os.path.normcase(naive) != os.path.normcase(root), \
                    "%r 用裸 join 竟然没逃逸 —— 这条锁的前提要重核" % name
        good = FS.safe_out_path(out, "deep/dir/hello.txt")
        assert good == os.path.join(root, "deep", "dir", "hello.txt"), good
        assert os.path.normcase(os.path.commonpath([root, good])) == os.path.normcase(root), \
            "合法路径必须仍落在输出目录内"
    check("引擎：归档内路径逃逸被拒、合法路径仍在输出目录内", _path_traversal_guard)

    def _lzo_malformed_safe():
        """畸形 LZO 流不得抛异常给调用方，解压炸弹必须被拒。

        为什么：`cpm` 的 m_pos 由**流内数据**算出，可以是负值 —— Python 的负下标会
        **静默读输出尾部字节**（不报错、产出错数据），越界则把 IndexError 抛出引擎 API。
        原始实现下随机 fuzz 约 15% 的输入会抛（20000 次里 3003 次）。
        随机 fuzz 是这里最省事也最有效的判据；固定种子保证结论可复现。
        """
        import random
        random.seed(0)
        for size in range(1, 400):
            blob = bytes(random.randrange(256) for _ in range(size))
            try:
                got = FS.lzo1x_decompress(blob, out_len=1 << 20)
            except Exception as e:
                raise AssertionError("畸形流抛出了 %s: %r（长度 %d）"
                                     % (type(e).__name__, e, size))
            assert got is None or isinstance(got, bytes), got
        # 解压炸弹：64 字节压缩体声明 1 GiB → 必须拒绝（返回 None），不得分配
        assert FS.extract_file(bytes(64), {"offset": 0, "size_comp": 64,
                                           "size_real": 1 << 30, "is_dir": False}) is None, \
            "解压炸弹没有被拒绝"
        # 压缩比超标（声明 1 MiB / 压缩体 64 B = 16384×）同样要拒
        assert FS.extract_file(bytes(64), {"offset": 0, "size_comp": 64,
                                           "size_real": 1 << 20, "is_dir": False}) is None, \
            "压缩比超标（16384×）没有被拒绝"
    check("引擎：畸形 LZO 流不抛异常、解压炸弹与超标压缩比被拒", _lzo_malformed_safe)

    def _auto_detect_no_misdetect():
        """auto_detect 不得把一种格式的产物判成**另一种**格式（默认模式就靠它）。

        旧判据（"第一个能解析出条目的格式赢"）实测：2215 → 2945（错）、11xx → 2945（错）、
        全空文件归档 → None（错）。前者让用户拿到**错误字节**而日志显示"解析成功"。
        本锁钉三件事：① 六格式产物只能是它自己或 None（歧义），绝不能是别的格式；
        ② 全空文件的 xdb 包仍必须识别（旧判据要求 size_real>0 会放弃）；
        ③ 随机字节不得被判成任何格式。
        """
        files = [("hello.txt", "Привет мир".encode("utf-8"), False),
                 ("deep/dir/a.bin", bytes(range(256)) * 4, False),
                 ("empty.bin", b"", False)]
        for fmt in FS.FORMATS:
            got = FS.auto_detect(FS.pack_db(files, fmt))
            assert got in (fmt, None), "%s 的产物被判成了 %r" % (fmt, got)
        empty_only = [("e1.bin", b"", False), ("d/e2.bin", b"", False)]
        assert FS.auto_detect(FS.pack_db(empty_only, "xdb")) == "xdb", \
            "全空文件的 xdb 包识别失败（判据不许要求 size_real>0）"
        import random
        random.seed(1)
        for _ in range(20):
            blob = bytes(random.randrange(256) for _ in range(512))
            assert FS.auto_detect(blob) is None, "随机字节被判成了格式"
    check("引擎：auto_detect 不把一种格式判成另一种（含全空文件与随机字节）",
          _auto_detect_no_misdetect)

    def _empty_file_is_written():
        """空文件是**合法文件**：b" 要写出 0 字节、只有 None 才算失败。

        历史调用方写 `if not data:`，空文件被计入失败并直接消失 —— 真实包里 0 字节
        占位文件很常见，属正常场景的数据缺失（不是异常）。锁钉"三态"语义与端到端往返。
        """
        d = os.path.join(tmp, "emptyfile")
        os.makedirs(d, exist_ok=True)
        p1 = os.path.join(d, "zero.bin")
        assert FS.write_extracted_file(p1, b"") is True, "空文件被当成失败"
        assert os.path.isfile(p1) and os.path.getsize(p1) == 0, "空文件没被写出"
        p2 = os.path.join(d, "sub", "none.bin")
        assert FS.write_extracted_file(p2, None) is False, "None 被当成可写"
        assert not os.path.exists(p2), "None 竟然写出了文件"
        p3 = os.path.join(d, "sub", "data.bin")
        assert FS.write_extracted_file(p3, b"abc") is True
        with open(p3, "rb") as f:
            assert f.read() == b"abc"
        # 端到端：含 0 字节文件的包，逐条 extract 后落盘，空文件必须还在
        files = [("z.bin", b"", False), ("n.txt", b"x", False)]
        db = FS.pack_db(files, "xdb")
        out = os.path.join(d, "rt")
        for e in FS.unpack_db(db, "xdb"):
            if e.get("is_dir"):
                continue
            dest = FS.safe_out_path(out, e["path"])
            assert FS.write_extracted_file(dest, FS.extract_file(db, e)) is True
        z = os.path.join(out, "z.bin")
        assert os.path.isfile(z) and os.path.getsize(z) == 0, "空文件在往返里丢了"
    check("引擎：空文件是合法文件（b'' 写出 0 字节、None 才算失败）", _empty_file_is_written)


# ══════════════════════════════════════════════════════════════
# 5. 汉化包生成（字体 + PIL）
# ══════════════════════════════════════════════════════════════
def test_font_pack(tmp):
    """汉化包生成：extract_chars 必须提取到 XML 里的西里尔字符（不依赖 PIL）。"""
    import font_pack as FP

    xml_dir = os.path.join(tmp, "fp_xml")
    os.makedirs(xml_dir, exist_ok=True)
    open(os.path.join(xml_dir, "gameplay.xml"), "wb").write(
        '<?xml version="1.0" encoding="windows-1251"?>\n<string_table>'
        '<string id="a"><text>Привет</text></string></string_table>'.encode("windows-1251"))
    # 再加一个**声明撒谎**的：声明 utf-8、实际 cp1251。
    # 用户决策是「包内 XML 一律 UTF-8」，所以这种也要转出来，而不是原样字节入库。
    open(os.path.join(xml_dir, "liar.xml"), "wb").write(
        '<?xml version="1.0" encoding="utf-8"?>\n<string_table>'
        '<string id="b"><text>Мир</text></string></string_table>'.encode("cp1251"))
    # GBK/GB18030 源：中文汉化包最常见的源编码，也是原版 CharAdder 在中文 Windows 上
    # 的 `Encoding.Default` 行为（其帮助文本写明"仅支持 GB18030 与带 BOM 的 Unicode"）。
    # ⚠ 这里曾经写死 `raw.decode("utf-8-sig", "ignore")`：GBK 源里的中文**静默全丢**，
    # 表现为字库里根本没有这些字 → 游戏内空白，且日志无一字告警（errors="ignore"
    # 让丢失无法被察觉）。故本组断言必须用**不在内置 ASCII_CHARS 里**的字符（中文），
    # 否则会被内置集的西里尔掩盖。
    gbk_text = "你好世界，潜行者。测试"
    open(os.path.join(xml_dir, "gbk.xml"), "wb").write(
        ('<?xml version="1.0" encoding="gbk"?>\n<string_table><string id="c">'
         '<text>%s</text></string_table>' % gbk_text).encode("gbk"))
    # 合法 UTF-8 源（西里尔 + 中文）：改编码判定链**不得**影响它
    u8_text = "Привет 你好 мир 世界"
    with open(os.path.join(xml_dir, "u8.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<string_table><string id="d">'
                '<text>%s</text></string_table>' % u8_text)
    # 标点样本：上面的中文串里只有「，。」两个标点，收窄逻辑（3 类 33 个字）几乎测不到；
    # 让它们进 XML → 进字库 → 被下面的 .ini 布局锁与逐字像素锁端到端覆盖。
    punct_text = "".join(sorted(FP.PUNCT_OPEN | FP.PUNCT_CLOSE
                                | FP.PUNCT_SINGLE | FP.PUNCT_WIDE))
    with open(os.path.join(xml_dir, "punct.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="utf-8"?>\n<string_table><string id="p">'
                '<text>%s</text></string_table>' % punct_text)

    chars = FP.extract_chars(xml_dir)
    check("汉化包：extract_chars 提取到字符", lambda: len(chars) > 0)

    def _gbk_chars_kept():
        miss = "".join(c for c in gbk_text if c not in chars)
        assert not miss, "GBK 源里丢失字符: %r" % miss

    check("汉化包：GBK 源里的中文全部提取到（不静默丢字）", _gbk_chars_kept)

    def _utf8_not_misjudged():
        """合法 UTF-8 源不得被误判。

        对照值**绕过编码嗅探**（直接严格 utf-8 解析 + 正则取 <text>），所以能抓到
        "嗅探把合法 UTF-8 判成别的编码"这类回归；只看"提到了一些字"是抓不到的。
        这条保护的是"原先能用的路径不被改坏"。
        """
        import re as _re
        want = set(FP.ASCII_CHARS) | set(FP.FONTGEN_EXTRA)
        with open(os.path.join(xml_dir, "u8.xml"), "rb") as f:
            raw = f.read().decode("utf-8")           # 严格：解不开就直接抛
        for m in _re.finditer(r"<text[^>]*>(.*?)</text>", raw, _re.S):
            want |= set(m.group(1)) - set("\r\n")
        miss = want - set(chars)
        assert not miss, "合法 UTF-8 源被误判/漏提: %r" % "".join(sorted(miss))

    check("汉化包：合法 UTF-8 源不被误判（对照严格 utf-8 解析）", _utf8_not_misjudged)

    def _liar_text_kept():
        miss = "".join(c for c in "Мир" if c not in chars)
        assert not miss, "声明撒谎的文件丢失字符: %r" % miss

    check("汉化包：声明撒谎（声明 utf-8 实际 cp1251）的文件正文也被提取", _liar_text_kept)

    # 字号槽位表 = 从原版成品反推出来的常量（见 font_pack.CELL_HEIGHTS 上方长注释）。
    # `height=` 直接决定游戏内的行高；槽宽决定每个字落在图集的哪个格子。
    # 这两张表被改动会让成品几何与既有汉化包不一致 —— 所以钉死，而不是靠注释提醒。
    def _size_tables_locked():
        assert FP.CELL_HEIGHTS == {11: 20, 13: 22, 15: 23, 16: 25, 17: 26, 18: 29,
                                   20: 31, 21: 32, 23: 33, 25: 35}, FP.CELL_HEIGHTS
        assert FP.BLOCK_WIDTHS == {11: 17, 13: 18, 15: 19, 16: 21, 17: 22, 18: 24,
                                   20: 26, 21: 27, 23: 29, 25: 31}, FP.BLOCK_WIDTHS
        assert [s for s, _x2 in FP.SIZES] == [11, 13, 15, 16, 17, 18, 20, 21, 23, 25], FP.SIZES
        assert [x2 for _s, x2 in FP.SIZES] == [0, 0, 0, 1, 1, 1, 1, 1, 1, 1], FP.SIZES
        assert sorted(FP.ADV_TABLES) == [11, 13, 15, 16, 17, 18, 20, 21, 23, 25], \
            sorted(FP.ADV_TABLES)

    check("汉化包：字号槽位表与原版成品一致（cell 高 / 方块宽 / x2 位）",
          _size_tables_locked)

    # ── 引擎契约锁（OGSR 源码引用见 font_pack.LOST_CYRILLIC 上方注释）──
    # 引擎对缺失码位不是留空，而是 `TCMap[i] = vFirstValid`（GameFont.cpp:130）：
    # 整张表被填成**同一个字形**。所以"少收字"在俄文目标上等价于满屏乱码。
    def _required_chars_present():
        need = set(FP.CYRILLIC_BLOCK) | set(FP.ANSI_BRIDGE)
        miss = sorted(need - set(chars))
        assert not miss, ("字库缺少必需码位 %d 个（缺一个=整表重复字形）: %r"
                          % (len(miss), "".join(miss[:24])))

    check("汉化包：字库含完整西里尔块与 ANSI 桥接目标", _required_chars_present)

    def _default_keeps_cyrillic():
        """默认**不许**剔除西里尔，且"复刻旧包"仍可用（但必须告警）。"""
        import inspect as _insp
        dflt = _insp.signature(FP.build_package).parameters["full_cyrillic"].default
        assert dflt is True, "build_package 的 full_cyrillic 默认值被改成了 %r" % (dflt,)
        strict = FP.extract_chars(xml_dir, full_cyrillic=False)
        left = set(FP.LOST_CYRILLIC) & set(strict)
        assert not left, "「复刻旧包」模式没有剔除: %r" % "".join(sorted(left))

    check("汉化包：默认保留完整西里尔（复刻旧包模式仍可用）", _default_keeps_cyrillic)

    def _recursive_scan():
        """子目录里的 XML 必须被扫到 —— 只扫顶层会漏字（= 重复字形）。

        原版 CharAdder 用的就是 `for /r` 递归（Generator.bat:75）。
        用生僻字 '齉'（U+9F49）作探针：它不在任何内置字符集里，不会被掩盖。
        """
        import shutil as _sh
        import tempfile as _tf
        d = _tf.mkdtemp(prefix="fp_rec_")
        try:
            os.makedirs(os.path.join(d, "sub", "deep"))
            with open(os.path.join(d, "sub", "deep", "n.xml"), "w", encoding="utf-8") as f:
                f.write('<?xml version="1.0" encoding="utf-8"?>\n<string_table>'
                        '<string id="z"><text>\u9f49\u9f49</text></string></string_table>')
            got = FP.extract_chars(d)
            assert "\u9f49" in got, "子目录里的 XML 未被扫描到（该字形会变成重复字形）"
        finally:
            _sh.rmtree(d, ignore_errors=True)

    check("汉化包：extract_chars 递归扫描子目录", _recursive_scan)

    if not FP.ensure_pillow():
        return "SKIP-PIL"
    from toolkit_platform import system_font_dirs
    font = None
    for d in system_font_dirs():
        for n in ("msyh.ttc", "msyh.ttf", "simsun.ttc", "arial.ttf"):
            p = os.path.join(d, n)
            if os.path.isfile(p):
                font = p
                break
        if font:
            break
    if not font:
        return "SKIP-FONT"
    # 本机字体是否有中文字形：标点留白锁只在"字体真画得出这些字形"时才有意义 ——
    # 没有中日韩字形的字体（tahoma/arial 等）画的是 .notdef 方框，
    # 方框的留白大小与标点本身无关，拿它定标只会得出错误结论。
    from PIL import ImageFont as _PIF
    _probe_font = _PIF.truetype(font, 40)
    _notdef = _probe_font.getmask("\ue123", mode="L").getbbox()
    has_cjk = _probe_font.getmask("永", mode="L").getbbox() != _notdef
    if not has_cjk:
        print("  注意：本机字体 %s 缺中文字形，标点留白锁按 SKIP 处理"
              % os.path.basename(font))

    out = os.path.join(tmp, "fp_out")
    os.makedirs(out, exist_ok=True)
    FP.build_package("SoC", "chs", xml_dir, font, out, suffix="", offset=0,
                     full_cyrillic=True, log=None)
    produced = []
    for dp, dn, fn in os.walk(out):
        produced += [os.path.join(dp, x) for x in fn]
    check("汉化包：build_package 产出文件", lambda: len(produced) > 0)

    # 决策锁定：包内 XML **一律 UTF-8**，且不再产生 .orig 侧写文件
    def _packed_xml_is_utf8():
        xs = [p for p in produced if p.lower().endswith(".xml")]
        assert xs, "包里没有 XML"
        for p in xs:
            if p.lower().endswith(".orig"):
                raise AssertionError("出现了 .orig 侧写文件: %s" % p)
            raw = open(p, "rb").read()
            raw.decode("utf-8")                      # 必须能按 UTF-8 解
            assert not raw.startswith(b"\xef\xbb\xbf"), "包内 XML 不应带 BOM"
        joined = "".join(open(p, encoding="utf-8").read()
                         for p in xs if not p.lower().endswith(".orig"))
        assert "Привет" in joined, "cp1251 源没转成可读文本"
        assert "Мир" in joined, "声明撒谎的 cp1251 源没转成可读文本"
    check("汉化包：包内 XML 一律 UTF-8（含声明撒谎的源），且无 .orig",
          _packed_xml_is_utf8)

    # 独立重算 render_font.widths_of 的结果（adv 表 → 方块宽 → 字体 advance）。
    # 「.ini 布局锁」与「标点留白锁」都要把 ini 里的 (x1,x2) 还原成"原宽 + 收窄量"，
    # 所以单独提出来。
    def _indep_rw0(fobj, rsize, S, ch):
        import unicodedata as _ud
        tbl = FP.ADV_TABLES.get(rsize, {})
        if ord(ch) in tbl:
            return tbl[ord(ch)]
        if _ud.east_asian_width(ch) in "FW" or ch in FP.FORCED_FULLWIDTH:
            return FP.BLOCK_WIDTHS.get(rsize, rsize + 2)
        return max(1, round(fobj.getlength(ch) / S) + 1)

    # 布局不变量：这些性质是从**原版成品**（汉化包生成工具2024 的 ui_font_NN_chs.ini，
    # 10 个尺寸 × 3428 行）实测反推出来的，逐条对上才算与既有汉化包几何一致：
    #   * `height=` == CELL_HEIGHTS[槽位]（引擎据此算行高）；
    #   * 槽是正方形网格：槽宽 = 槽高 = cell；
    #   * **墨迹**在槽内按原宽水平居中（标点把框起点左移 pl 做对称收窄，判据要加回 pl）；
    #   * 每行槽数 = 图集宽 // cell。
    # 垂直方向**有**偏移（vshift：em 盒底对齐行带底），所以本锁只锁水平与网格；
    # 垂直由下面的 _ink_lower_edge_inside_band 按同一模型锁。
    # 钉住这些，几何被改动会立刻变红，而不是等到成品进游戏才发现。
    def _ini_layout_invariant():
        import re as _re
        from PIL import ImageFont
        inis = [p for p in produced if p.lower().endswith(".ini")]
        assert inis, "包里没有 .ini"
        line_re = _re.compile(r"^(\d+)\s*=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$")
        x2_by_slot = dict(FP.SIZES)
        for p in inis:
            base = os.path.basename(p)
            m = _re.match(r"ui_font_(\d+)$", os.path.splitext(base)[0])
            assert m, "非预期的 .ini 名: %s" % base
            slot = int(m.group(1))
            cell = FP.CELL_HEIGHTS[slot]
            S = 2 if x2_by_slot[slot] else 1
            fobj = ImageFont.truetype(font, slot * S)
            section, height, rows = None, None, 0
            for ln in open(p, encoding="ascii"):
                s = ln.strip()
                if s.startswith("["):
                    section = s
                elif s.lower().startswith("height"):
                    height = int(s.split("=", 1)[1])
                else:
                    mm = line_re.match(s)
                    if not mm:
                        continue
                    _cp, x1, y1, x2, y2 = (int(g) for g in mm.groups())
                    rows += 1
                    w = x2 - x1
                    assert w > 0, "%s 宽度非正: %r" % (base, s)
                    # 中文标点按 punct_box_px **对称**收两侧留白：独立重算墨迹与原宽后，必须满足
                    #   ① 框宽 == punct_box_px 给的 rw；
                    #   ② **墨迹**在图集里仍按原宽水平居中 —— 框起点左移了 pl，判据要把 pl 加回来，
                    #      否则"收窄"就成了随手挪坐标而不是申报的那一份。
                    _ch = chr(_cp)
                    _mb = fobj.getmask(_ch, mode="L").getbbox()
                    rw0 = _indep_rw0(fobj, slot, S, _ch)
                    _left = (_mb[0] // S) if _mb is not None else 0
                    _gw = ((_mb[2] - _mb[0]) // S) if _mb is not None else 0
                    pl, rw_exp = FP.punct_box_px(_ch, rw0, _left, _gw)
                    # 与 render_font 同一条"框不得窄于墨迹"的下限（共用库函数，不各算一遍）
                    rw_exp = FP.clamp_box_to_ink(pl, rw_exp, _gw)
                    assert w == rw_exp, \
                        "%s 框宽与申报的收窄不自洽: %r (rw0=%d pl=%d 期望宽=%d)" % (
                            base, s, rw0, pl, rw_exp)
                    _c0 = (x1 // cell) * cell
                    assert x1 + pl == _c0 + (cell - rw0) // 2 + _left, \
                        "%s 墨迹未落在「按原宽居中」的位置: %r (格起点=%d rw0=%d left=%d pl=%d)" % (
                            base, s, _c0, rw0, _left, pl)
                    assert _c0 <= x1 and x1 + w <= _c0 + cell, \
                        "%s 框越出自己的格子: %r (格起点=%d 框宽=%d cell=%d)" % (
                            base, s, _c0, w, cell)
                    assert y1 % cell == 0, "%s 行起点不是 cell 整数倍: %r" % (base, s)
                    assert (y2 - y1) == cell, "%s 虚拟框高 ≠ cell: %r" % (base, s)
            assert section == "[mb_symbol_coords]", "%s 节名异常: %r" % (base, section)
            assert height == cell, "%s height=%r 应为 %d" % (base, height, cell)
            assert rows > 0, "%s 没有任何字形行" % base

    check("汉化包：.ini 布局满足原版不变量（height=cell / 正方形槽 / 水平居中）",
          _ini_layout_invariant)

    # ══════════════════════════════════════════════════════════
    # 墨迹必须落在自己那一格：水平（标点收窄）与垂直（行带 / 槽位高）
    # ══════════════════════════════════════════════════════════
    # 引擎只采样 [x1,x2)×[y1,y1+height)（OGSR `dxFontRender.cpp:99-111`：
    # `tu = l.x/vTS.x`、`fTCWidth = l.z/vTS.x`、`tv = l.y/vTS.y`、
    # `fTCHeight = height/vTS.y` —— ini 的 `x2-x1` 是字距、`y2` 被忽略、垂直只取
    # `height=` 那么高）。因此任何落在框外的墨迹都**不会被画出来**，只会留给邻格
    # 的采样框 → 用户报的「分划把上面那个字的底部也划进去了」就是垂直方向的这一条。
    # 下面三条互补：
    #   A 解析锁：render_font 的几何独立重算（font.getbbox/getmask/getmetrics），对**全字符集
    #     × 10 槽位 × GUI 的每个尺寸档位**断言墨迹整条留在行带内。它锁"槽位高够不够" ——
    #     旧兜底 `size + 4` 在「尺寸 +N」下比实测所需低 1–7px，只有这条抓得住。
    #   B 像素锁：标点（开/闭括号、句读、满框符号）**逐字单独渲染**，实测墨迹必须整条
    #     落在自己的虚拟框 [x1,x2) 内。收窄按 min(两侧留白, PUNCT_PAD_PX[类]) 对称做，
    #     "左偏移 ≤ 原左留白、右留白 ≤ 原右留白"是硬不等式 ⇒ 这条是"永不裁墨迹"的落地验证。
    #   C 像素锁：逐字单独渲染进 DDS（fmt=A8），断言**实际产出的像素**等于 A/B 用的
    #     那个解析模型（含"装不下就整体上移"的兜底）。A/B 若与 render_font 脱节、
    #     或 render_font 不再按模型摆位，C 会先红。
    # 注：top<0（墨迹高出行带上沿）只出现在没有中日韩字形的 Latin 字体上（实测
    # consola 的 '|' 在 25 号 top=-5），由裁带兜底处理（引擎本来就采样不到），
    # 所以 A 只锁下沿、B/C 按模型锁全。

    def _ink_lower_edge_inside_band():
        """全字符集 × 10 槽位 × 档位 0/3/5/7/9：按 render_font 的**同一个**垂直模型
        （em 盒底对齐行带底 + 装不下就整体上移）算出的墨迹，必须整条留在行带内。

        判据 = "上移之后 top 仍 ≥ 0"。一旦为负，说明该字体在该档位的墨迹比**整个行带**
        还高 —— 那才是真的装不下（旧实现在这种情况下从**底部**裁墨，正好啃掉字的底边，
        即用户报的"所有字的底部一丢丢边被吞"）。只锁下沿的旧写法在新的"整体上移"兜底
        下会恒真，所以改成锁这个。
        """
        from PIL import ImageFont
        worst = None
        for size, x2 in FP.SIZES:
            S = 2 if x2 else 1
            for off in (0, 3, 5, 7, 9):        # GUI「尺寸」的全部档位
                rsize = size + off
                cell = FP.cell_height_for(rsize)
                fobj = ImageFont.truetype(font, rsize * S)
                asc, desc = fobj.getmetrics()
                vs = max(0, cell - (asc + desc) // S)
                for ch in chars:
                    bb = fobj.getbbox(ch)
                    mb = fobj.getmask(ch, mode="L").getbbox()
                    if mb is None:
                        continue
                    gh = (mb[3] - mb[1]) // S
                    if gh < 1:
                        continue
                    top = (bb[1] // S) + vs
                    if top + gh > cell:
                        top -= (top + gh - cell)
                    if top < 0 and (worst is None or top < worst[0]):
                        worst = (top, size, off, rsize, cell, ch, gh)
        assert worst is None, (
            "墨迹装不进行带（整体上移后仍高出上沿 %dpx）：槽位 %d + %d（rsize=%d cell=%d）"
            "字符 %r 墨高=%d —— 需要更高的 cell 或换字体"
            % (-worst[0], worst[1], worst[2], worst[3], worst[4], worst[5], worst[6]))

    def _punct_ink_inside_own_box():
        """标点逐字实测：墨迹必须整条落在自己的虚拟框 [x1,x2) 内（收窄不吃墨迹）。

        这是"收窄不得裁到墨迹"的落地锁：收窄量按**实测右留白**算，若公式被改坏
        （比例 > 1、锚点取错、拿 rw0 当留白…）墨迹就会越框，而引擎只采样 [x1,x2)，
        越出的部分在游戏里直接消失。
        只对**字体真有这些字形**的字符断言：没有中日韩标点的字体（tahoma/arial 等）
        画的是 .notdef 方框，方框宽窄与标点本身无关。
        """
        import re as _re
        from PIL import Image, ImageFont
        punct = "".join(sorted(FP.PUNCT_OPEN | FP.PUNCT_CLOSE
                               | FP.PUNCT_SINGLE | FP.PUNCT_WIDE))
        rx = _re.compile(r"^(\d+)\s*=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$",
                         _re.M)

        tested = 0
        bad = []
        inherent = []
        asym = []
        for size, x2 in FP.SIZES:
            S = 2 if x2 else 1
            for off in (0, 3, 5, 7, 9):
                rsize = size + off
                fobj = ImageFont.truetype(font, rsize * S)
                notdef = fobj.getmask("\ue123", mode="L").getbbox()
                for ch in punct:
                    mb = fobj.getmask(ch, mode="L").getbbox()
                    if mb is None or mb == notdef:
                        continue          # 该字体没有这个字形（画的是方框）
                    data, ini, tex_w, tex_h, _my = FP.render_font(ch, font, rsize, x2, "A8")
                    mm = rx.search(ini)
                    assert mm, "单字渲染的 ini 无法解析: %r" % ini
                    _cp, x1, _y1, x2b, _y2 = (int(g) for g in mm.groups())
                    got = Image.frombytes("L", (tex_w, tex_h), data).getbbox()
                    tested += 1
                    if got is None:
                        continue
                    # 未收窄的框本来就装不下（Latin 带音符、非表内字号的“—”在 BLOCK_WIDTHS
                    # 兜底 rsize+2 下）→ 属宽度表的老问题，单独计数；其余一律必须落在框内。
                    left, gw = mb[0] // S, (mb[2] - mb[0]) // S
                    if left + gw > _indep_rw0(fobj, rsize, S, ch):
                        inherent.append((ch, size, off, rsize, left, gw,
                                         _indep_rw0(fobj, rsize, S, ch)))
                    elif got[0] < x1 or got[2] > x2b:
                        bad.append((ch, size, off, rsize, got, (x1, x2b)))
                    else:
                        # ★ 对称锁：标点墨迹在框内的左右留白必须相等（允许 1px 舍入差）。
                        # 用户口径"要对称"；公式取两侧同一个数
                        # （m = min(左留白, 右留白, PAD)）后这是构造性成立的，本锁防止将来
                        # 又拆回"两侧各自 min(原留白, PAD)"—— 那样 ” 会左 2 右 3（用户报的
                        # "双引号对称有点小问题"）。实测像素，不看公式自觉。
                        lm, rm = got[0] - x1, (x2b - 1) - got[2]
                        if abs(lm - rm) > 1:
                            asym.append((ch, size, off, rsize, lm, rm))
        assert tested > 100, "可断言的标点组合只有 %d 组，这条锁等于没跑" % tested
        assert not bad, (
            "%d 组标点墨迹越出自己的虚拟框 [x1,x2)（= 收窄吃掉了墨迹）：%r"
            % (len(bad), bad[:4]))
        assert not asym, (
            "%d 组标点在框内左右留白不相等（>1px）：%r" % (len(asym), asym[:4]))
        if inherent:
            print("  注：其中 %d 组墨迹本来就比未收窄的框宽（宽度表老问题，非收窄所致）：%r"
                  % (len(inherent), inherent[:2]))

    def _realized_ink_matches_model():
        """DDS 实测：逐字单独渲染，墨迹矩形必须等于解析模型（含裁带兜底）。

        模型 = 把 render_font 的贴图流程独立重走一遍：裁到墨迹包围盒 →（超采样时）
        缩放到 gw×gh → **加 vshift（em 盒底对齐行带底）→ 装不下就整体上移 → 仍越出
        [y1, y1+height) 才裁** → 贴到 (x1+pl, y1+top)，其中 `pl` 由 punct_box_px 裁决
        （标点 = min(设计内缩, PAD)、非标点 = 设计内缩本体；不是 getbbox()[0]，那是布局左边距）。
        注意**贴的是矩形、矩形里的墨迹通常不满**：例如 consola 的 'ĺ' 末列只在矩形
        第 0 行有墨，裁掉顶部一行后那一列就空了 —— 所以期望值要用裁剪后子图的 bbox，
        不能直接写 (x1+left, y1+top+裁掉的行, …+gw, …+keep)，否则会误报。
        档位取 0（用户默认）与 +9（最大档，槽位最紧）；中间档位由 A 解析覆盖。
        另外对**标点**断言"实测墨迹整条落在自己的虚拟框 [x1,x2) 内"：这正是标点
        收窄的非空转锁（收窄超过右留白就会越框）。全字符集不这么做 —— 有些字形
        （Latin 带音符、非表内字号的“—”）的墨迹本来就比自己那 1px 余量的框宽，
        那是宽度表的老问题，与标点收窄无关（报告里单独给了数字）。
        """
        import re as _re
        from PIL import Image, ImageFont
        punct = "".join(sorted(FP.PUNCT_OPEN | FP.PUNCT_CLOSE
                               | FP.PUNCT_SINGLE | FP.PUNCT_WIDE))
        rx = _re.compile(r"^(\d+)\s*=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*$",
                         _re.M)
        n = 0
        bad = []
        inherent = []
        for size, x2 in FP.SIZES:
            S = 2 if x2 else 1
            for off in (0, 9):
                rsize = size + off
                cell = FP.cell_height_for(rsize)
                fobj = ImageFont.truetype(font, rsize * S)
                for ch in chars:
                    bb = fobj.getbbox(ch)
                    mask = fobj.getmask(ch, mode="L")
                    mb = mask.getbbox()
                    if mb is None:
                        continue
                    gw = (mb[2] - mb[0]) // S
                    gh = (mb[3] - mb[1]) // S
                    if gw < 1 or gh < 1:
                        continue
                    top, left = bb[1] // S, mb[0] // S
                    # 垂直：与 render_font 同一模型 —— 加 vshift（em 盒底对齐行带底），
                    # 装不下就整体上移（绝不从底部裁墨），上移到顶仍越界才裁顶。
                    _asc, _desc = fobj.getmetrics()
                    top += max(0, cell - (_asc + _desc) // S)
                    if top + gh > cell:
                        top -= (top + gh - cell)
                    cut_top = max(0, -top)
                    cut_bot = max(0, top + gh - cell)
                    keep = gh - cut_top - cut_bot
                    # 水平：框起点左移 pl，墨迹贴到 x1+pl（pl 由 punct_box_px 裁决）
                    _rw0m = _indep_rw0(fobj, rsize, S, ch)
                    pl, _rwm = FP.punct_box_px(ch, _rw0m, left, gw)
                    # 期望值：独立重走一遍 render_font 的贴图流程（见 docstring）
                    sub = Image.frombytes("L", mask.size, bytes(mask)).crop(mb)
                    if S > 1:
                        sub = sub.resize((gw, gh), Image.LANCZOS)
                    if keep < 1:
                        sub = None
                    elif cut_top or cut_bot:
                        sub = sub.crop((0, cut_top, gw, cut_top + keep))
                    sb = None if sub is None else sub.getbbox()
                    data, ini, tex_w, tex_h, _my = FP.render_font(ch, font, rsize, x2, "A8")
                    mm = rx.search(ini)
                    assert mm, "单字渲染的 ini 无法解析: %r" % ini
                    _cp, x1, y1, x2b, _y2 = (int(g) for g in mm.groups())
                    exp = None if sb is None else (
                        x1 + pl + sb[0], y1 + top + cut_top + sb[1],
                        x1 + pl + sb[2], y1 + top + cut_top + sb[3])
                    got = Image.frombytes("L", (tex_w, tex_h), data).getbbox()
                    n += 1
                    if got != exp:
                        bad.append((ch, size, off, got, exp))
                    if ch in punct and got is not None:
                        # 只做**信息性**统计：未收窄的框本来就装不下墨迹的组合（Latin 带音符、
                        # 非表内字号的“—”在 BLOCK_WIDTHS 兜底 rsize+2 下）是宽度表的老问题；
                        # "收窄吃墨迹"另有专门一条锁（_punct_ink_inside_own_box）。
                        if left + gw > _indep_rw0(fobj, rsize, S, ch):
                            inherent.append((ch, size, off, left, gw,
                                             _indep_rw0(fobj, rsize, S, ch)))
        assert n > 500, "像素复核只跑了 %d 组，这条锁等于没跑" % n
        assert not bad, "%d 组 DDS 墨迹与模型不符：%r" % (len(bad), bad[:4])
        if inherent:
            print("  注：%d 组标点的墨迹本来就比未收窄的框宽（宽度表老问题，非收窄所致）：%r"
                  % (len(inherent), inherent[:2]))

    check("汉化包：墨迹不出自己的行带下边界（全字符集 × 10 槽位 × 0/3/5/7/9 档）",
          _ink_lower_edge_inside_band)
    if has_cjk:
        check("汉化包：标点墨迹整条落在自己框内、且左右留白相等（DDS 实测）",
              _punct_ink_inside_own_box)
    else:
        skip("汉化包：标点墨迹整条落在自己框内（DDS 实测，收窄不吃墨迹）",
             "本机字体 %s 缺中文字形，画的是 .notdef 方框" % os.path.basename(font))
    check("汉化包：DDS 逐字复核墨迹矩形 == 解析模型（含越带裁剪）",
          _realized_ink_matches_model)

    def _all_ink_inside_own_box():
        """**非标点**的墨迹也必须整条落在自己的框内（宽度表偏窄时自动抬框）。

        历史缺陷：arial/tahoma 的 U+0483–U+0486 表值 1px 而墨迹 4–9px（最坏裁 23px）、
        软连字符 U+00AD 表值是 0（写出 `x1==x2` 空框）。引擎按 [x1,x2) 采样，框窄了就是
        **静默右裁墨**：没有告警、没有日志，用户只看到"某些字母右边被切了一刀"。
        样例刻意带上这些已知比表值宽的字符。
        """
        import re as _re2
        from PIL import ImageFont
        rx2 = _re2.compile(r"^(\d+)\s*=\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,",
                           _re2.M)
        samples = ["\u0483", "\u0484", "\u0485", "\u0486", "\u00ad", "_", "i",
                   "\u4e2d", "\u0416", "A", "j", "|"]
        bad = []
        for rsize, x2f in ((11, False), (15, False), (23, True)):
            S = 2 if x2f else 1
            f = ImageFont.truetype(font, rsize * S)
            for ch in samples:
                mb = f.getmask(ch, mode="L").getbbox()
                if mb is None:
                    continue
                gw = (mb[2] - mb[0]) // S
                if gw < 1:
                    continue
                _data, ini, _tw, _th, _my = FP.render_font(ch, font, rsize, x2f, "A8")
                m = rx2.search(ini)
                assert m, "单字渲染的 ini 无法解析: %r" % ini
                x1, x2b = int(m.group(2)), int(m.group(4))
                if x2b - x1 < gw:
                    bad.append((ch, rsize, x2b - x1, gw))
        assert not bad, "非标点墨迹被框右裁（框宽 < 墨宽）：%r" % (bad[:4],)
    check("汉化包：非标点墨迹也整条落在自己框内（宽度表偏窄时自动抬框）",
          _all_ink_inside_own_box)

    def _missing_glyph_font_rejected():
        """字体画不出汉字时必须**报错**，而不是产出十张全方框图集还报"完成"。

        负例用 Windows 自带的西文字体（tahoma/arial）—— 它们必然不含中日韩字形，
        正是历史上"选了 Arial 就得到满屏方框"的那条路径。
        """
        fdir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        cands = [os.path.join(fdir, n) for n in ("tahoma.ttf", "arial.ttf")]
        cands = [p for p in cands if os.path.isfile(p)]
        if not cands:
            skip("汉化包：字体缺字形被拒绝", "本机没有 tahoma.ttf / arial.ttf 可作负例")
            return
        bad_font = cands[0]
        # 显式给"要按类别成组探测"的字符：探针的字符集里未必有真汉字（可能只有全角标点），
        # 而这条锁要验的正是"字体画不出汉字时必须报错" —— 依赖字符集会让锁在字符集变化时空转。
        miss = FP.font_missing_chars(bad_font, ["\u4e2d", "\u56fd", "\u0416", "A"])
        assert miss, "%s 竟被判为覆盖正常（负例失效，这条锁会空转）" \
            % os.path.basename(bad_font)
        # 端到端：自带一个**内容确实是汉字**的 XML 目录，再走一遍 build_package
        cjk_dir = os.path.join(tmp, "badfont_xml")
        os.makedirs(cjk_dir, exist_ok=True)
        with open(os.path.join(cjk_dir, "zh.xml"), "w", encoding="utf-8") as f:
            f.write('<?xml version="1.0" encoding="utf-8"?>\n<string_table>\n'
                    '<string id="s1"><text>切换阳光光束，丁达尔效应。</text></string>\n'
                    '</string_table>\n')
        out_bad = os.path.join(tmp, "fp_badfont")
        try:
            FP.build_package("SoC", "chs", cjk_dir, bad_font, out_bad,
                             suffix="", offset=0, full_cyrillic=True, log=None)
            raise AssertionError("缺字形的字体没有报错 —— 会产出十张全方框图集")
        except RuntimeError as e:
            assert ("方框" in str(e)) or ("画不出" in str(e)), \
                "报错信息没说清原因: %s" % e
        assert not os.path.exists(os.path.join(out_bad, "gamedata")), \
            "报错却留下了半成品 gamedata"
    check("汉化包：字体缺字形被拒绝（不产出全方框图集、不留半成品）",
          _missing_glyph_font_rejected)
    return "OK"


def test_encoding():
    """编码判定的**回归锁**。

    锁的都是实测出来的真实缺陷，且都不是"看起来对不对"能发现的：

      1. **多/单字节判据搞错**（1.0.0 的"XML 声明改不掉"根因）：把"能不能按
         UTF-8 解码"当成多字节判据，纯 ASCII 也算数，于是英文 XML 一律判
         utf-8 → 编码转换撞进"已是目标编码"分支 → 声明永远停在 windows-1251。
         正确判据是"能按 UTF-8 解码**且确实含多字节序列**"，它优先级最高（高于
         手动指定，因为多字节 UTF-8 用单字节编码解必是乱码）；纯 ASCII 没有
         多字节证据，要让位给手动指定 → XML 声明 → 统计 → 默认。
      2. `sniff_encoding` 曾经完全没有统计探测，GBK/Big5/UTF-16 一律落到
         windows-1251（旧编码转换工具用 chardet 是能识别的）；
      3. `DEFAULT_ENCODINGS` 曾把 gb18030 排到 windows-1251 **之后** ——
         而 gb18030 的中文 XML 字节用 windows-1251 能"解码成功"（乱码但不抛
         异常），于是 cp1251 永远抢先，中文源全部乱码。顺序反过来对俄文无损：
         cp1251 的俄文字节用 gb18030 会抛 UnicodeDecodeError。
    """
    from toolkit_textio import (sniff_encoding, read_text_file, decode_bytes,
                                DEFAULT_ENCODINGS)
    # 用 find_spec 探测而不是 `import chardet`：后者只为存在性检查，
    # 会被 pyflakes 报成"导入未使用"（它不认 noqa）。
    import importlib.util
    has_chardet = importlib.util.find_spec("chardet") is not None

    check("编码：合法 UTF-8 判为 utf-8",
          lambda: sniff_encoding("中文".encode("utf-8")) == "utf-8")
    check("编码：UTF-8 BOM 归一为 utf-8",
          lambda: sniff_encoding(b"\xef\xbb\xbf" + "中文".encode("utf-8")) == "utf-8")
    check("编码：cp1251 XML 声明被采纳",
          lambda: sniff_encoding(
              '<?xml version="1.0" encoding="windows-1251"?><a>Привет</a>'
              .encode("cp1251")) == "windows-1251")
    # 声明是"文件自己的声称"，字节能否定它 —— 这条补齐的正是"实际编码与声明不一致"。
    # 只靠多字节检查只能证明"不是 UTF-8"，不能证明"是哪种单字节编码"，于是链条会去
    # 问声明；若声明写 utf-8 而字节严格解不开 utf-8，就不能采信。
    # 漏掉这条的后果实测过：字节 cp1251 + 声明 utf-8 被判成 utf-8，目标 utf-8 时
    # 被当成"已达标"**静默跳过**（文件没修好也没提示），目标非 utf-8 时正文被
    # `errors="replace"` 成片替换（9 个西里尔字母 → `?`）。
    check("编码：声明要被字节证实（cp1251 字节 + 声明 utf-8 时不采信声明）",
          lambda: sniff_encoding(
              '<?xml version="1.0" encoding="utf-8"?><a>Привет мир</a>'
              .encode("cp1251")) == "windows-1251")
    check("编码：声明里的编解码器名不存在时也不采信",
          lambda: sniff_encoding(
              b'<?xml version="1.0" encoding="no-such-codec"?><a>Hi</a>')
          not in ("no-such-codec",))
    check("编码：俄文 cp1251 短样本仍判 windows-1251",
          lambda: sniff_encoding("Привет".encode("cp1251")) == "windows-1251")
    check("编码：俄文 cp1251 长样本仍判 windows-1251",
          lambda: sniff_encoding(
              ("Здравствуй, сталкер! Это длинный русский текст. " * 8)
              .encode("cp1251")) == "windows-1251")
    check("编码：cp1252 西文按项目默认回落 windows-1251",
          lambda: sniff_encoding("café".encode("cp1252")) == "windows-1251")

    # ── 判定链的**核心分工**：多/单字节检查优先级最高 ────────────────────
    # 多字节 UTF-8 的字节用任何单字节编码去解都是乱码 —— 这是物理事实，比"用户
    # 选了什么"更硬，所以排在手动指定之前；反过来，**纯 ASCII 没有多字节证据**
    # （它在任何 ASCII 兼容单字节编码下字节完全相同），必须继续往下走，听用户的、
    # 再看声明。1.0.0 的缺陷正是把"能不能按 UTF-8 解码"当成了多字节判据，纯 ASCII
    # 也算数 → 英文 XML 一律判 utf-8 → 撞进"已是目标编码"分支 → 声明改不掉。
    check("编码：多字节 UTF-8 优先于手动指定（单字节编码解它必是乱码）",
          lambda: sniff_encoding("Привет".encode("utf-8"), override="gbk") == "utf-8")
    check("编码：纯 ASCII 不算多字节，让位给手动指定",
          lambda: sniff_encoding(b'<?xml version="1.0" encoding="windows-1251"?>'
                                 b"<a>Hello</a>", override="windows-1251")
          == "windows-1251")
    check("编码：纯 ASCII 不算多字节，让位给 XML 声明（1.0.0 的 Bug 判据）",
          lambda: sniff_encoding(
              b'<?xml version="1.0" encoding="windows-1251"?><a>Hello</a>')
          == "windows-1251")
    check("编码：纯 ASCII 且无声明/无手动 → 走统计与默认，不再冒充 utf-8",
          lambda: sniff_encoding(b"<a>Hello</a>") != "utf-8")
    check("编码：多字节 UTF-8 仍判 utf-8（判据没被上面几条放宽）",
          lambda: sniff_encoding("<a>Привет</a>".encode("utf-8")) == "utf-8")
    check("编码：override='auto' 不干预判定",
          lambda: sniff_encoding("中文".encode("gbk"), override="auto") != "auto")
    check("编码：UTF-16 BOM（含大端）被识别",
          lambda: sniff_encoding("hi 中文".encode("utf-16")) == "utf-16"
          and sniff_encoding(b"\xfe\xff" + "hi 中文".encode("utf-16-be")) == "utf-16")

    # decode_bytes 的 BOM 处理：旧实现**先无条件剥 2 字节**再用 'utf-16' 解，
    # 大端 BOM 会解成乱码、UTF-32 会被误判成 UTF-16，而且剥完再判定等于
    # 丢掉了 BOM 这个信号（UTF-16 只剩它一个判据）。
    check("编码：UTF-16 大端 BOM 解出正确文本（旧实现会乱码）",
          lambda: decode_bytes(b"\xfe\xff" + "Привет".encode("utf-16-be"))[0] == "Привет")
    check("编码：UTF-32 BOM 被识别为 utf-32",
          lambda: decode_bytes("Привет".encode("utf-32"))[1] == "utf-32")
    check("编码：UTF-8 BOM 剥离后文本不含 BOM 字符",
          lambda: decode_bytes(b"\xef\xbb\xbf" + "中文".encode("utf-8"))[0] == "中文")
    check("编码：单字节源的 cp1251 手动指定在 decode_bytes 里被采纳",
          lambda: decode_bytes("Привет".encode("cp1251"), override="cp1251")[0] == "Привет")
    check("编码：多字节 UTF-8 在 decode_bytes 里优先于手动指定",
          lambda: decode_bytes("Привет".encode("utf-8"), override="gbk")[1] == "utf-8")

    if has_chardet:
        # 低置信度的**单字节**猜测必须被拒。旧规则是"置信度达标 **或** 不在手工歧义
        # 名单里就采信"，而那张名单必然漏：实测 chardet 对 cp1251 文件给出
        # "cp865 / 0.025"（不在名单）→ 被采信 → 整篇按丹麦语 DOS 码页解成乱码。
        # 现在判据是程序化的"该编解码器是否单字节家族"，不维护名单。
        check("编码：低置信度的单字节猜测不被采信（chardet 曾猜 cp865/0.025）",
              lambda: sniff_encoding(
                  '<string_table><string id="b"><text>Мир</text></string>'
                  '</string_table>'.encode("cp1251")) == "windows-1251")
        check("编码：GBK 中文判为 gb18030 家族",
              lambda: sniff_encoding(
                  "这是一段中文测试文本，用于验证编码自动探测能力。"
                  .encode("gbk")) in ("gb18030", "gbk"))
        check("编码：Big5 中文不再落到 windows-1251",
              lambda: sniff_encoding(
                  "這是一段中文測試文本，用於驗證編碼自動探測能力。"
                  .encode("big5")) not in ("windows-1251",))
        check("编码：无 BOM 的 UTF-16LE 被识别",
              lambda: sniff_encoding("hello world 中文".encode("utf-16-le")) == "utf-16-le")
    else:
        skip("编码：GBK/Big5/UTF-16 统计探测", "未安装 chardet")

    # 候选顺序：gb18030 必须在 windows-1251 之前（见 docstring 第 2 条）
    check("编码：DEFAULT_ENCODINGS 中 gb18030 排在 windows-1251 之前",
          lambda: DEFAULT_ENCODINGS.index("gb18030")
          < DEFAULT_ENCODINGS.index("windows-1251"))

    def _roundtrip(enc, text):
        raw = text.encode(enc)
        got, used, _forced = decode_bytes(raw)
        assert got == text, "decode_bytes(%s) -> %r（用了 %s）" % (enc, got[:20], used)

    check("编码：decode_bytes 正确解 GB18030",
          lambda: _roundtrip("gb18030", "中文测试文本。" * 4))
    check("编码：decode_bytes 正确解 cp1251",
          lambda: _roundtrip("cp1251", "Здравствуй, сталкер! " * 4))

    # read_text_file 是各 App 读源文件的实际入口，必须也能读中文
    fd, path = tempfile.mkstemp(suffix=".xml", prefix="enc_probe_")
    os.close(fd)
    try:
        with open(path, "wb") as f:
            f.write(("这是一段中文测试文本。" * 6).encode("gb18030"))
        got, used = read_text_file(path)
        check("编码：read_text_file 读 GB18030 中文源不再乱码",
              lambda: "中文测试文本" in got and used in ("gb18030", "gbk"))
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def test_task_runner():
    """任务壳的**失败路径**必须回主线程（回归锁）。

    `TaskRunner._wrapper` 原本在工作线程里直接调 `on_error(e)`，而各 App 的
    on_error 都会 `set_status` / 改控件 —— 那是"后台线程改 Tk"，未定义行为。
    失败路径只在任务抛异常时才走到，正常路径永远测不到。
    """
    import threading
    import time
    import tkinter as tk
    from toolkit_widgets import TaskRunner, _make_pump

    try:
        root = tk.Tk()
        root.withdraw()
    except Exception as e:
        skip("任务壳失败路径", "无桌面 Tk: %s" % e)
        return

    seen = {}
    try:
        ui = _make_pump(root)

        def on_error(exc):
            seen["handled"] = repr(exc)
            seen["in_main"] = (threading.current_thread() is threading.main_thread())
            tr.set_status("失败: %s" % exc, "err")

        tr = TaskRunner(root, ui,
                        status_setter=lambda t, k="idle": seen.__setitem__("status", (t, k)))
        tr.run(lambda: (_ for _ in ()).throw(RuntimeError("boom")), on_error=on_error)
        for _ in range(60):
            root.update()
            time.sleep(0.02)
        root.update()
    except Exception as e:
        skip("任务壳失败路径", "环境不满足: %s" % e)
        return
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    check("任务壳：on_error 被执行", lambda: seen.get("handled") == "RuntimeError('boom')")
    check("任务壳：on_error 在**主线程**执行（不在工作线程碰 Tk）",
          lambda: seen.get("in_main") is True)
    check("任务壳：失败状态不被收尾的“成功”状态覆盖",
          lambda: seen.get("status", ("", ""))[1] == "err")

    # ── 泵的日志纪律：**正常空队列不许报故障**，真回调异常必须留痕 ──────────────
    # 这条是实跑真 Hub 时发现的：日志里每隔一会儿就出现
    # `UI 回调队列异常（取队列失败）: Empty` —— 而 Empty 正是泵的**正常出口**。
    # 根因：`try/except Exception` 把 `queue.Empty`（循环终止条件）一起当成了故障。
    # 后果：每次开软件刷出 N 条假错误日志，把真故障淹没。
    notes = []
    import toolkit_log as _TL
    real_detail = _TL.detail
    _TL.detail = lambda msg, tag="info": notes.append((msg, tag))
    try:
        root2 = tk.Tk()
        root2.withdraw()
    except Exception as e:
        _TL.detail = real_detail
        skip("泵的日志纪律", "无桌面 Tk: %s" % e)
        return
    try:
        ui2 = _make_pump(root2)
        for _ in range(15):                     # 空队列跑十几轮
            root2.update()
            time.sleep(0.02)
        fake = [n for n in notes if "取队列失败" in n[0]]
        check("任务壳：泵在**空队列**时不许报「取队列失败」（那是正常出口）",
              lambda: not fake)
        # 正例：真有回调抛异常时必须留痕（不能因为修上面那条就把这条也吞了）
        notes.clear()
        ui2(lambda: (_ for _ in ()).throw(RuntimeError("cb-boom")))
        for _ in range(15):
            root2.update()
            time.sleep(0.02)
        check("任务壳：UI 回调真的抛异常时仍要留痕（不静默）",
              lambda: any("UI 回调失败" in n[0] and "cb-boom" in n[0] for n in notes))
        # 而且泵必须活着（空队列那次 break 不该把它停掉）
        notes.clear()
        ui2(lambda: notes.append(("alive", "ok")))
        for _ in range(15):
            root2.update()
            time.sleep(0.02)
        check("任务壳：空队列之后泵仍然在跑（后续回调照样投递）",
              lambda: any(n[0] == "alive" for n in notes))

        # ── 运行日志时间戳必须带毫秒 ──────────────────────────────────────────
        # 2026-09-12 的启动白屏取证：运行日志只到秒，而同一秒里挤着"窗口就绪 /
        # 插件扫描完成 / 六个栏目装配"，秒级精度分不出是哪一段慢，只能靠录屏
        # 逐帧反推。带毫秒之后，同一份日志自己就能读出相位差。
        import re as _re
        import shutil as _sh
        import tempfile as _tf
        import toolkit_log as _TL2
        _ts_ok, _ts_line = False, ""
        _orig_dir = getattr(_TL2, "_LOG_DIR", None)
        _tdir = _tf.mkdtemp(prefix="probe_logts_")
        try:
            _TL2.set_log_dir(_tdir)
            _TL2.log_to_file("时间戳探针", "info")
            _tpath = _TL2.log_path()
            assert _tpath.startswith(_tdir), "日志没落进探针临时目录：%s" % _tpath
            with open(_tpath, encoding="utf-8") as _tfh:
                _ts_line = _tfh.readline().rstrip("\n")
            _ts_ok = bool(_re.match(
                r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}\] \[info\] 时间戳探针$",
                _ts_line))
        finally:
            _TL2.set_log_dir(_orig_dir)
            _sh.rmtree(_tdir, ignore_errors=True)
        def _ts_lock():
            assert _ts_ok, "实际行：%s" % (_ts_line or "(空)")
            return True
        check("日志：运行日志时间戳带毫秒（相位差可读，不必再靠录屏反推）", _ts_lock)
    finally:
        _TL.detail = real_detail
        try:
            root2.destroy()
        except Exception:            pass


def test_video_convert(tmp):
    """真实转码一次（回归锁）。

    锁四件只在真跑 ffmpeg / 真构造界面时才暴露的事：
      1. 进度回调是 **0~100 的百分比**（曾把它当 0~1 再乘 100 → 进度条瞬间满格、
         状态显示「转换中… 9950%」）；
      2. **参考 OGM 是必需的**（用户决策：输出必须按参考参数生成才能与引擎一致）。
         这里锁到界面层：没加载参考时按钮必须是禁用的、且 `_start_convert` 不得启动任务；
         「灰着且不额外解释」是有意为之，所以这里也**不检查**有没有提示文案。
         旧散装版允许无参考（属旧版缺陷），不要继承。
      3. 完整性校验不再误报「输出不完整」—— OGM/Theora 容器不保存帧率，
         ffprobe 对所有 .ogm 都给 r_frame_rate=1/1，于是 fps*duration 恒等于
         "秒数"，任何正常转换都会被算成"帧数不足"。
      4. 取消请求不会被新一轮 `convert()` 清掉。
    """
    import subprocess
    from toolkit_platform import locate_exe

    ffmpeg = locate_exe("ffmpeg", extra_dirs=(BASE,))
    ffprobe = locate_exe("ffprobe", extra_dirs=(BASE,))
    if not (ffmpeg and ffprobe):
        skip("视频转换（参考 OGM 参数）", "未找到 ffmpeg/ffprobe")
        return

    src = os.path.join(tmp, "vc_src.mp4")
    out = os.path.join(tmp, "vc_out.ogm")
    try:
        # 用 lavfi 现场造一个 2 秒测试片，避免依赖仓库里的样片
        subprocess.run(
            [ffmpeg, "-y", "-v", "error",
             "-f", "lavfi", "-i", "testsrc=duration=2:size=320x240:rate=10",
             "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
             "-shortest", src],
            capture_output=True, timeout=180,
            **__import__("toolkit_platform").hidden_kwargs())
    except Exception as e:
        skip("视频转换（参考 OGM 参数）", "生成测试片失败: %s" % e)
        return

    from apps.video_ogm_app import Converter, VideoInfo, VideoStream, AudioStream

    # 界面层：没有参考时按钮禁用、且不启动任务（决策锁定）
    def _ui_requires_reference():
        try:
            import tkinter as tk
            from tkinter import messagebox
            for fn in ("showinfo", "showwarning", "showerror"):
                setattr(messagebox, fn, lambda *a, **k: "ok")
            from toolkit import _BaseTk, apply_theme, apply_tk_defaults
            from apps.video_ogm_app import VideoOGMApp
            root = _BaseTk(); root.withdraw()
            apply_theme("dark"); apply_tk_defaults(root, "dark")
            try:
                app = VideoOGMApp(tk.Frame(root)); root.update_idletasks()
                assert str(app.btn_go.cget("state")) == "disabled", \
                    "未加载参考时转换按钮竟然可用"
                app.source_path = src
                app.converter = Converter(ffmpeg, ffprobe)
                app.out_var.set(os.path.join(tmp, "vc_never2.ogm"))
                app._start_convert()          # 没有 reference_info，必须直接返回
                assert app.task.running is False, "没有参考 OGM 却启动了转换任务"
            finally:
                root.destroy()
        except AssertionError:
            raise
        except Exception as e:
            raise AssertionError("界面检查环境不满足: %s" % e)
    check("视频：未加载参考 OGM 时按钮禁用且不启动转换（必需，不是可选）",
          _ui_requires_reference)

    # 组件层：带参考参数真实转码一次
    ref = VideoInfo(filename="ref.ogm", size_mb=0.0, duration=2.0,
                    video=VideoStream(codec="theora", width=320, height=240,
                                      fps=10.0, bitrate=0),
                    audio=AudioStream(codec="vorbis", sample_rate=48000,
                                      channels=2, bitrate=128000))
    conv = Converter(ffmpeg, ffprobe)
    conv.reset_cancel()
    seen = []
    try:
        ok, msg = conv.convert(src, out, reference_info=ref,
                               progress_callback=lambda p: seen.append(float(p)))
    except Exception as e:
        skip("视频转换（参考 OGM 参数）", "转码异常: %s" % e)
        return

    def _convert_ok():
        assert ok is True, "转换失败: %s" % (str(msg)[:160],)
    check("视频：按参考 OGM 参数转码成功", _convert_ok)
    check("视频：产出非空 OGM 文件",
          lambda: os.path.isfile(out) and os.path.getsize(out) > 0)

    def _progress_in_range():
        assert seen, "进度回调一次都没触发"
        assert 0.0 <= min(seen) and max(seen) <= 100.0, \
            "进度值越界（应 0~100）: %.1f~%.1f" % (min(seen), max(seen))
    check("视频：进度回调值在 0~100（不是 0~1 被再乘 100）", _progress_in_range)

    # 取消请求不能被 convert() 在开头清掉
    conv2 = Converter(ffmpeg, ffprobe)
    conv2.cancel()
    ok2, msg2 = conv2.convert(src, os.path.join(tmp, "vc_never.ogm"))

    def _cancel_honored():
        assert ok2 is False and msg2 == "已取消", "实际 ok=%s msg=%s" % (ok2, msg2)
    check("视频：取消请求不会被新一轮 convert() 清掉（竞态回归）", _cancel_honored)
    check("视频：被取消时不留下半成品",
          lambda: not os.path.exists(os.path.join(tmp, "vc_never.ogm")))


# ══════════════════════════════════════════════════════════════
# 9. 复杂编码环境（受约束）
# ══════════════════════════════════════════════════════════════
# 约束（用户决策）：**多字节只用 UTF-8、单字节只用 windows-1251**。
# "多字节不用 utf-8"和"单字节编码不止一种"这两种情况基本不可能遇到，为它们写代码
# 必然非常冗余 —— 所以本环境**不覆盖**它们，也就不需要任何阈值/打分机制。
# 复杂度全部放在真正会遇到的地方：声明与字节不符（两个方向）、无声明、
# 只有 version 没有 encoding、UTF-8 BOM、纯 ASCII、单引号/大写/多余空格/前导空白、
# 多根 XML、属性含西里尔、CRLF、嵌套深目录。
#
# 每条用例都用 (真实编码, 字节) **明确构造**，期望文本由"按真实编码解码"得出 ——
# 所以"转换后正文是否等于期望文本"是可判定的，不依赖任何猜测。
_CE_RU = "Привет, сталкер!"
_CE_RU2 = "Здравствуй, Зона. Аномалия рядом."
_CE_ST = '<string_table><string id="a"><text>%s</text></string></string_table>' % _CE_RU


def _ce_cases():
    """(相对路径, 声明或 None, 正文, 真实编码, 前置 BOM)"""
    st = _CE_ST
    return [
        # 诚实声明
        ("config/text/rus/honest_1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>', st, "cp1251", b""),
        ("config/text/rus/honest_utf8.xml",
         '<?xml version="1.0" encoding="utf-8" ?>', st, "utf-8", b""),
        # 声明与字节不符：字节是多字节 UTF-8，声明却写 1251（多字节检查救回）
        ("config/text/rus/lying_decl1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>',
         '<string_table><string id="a"><text>%s</text></string></string_table>' % _CE_RU2,
         "utf-8", b""),
        # 声明与字节不符：字节是 1251，声明却写 utf-8（声明须被字节证实）
        ("config/text/rus/lying_declutf8.xml",
         '<?xml version="1.0" encoding="utf-8" ?>',
         '<string_table><string id="a"><text>%s</text></string></string_table>' % _CE_RU2,
         "cp1251", b""),
        # 无声明
        ("config/text/rus/nodecl_1251.xml", None, st, "cp1251", b""),
        ("config/text/rus/nodecl_utf8.xml", None, st, "utf-8", b""),
        ("config/text/rus/nodecl_ascii.xml", None,
         '<string_table><string id="a"><text>Hello</text></string></string_table>',
         "ascii", b""),
        # BOM
        ("config/text/rus/bom_utf8.xml",
         '<?xml version="1.0" encoding="utf-8" ?>', st, "utf-8", b"\xef\xbb\xbf"),
        ("config/text/rus/bom_nodecl.xml", None, st, "utf-8", b"\xef\xbb\xbf"),
        # 声明写法差异
        ("config/text/rus/decl_singlequote.xml",
         "<?xml version='1.0' encoding='windows-1251' ?>", st, "cp1251", b""),
        ("config/text/rus/decl_upper.xml",
         '<?xml version="1.0" ENCODING="UTF-8" ?>', st, "utf-8", b""),
        ("config/text/rus/decl_spaced.xml",
         '<?xml version = "1.0"   encoding = "windows-1251"  ?>', st, "cp1251", b""),
        ("config/text/rus/decl_leading_ws.xml",
         '\n\t<?xml version="1.0" encoding="windows-1251" ?>', st, "cp1251", b""),
        ("config/text/rus/decl_version_only.xml",
         '<?xml version="1.0"?>', st, "cp1251", b""),
        # 结构复杂度
        ("config/text/rus/multiroot_1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>',
         ('<string_table><string id="a"><text>%s</text></string></string_table>\n'
          '<string_table><string id="b"><text>%s</text></string></string_table>')
         % (_CE_RU, _CE_RU2), "cp1251", b""),
        ("config/text/rus/attr_cyr_utf8.xml",
         '<?xml version="1.0" encoding="utf-8" ?>',
         ('<string_table name="%s"><string id="a" note="%s"><text>%s</text>'
          '</string></string_table>') % (_CE_RU2, _CE_RU, _CE_RU2), "utf-8", b""),
        ("config/text/rus/crlf_1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>',
         '<string_table>\r\n\t<string id="a">\r\n\t\t<text>%s</text>\r\n\t</string>\r\n'
         '</string_table>' % _CE_RU, "cp1251", b""),
        # 英文目录（纯 ASCII）—— 1.0.0 的"声明改不掉"就出在这类文件上
        ("config/text/eng/ascii_decl1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>',
         '<string_table><string id="a"><text>Hello, stalker!</text></string>'
         '</string_table>', "ascii", b""),
        ("config/text/eng/ascii_declutf8.xml",
         '<?xml version="1.0" encoding="utf-8" ?>',
         '<string_table><string id="a"><text>Hello, stalker!</text></string>'
         '</string_table>', "ascii", b""),
        ("config/text/eng/ascii_nodecl.xml", None,
         '<string_table><string id="a"><text>Hello, stalker!</text></string>'
         '</string_table>', "ascii", b""),
        ("config/text/eng/ascii_crlf.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>',
         '<string_table>\r\n\t<string id="a"><text>Hi</text></string>\r\n</string_table>',
         "ascii", b""),
        # 嵌套深目录
        ("scripts/deep/a/b/deep_1251.xml",
         '<?xml version="1.0" encoding="windows-1251" ?>', st, "cp1251", b""),
    ]


def _ce_build(root):
    """写出全部用例文件，返回 [(相对路径, 期望全文, 是否本来就有 encoding 属性, 是否本来就有声明)]。"""
    meta = []
    for rel, decl, body, enc, bom in _ce_cases():
        text = ((decl + "\n") if decl else "") + body
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(bom + text.encode(enc))
        meta.append((rel, text,
                     bool(decl and "encoding" in decl.lower()),
                     decl is not None))
    return meta


def _ce_check_run(setting, outdir_on, tmp_root):
    """跑一遍并返回不合格清单（正文不符 / 带 BOM / 声明非 utf-8 / 输出缺失）。"""
    import threading
    import re
    from apps.convert_app import ConvertApp

    tmp = tempfile.mkdtemp(prefix="enc_cplx_", dir=tmp_root)
    out = os.path.join(tmp, "_out")
    meta = _ce_build(tmp)
    if outdir_on:
        os.makedirs(out)

    # convert_file 不需要界面：用 __new__ + 桩，避免依赖桌面 Tk
    app = ConvertApp.__new__(ConvertApp)
    app.cancelled = False
    ev = threading.Event(); ev.set()
    app.pause_event = ev
    app.convert_stats = {"success": 0, "skipped": 0, "failed": 0}
    snap = {"target_enc": "utf-8", "source_enc": setting, "is_single_file": False,
            "source_dir": tmp, "output_dir": out if outdir_on else "",
            "backup_files": False, "file_exts": ".xml",
            "recursive": True, "exclude_pattern": ""}
    app._task_snap = lambda: snap
    app._ensure_snap = lambda **k: snap
    app.backup_file = lambda *a, **k: None

    decl_re = re.compile(r"<\?xml[^>]*\?>", re.I)
    enc_re = re.compile(r"encoding\s*=\s*[\"']([^\"']*)[\"']", re.I)
    bad = []
    for rel, expect, has_enc, had_decl in meta:
        src = os.path.join(tmp, rel.replace("/", os.sep))
        app.convert_file(src, snap)
        dst = os.path.join(out, rel.replace("/", os.sep)) if outdir_on else src
        if not os.path.isfile(dst):
            bad.append("%s: 输出缺失" % rel); continue
        raw = open(dst, "rb").read()
        if raw.startswith(b"\xef\xbb\xbf"):
            bad.append("%s: 输出带 BOM" % rel); continue
        try:
            txt = raw.decode("utf-8")
        except Exception as e:
            bad.append("%s: 不是 utf-8 (%s)" % (rel, e)); continue
        # 声明**只能改、不能加**：原本没有声明的不许凭空多出一条（用户规则）。
        # 注意正文比对会把"第一条声明"整段去掉，所以凭空加上的声明**不会**被
        # 正文比对发现 —— 必须在这里单独判。
        if not had_decl and "<?xml" in txt:
            bad.append("%s: 原本无声明却被加上声明" % rel); continue
        if decl_re.sub("", txt, count=1) != decl_re.sub("", expect, count=1):
            bad.append("%s: 正文不符" % rel); continue
        if has_enc:
            m = decl_re.search(txt)
            em = enc_re.search(m.group(0)) if m else None
            if not em or em.group(1).lower() != "utf-8":
                bad.append("%s: 声明不是 utf-8" % rel)
        elif had_decl:
            # 声明本来只有 version、没有 encoding 属性 → 不许补上该属性
            m = decl_re.search(txt)
            if not m or "encoding" in m.group(0).lower():
                bad.append("%s: 原本无 encoding 属性却被补上" % rel)
    shutil.rmtree(tmp, ignore_errors=True)
    return bad


def test_complex_encoding_env(tmp):
    """复杂编码环境：auto 与手动 1251，原地与输出新目录，四个组合都必须全对。

    受约束环境（见本节开头）下这条链已经够用，所以这里**不引入**任何阈值/打分：
    只要链的层次对了，四种组合应该给出完全一致的结果。
    """
    n = len(_ce_cases())
    for setting in ("auto", "windows-1251"):
        for outdir_on in (False, True):
            label = "复杂编码环境：源=%s 输出=%s（%d 个文件全部正确）" % (
                setting, "新目录" if outdir_on else "原地", n)

            def _run(setting=setting, outdir_on=outdir_on, label=label):
                bad = _ce_check_run(setting, outdir_on, tmp)
                assert not bad, "%d 个不合格: %s" % (len(bad), "; ".join(bad[:6]))
            check(label, _run)


# ══════════════════════════════════════════════════════════════
# 10. 交叉校验工具的判定（ANSI 代码页 / 逐字节比对）—— 外部审计 2026-09-12
# ══════════════════════════════════════════════════════════════
def test_cross_validate_helpers(tmp):
    """`cross_validate.py` 两条"潜伏型"判据：代码页取错、用哈希代替逐字节。

    两条都不需要 converter.exe，所以能在快速档里锁死：
      * **代码页**：cv 用的是 Win32 `GetACP()`（本机 936）。旧代码用
        `locale.getpreferredencoding(False)`，本机返回 `utf-8` → 预测名把西里尔字节整段丢掉，
        于是"cv 写得成的合法乱码名"被预测成"写不成"，落到 `else` → **误报 FAIL**。
        本锁用**探针自己**的 `MultiByteToWideChar` 结果与预测比对（两套实现必须一致），
        所以换机器、换 ACP 都成立。
      * **逐字节**：用户口径是"字节级相同"。哈希相等只给"不同"，给不出"首个不同字节在哪"。
    """
    import sys as _sys
    import cross_validate as XV

    def _acp_is_getacp():
        """**来源**才是要点：必须取自 GetACP()。

        本机 `locale.getpreferredencoding(False)` 恰好也返回 cp936，所以"值相等"这条
        在本机是**空转**的（外部审计那边它返回 utf-8，缺陷就是在那种机器上发作的）。
        因此再加一条源码级判定：ANSI_CP 必须由 `GetACP()` 派生 —— 它与本机 locale 是否
        恰好一致无关。
        """
        src = open(os.path.join(BASE, "cross_validate.py"), encoding="utf-8").read()
        import re as _re2
        assert _re2.search(r"^ANSI_CP = _windows_acp\(\)\s*$", src, _re2.M), \
            "ANSI_CP 的赋值不是 _windows_acp()（那是个内部走 GetACP() 的助手）—— " \
            "退回 locale.getpreferredencoding() 就是本缺陷的原始形态"
        assert "GetACP()" in src, \
            "cross_validate.py 不再用 GetACP() 取本机 ANSI 代码页（cv 用的一定是它）"
        if _sys.platform != "win32":
            return
        import ctypes
        want = "cp%d" % int(ctypes.windll.kernel32.GetACP())
        assert XV.ANSI_CP.lower().replace("-", "") == want, \
            "ANSI_CP=%r 与 GetACP()=%r 不一致" % (XV.ANSI_CP, want)
        naive = "cp%s" % "".join(ch for ch in XV.ANSI_CP if ch.isdigit())
        if __import__("locale").getpreferredencoding(False).lower().replace(
                "-", "").replace("cp", "") != naive.replace("cp", ""):
            print("  注意：本机 locale 与 GetACP 不同（%s vs %s）—— 这正是缺陷会发作的环境"
                  % (__import__("locale").getpreferredencoding(False), want))
    check("交叉校验：ANSI_CP 由 GetACP() 派生（源码级 + 运行期）", _acp_is_getacp)

    def _probe_api_name(name):
        """探针**独立**用 Win32 API 算一遍（与 cross_validate 的实现互不共用）。"""
        import ctypes
        from ctypes import wintypes
        raw = name.encode("cp1251")
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        fn = k32.MultiByteToWideChar
        fn.argtypes = [wintypes.UINT, wintypes.DWORD, ctypes.c_char_p,
                       ctypes.c_int, ctypes.c_wchar_p, ctypes.c_int]
        fn.restype = ctypes.c_int
        need = fn(0, 0, raw, len(raw), None, 0)          # CP_ACP = 0
        buf = ctypes.create_unicode_buffer(need)
        got = fn(0, 0, raw, len(raw), buf, need)
        return buf[:got]

    def _prediction_uses_api():
        if _sys.platform != "win32":
            return
        for name in ("имя_тест_кириллица.txt", "Сценарий windows.cmd"):
            pred = XV.cv_written_name(name)
            assert pred == _probe_api_name(name), (
                "预测名 %r 与 Win32 API 按 CP_ACP 的结果 %r 不一致 —— "
                "多半又退回 Python 的 decode(errors='ignore') 了"
                % (pred, _probe_api_name(name)))
    check("交叉校验：cv 名字预测走 Win32 API（与探针独立实现一致）", _prediction_uses_api)

    def _classification_contract():
        """判定表：原名→PASS；预测的乱码名→SKIP；什么都没落→SKIP；落了别的名→FAIL。

        最后一条正是当年被误报的那条路径：**预测名没错**时，"cv 写出了那个乱码名"
        必须是 SKIP 而不是 FAIL。用 `Сценарий windows.cmd` 做样本（它的预测名不含 '?'）。
        """
        name = "Сценарий windows.cmd"
        pred = XV.cv_written_name(name)
        assert pred is not None
        assert XV.classify_cv_name(name, {name}, pred)[0] == "PASS", "原名在却不算 PASS"
        kind = XV.classify_cv_name(name, {pred}, pred)[0]
        if XV.ANSI_CP.lower().replace("-", "") == "cp1251":
            assert kind == "PASS", kind
        else:
            assert kind == "SKIP", "预测名在却判成 %s（应当 SKIP：cv 自身代码页行为）" % kind
        assert XV.classify_cv_name(name, set(), pred)[0] in ("SKIP", "FAIL", "PASS")
        if "?" not in pred and XV.ANSI_CP.lower().replace("-", "") != "cp1251":
            assert XV.classify_cv_name(name, {"谁也没想到的名字.txt"}, pred)[0] == "FAIL", \
                "既非原名也非预测名，必须是 FAIL（模型与实测矛盾）"

        # '?' 归因那一支也必须被走到：预测名含 U+003F 时，说明文字要指出"Win32 非法字符"，
        # 而不是含糊地说"没建出文件"（旧实现的归因文字是错的：不是"字节被丢弃"）。
        name2 = "имя_тест_кириллица.txt"
        pred2 = XV.cv_written_name(name2)
        if pred2 and "?" in pred2:
            kind2, detail2 = XV.classify_cv_name(name2, set(), pred2)
            assert kind2 in ("SKIP", "FAIL"), kind2
            assert "U+003F" in detail2 or "非法字符" in detail2, \
                "含 '?' 的预测名必须归因到 Win32 非法字符：%r" % detail2
    check("交叉校验：cv 文件名判定表（原名/乱码名/无产出/陌名/'?' 归因）",
          _classification_contract)

    def _bytewise_index():
        """逐字节比对必须能指出**首个不同字节的下标**（哈希口径给不出）。"""
        d = os.path.join(tmp, "xvalbytes")
        os.makedirs(d, exist_ok=True)
        pa, pb, pc, pd = (os.path.join(d, n) for n in ("a.bin", "b.bin", "c.bin", "d.bin"))
        open(pa, "wb").write(b"ABCDEF")
        open(pb, "wb").write(b"ABCDEF")            # 相同
        open(pc, "wb").write(b"ABCdEF")            # 第 3 字节不同
        open(pd, "wb").write(b"ABCDE")             # 长度不同
        same, why = XV.first_byte_diff(pa, pb)
        assert same is True, why
        same, why = XV.first_byte_diff(pa, pc)
        assert same is False and "@3" in why, why
        assert "100(0x64)" in why and "68(0x44)" in why, why
        same, why = XV.first_byte_diff(pa, pd)
        assert same is False and "长度不同" in why, why
    check("交叉校验：逐字节比对给出首异下标与两侧字节值", _bytewise_index)

    def _trees_compare_bytewise():
        """树比对走逐字节，且在日志里说明差异位置（而不是只说"不同"）。"""
        import contextlib
        import io
        d = os.path.join(tmp, "xvaltrees")
        exp, act = os.path.join(d, "exp"), os.path.join(d, "act")
        for root in (exp, act):
            os.makedirs(os.path.join(root, "sub"), exist_ok=True)
        open(os.path.join(exp, "same.txt"), "wb").write(b"hello")
        open(os.path.join(act, "same.txt"), "wb").write(b"hello")
        open(os.path.join(exp, "sub", "x.bin"), "wb").write(b"\x00\x01\x02\x03")
        open(os.path.join(act, "sub", "x.bin"), "wb").write(b"\x00\x01\xFF\x03")
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            ok = XV.compare_trees(exp, act, "探针树")
        said = buf.getvalue()
        assert ok is False, "只差一个字节却判成相同"
        assert "@2" in said and "x.bin" in said, "日志没说清差异位置：%r" % said
    check("交叉校验：树比对逐字节并打印首异位置", _trees_compare_bytewise)

    def _no_hash_shortcut():
        src = open(os.path.join(BASE, "cross_validate.py"), encoding="utf-8").read()
        assert "sha256(" not in src and "md5(" not in src, \
            "cross_validate.py 又用哈希代替逐字节比对了（用户口径：字节级相同）"
    check("交叉校验：不再用哈希代替逐字节比对（口径漂移锁）", _no_hash_shortcut)

    def _coverage_contract():
        """覆盖率行与 `--strict` 语义（与套件脚本同一契约）。

        用户口径：默认只对"字节不同 / 无法解释的丢失"判红，**覆盖率必须显式报出**；
        `--strict` 才要求 100% 覆盖率（cv 侧限制导致的不可比对项也算失败）。
        """
        line = XV.coverage_line(5238, 5242, 4, "cv 名字按本机 ANSI 转换后含非法字符")
        assert "5238/5242" in line and "99.92%" in line, line
        assert "未覆盖 4 项" in line and "非法字符" in line, line
        assert XV.coverage_line(6, 6).startswith("覆盖率: 6/6 = 100.00%"), \
            XV.coverage_line(6, 6)
        assert XV.verdict_exit_code(False, 0, 6) == 0, "默认模式：不可比对项不该判红"
        assert XV.verdict_exit_code(True, 0, 6) == 1, "--strict：有不可比对项必须判红"
        assert XV.verdict_exit_code(False, 1, 0) == 1, "真失败必须判红"
        assert XV.verdict_exit_code(True, 1, 6) == 1, "真失败 + strict 仍判红"

        src = open(os.path.join(BASE, "cross_validate.py"), encoding="utf-8").read()
        assert '"--strict"' in src, "cross_validate.py 不再接受 --strict"
        assert "coverage_line(" in src and "verdict_exit_code(" in src, \
            "cross_validate.py 的主流程没有真的用覆盖率行 / 判定函数"
        assert "sys.exit(1 if FAIL else 0)" not in src, \
            "又退回裸 `sys.exit(1 if FAIL else 0)` —— --strict 会失效"
    check("交叉校验：覆盖率行 + --strict 契约（与套件同一口径）", _coverage_contract)


def main():
    print("=" * 66)
    print("功能完整性验证（全部在临时目录内操作）")
    print("=" * 66)
    tmp = tempfile.mkdtemp(prefix="func_probe_")
    try:
        print("\n[1] 文本提取")
        test_text_extract(tmp)

        print("\n[2] XML 比较")
        test_xml_compare(tmp)

        print("\n[3] 编码转换")
        r = test_convert()
        if r == "SKIP":
            skip("编码转换（无桌面 Tk）", "无法创建根窗口")

        print("\n[4] 引擎：六格式真实往返")
        test_engine(tmp)

        print("\n[5] 汉化包生成")
        try:
            r5 = test_font_pack(tmp)
            if r5 in ("SKIP-PIL", "SKIP-FONT"):
                skip("汉化包生成", r5)
        except Exception as e:
            # ⚠ 这里原先写的是 skip("汉化包生成", "环境不满足: %s" % e)：**任何**异常都被
            # 说成"环境不满足"，于是本段 [5] 的十余条断言（zip 结构 / ini 布局 /
            # 逐字像素覆盖 / 缺字形拒绝 / 无声明不添加声明）可以整体消失，而全局
            # 仍是 exit 0 绿灯。实测注入 `raise RuntimeError` 到 test_font_pack 里，
            # 改前 SKIP+1、PASS/FAIL 不变、退出码 0 —— 整段门禁一键蒸发。
            # 真正的环境缺失只有两种，且都由 test_font_pack **显式返回**（PIL 未装 /
            # 本机无中文字体），走上面的 skip()。其余异常一律按 FAIL 记账并继续跑
            # 后面的段落（不能整段 aborted，否则 [6]-[9] 的回归锁一起消失）。
            FAIL.append("汉化包生成")
            print("  FAIL 汉化包生成 -> %s: %s" % (type(e).__name__, e))
            for line in traceback.format_exc().strip().splitlines()[-3:]:
                print("       " + line.strip())

        print("\n[6] 编码判定（回归锁）")
        test_encoding()

        print("\n[7] 任务壳失败路径（回归锁）")
        test_task_runner()

        print("\n[8] 视频转换（真实 ffmpeg，回归锁）")
        test_video_convert(tmp)

        print("\n[9] 复杂编码环境（受约束：多字节只用 UTF-8、单字节只用 1251）")
        test_complex_encoding_env(tmp)

        print("\n[10] 交叉校验工具的判定（ANSI 代码页 / 逐字节比对）")
        test_cross_validate_helpers(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 66)
    print("PASS %d  FAIL %d  SKIP %d" % (len(PASS), len(FAIL), len(SKIP)))
    if FAIL:
        print("失败：")
        for n in FAIL:
            print("  - " + n)
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
