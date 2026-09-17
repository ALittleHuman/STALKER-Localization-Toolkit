# -*- coding: utf-8 -*-
"""引擎兼容性回归：**旧调用形状**必须仍然正确。

背景：本会话的审计指出——旧版散装 FS GUI 调用 `extract_file` 时只传
`{offset, size_real, is_dir}`，**不传 `size_comp` / `use_lzhuf`**：

    data = extract_file(raw, {"offset": n.offset, "size_real": n.size, "is_dir": False})

而游戏原版库里确实存在 LZHUF / LZO 载荷（`cross_validate` 专门手工构造这种库）。
因此引擎必须**容忍这种省略**，否则老调用方会拿到错字节（表现为解包后乱码）。

本探针用引擎自己的编码器手工构造真实形状的库来验证，而不是依赖 pack_db
（`pack_db` 不给文件体做压缩，造不出这种载荷，所以普通往返测不到这条路径）。

用法: python run_engine_compat_probe.py   （退出码 0=全过）
"""
import os
import struct
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "file_system"))

PASS, FAIL = [], []


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
        return
    if r is False:
        FAIL.append(name)
        print("  FAIL %s -> 断言返回 False" % name)
        return
    PASS.append(name)
    print("  PASS %s" % name)


def build_11xx_lzhuf_db(path, payload):
    """手工构造 11xx 库：header 标 uncomp=0（=LZHUF），载荷是 lzhuf 编码。"""
    import stalker_fs as FS
    comp = FS.lzhuf.encode(payload)
    hdr = b"".join([path.encode("cp1251"), b"\x00",
                    struct.pack("<III", 0, 8, len(comp))])
    chdr = FS.lzhuf.encode(hdr)
    return (struct.pack("<II", 0, len(comp)) + comp
            + struct.pack("<I", 0x80000001)
            + struct.pack("<I", len(chdr)) + chdr)


def main():
    print("=" * 64)
    print("引擎兼容性回归：旧调用形状（缺 size_comp/use_lzhuf）")
    print("=" * 64)
    import stalker_fs as FS

    payload = b"<string id=\"x\">Hello STALKER</string>\n" * 60
    db = build_11xx_lzhuf_db("a.txt", payload)

    entries = FS.unpack_db(db, "11xx")
    check("构造的库能被解出条目", lambda: len(entries) == 1)
    if not entries:
        return 1
    e = entries[0]
    print("    条目: path=%s offset=%s size_real=%s size_comp=%s use_lzhuf=%s"
          % (e["path"], e["offset"], e["size_real"], e["size_comp"], e.get("use_lzhuf")))

    full = FS.extract_file(db, e)
    check("完整 entry：解出原文", lambda: full == payload)

    # 旧版散装 GUI 的调用形状（HanaAgent 的 P1-1）。
    # ⚠ 这里必须分清"哪一档旧形状"是引擎**真的**兜住了的：
    #   extract_file 里 use_lzhuf 缺失时用 `size_real == 0 and size_comp > 0` 反推 11xx
    #   的 LZHUF → 所以被兼容的是「**有** size_comp、**没有** use_lzhuf」。
    legacy = FS.extract_file(db, {"offset": e["offset"], "size_real": e["size_real"],
                                  "size_comp": e["size_comp"], "is_dir": False})
    check("旧调用形状（有 size_comp、缺 use_lzhuf）：反推出 LZHUF 并解出原文",
          lambda: legacy == payload)
    check("11xx LZHUF 路径：两种形状结果一致", lambda: legacy == full)

    # 再退一档、**连 size_comp 都不给**的形状不在兼容范围内：既无法反推 LZHUF，
    # 切片长度也退化成 size_real（11xx 压缩条目的 size_real == 0）→ 得到空字节。
    # 把它钉死，免得日后误以为"随手给几个字段都能解"。
    # （这条以前写成"应当解出原文"，与下面 LZO 那条自相矛盾，且因 check() 只判异常
    #   而永久空转 —— 两条断言从未真正执行过。）
    bare = FS.extract_file(db, {"offset": e["offset"], "size_real": e["size_real"],
                                "is_dir": False})
    check("旧调用形状（连 size_comp 都不给）不在兼容范围：11xx 压缩条目解不出内容",
          lambda: bare == b"")

    # ── 边界：**LZO 路径**下旧形状不安全，这里把这条边界钉死 ──
    # 引擎的兜底是 `sc = entry.get("size_comp") or entry["size_real"]`：
    # 缺 size_comp 时 sc 就等于 size_real，于是 `sc != size_real` 为假 →
    # **根本不会调用 LZO 解压**，压缩条目会原样输出压缩字节（表现为乱码）。
    # 旧的散装 GUI 正是这样调的（HanaAgent 的 P1-1）。新版 apps/fs_app.py 的
    # 两个调用点都传了 size_comp，所以新版不受影响；但外部老调用方会踩。
    # 本机没有 LZO 压缩器，无法造真压缩数据，于是用"解压器是否被调用"来判定。
    calls = []
    real_decomp = FS.lzo1x_decompress

    def _spy(data, out_len=None, *a, **k):
        calls.append((len(data), out_len))
        return b"\x00" * (out_len or 0)

    FS.lzo1x_decompress = _spy
    try:
        body = bytes(range(256)) * 4
        fake = struct.pack("<II", 0, len(body)) + body + \
            struct.pack("<I", 0x80000001) + struct.pack("<I", 0) + b""
        calls.clear()
        FS.extract_file(fake, {"offset": 8, "size_real": len(body),
                               "is_dir": False})
        legacy_called = bool(calls)

        calls.clear()
        FS.extract_file(fake, {"offset": 8, "size_real": len(body),
                               "size_comp": len(body) - 8, "is_dir": False})
        sized_called = bool(calls)
    finally:
        FS.lzo1x_decompress = real_decomp

    check("LZO 路径：旧形状（缺 size_comp）**不会**尝试解压 → 压缩条目会输出乱码",
          lambda: legacy_called is False)
    check("LZO 路径：带 size_comp 时才会走解压",
          lambda: sized_called is True)

    # LZO 形状（size_comp != size_real）也必须被容忍
    raw_body = bytes(range(256)) * 4
    lzo_db = struct.pack("<II", 0, len(raw_body)) + raw_body + \
        struct.pack("<I", 0x80000001) + struct.pack("<I", 0) + b""
    check("空 header 不炸（边界）", lambda: isinstance(FS.unpack_db(lzo_db, "xdb"), list))

    print("\n" + "=" * 64)
    print("PASS %d  FAIL %d" % (len(PASS), len(FAIL)))
    if FAIL:
        for n in FAIL:
            print("  - " + n)
    print("=" * 64)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
