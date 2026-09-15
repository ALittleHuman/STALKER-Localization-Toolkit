# -*- coding: utf-8 -*-
"""滚动条真实性审计：**只看真几何与真可见性**，不看 `winfo_manager()`。

为什么单独有一个脚本（用户口径 2026-09-13）：
    > "我要的就是智能隐藏…… 底下滚动条出现的条件是该窗口有东西显示不完全。
    >  包括控件和里面的内容。"
    > "我横向滚动条呢？我正常的大滚动条呢？"

上一轮的审计只查了 `winfo_manager()`，于是报"滚动条在"——而实际是
`manager='pack'` + `1x1` + `winfo_ismapped()==0`：**存在但肉眼看不见**。
所以本脚本对每个视口同时断言四件事：

    1. `winfo_manager()` 非空（被某个几何管理器管着）；
    2. `winfo_ismapped() == 1`（真的被映射，不是"有主但不可见"）；
    3. `winfo_width()/height() > 1`（拿到了**真实尺寸**，不是 Tk 给 0 空间后的 1x1）；
    4. **不许盖在内容上**（滚动条矩形与画布矩形不重叠）—— 这是 place() 那版
       的回归：用户"不认识你放在本来应该给滚动条留下的地方的东西"。

"显示不完全"的判据用 **Tk 自己的** `canvas.xview()/yview()`：
跨度不满 (0.0, 1.0) 就是"这条轴上有东西看不到"。这是最贴近用户的判据，
也避免了"我算了 req 但 Tk 不这么认为"的自说自话。

真页面：把 `apps/fs_app.py` 的 `FSToolApp` 放进 Notebook，每个页面照
`stalker_toolkit.py::_build_one` 的方式套一层
`ScrollViewport(fit="content", minsize_y=px(430))`（模仿 Hub 结构）；
另加一页"一行超宽按钮"的 `ScrollPanel` 夹具（用户实测里那个形状）。
**每个页面都先 `nb.select()` 选上再量** —— 没选中的标签页根本没在布局里，
量它只会得到 1x1 的假数据。

★ **反向不变量（2026-09-15 补：为什么旧版审计查不出来）**：
旧版只有**单向**判据 —— "内容显示不完全 ⇒ 必须有条" + "装得下 ⇒ 条必须收起"，
从没查过反向的"**没有可滚内容 ⇒ 绝不许能滚**"；更糟的是"面板用法核对"把
`fit="content"` **当成契约钉死**，于是 fs 面板那个 `fit="content"`（树的最小请求高
把内容自然高顶到视口之上 → 明明没内容也能滚）在审计眼里是"合规"，我去改它反而会被
审计报红。所以那份审计**结构上不可能**抓到这个缺陷，还会替它站岗。
判据来自用户原话："没有出现滚动条的时候应当能被滚动吗？"

拆成两条**都真的能红**的锁，各放在能复现机制的地方：

  * **契约级**（本脚本 `audit_all_panels`）：页面里**所有** `ScrollPanel` —— body 里
    自带滚动条（弹性内容）就必须 `fit="viewport"`，否则必须 `fit="content"`。
    不点名、不按 app 硬编码；注入"弹性树的面板退回 fit=content"能把它弄红。
  * **行为级**（`run_app_probe`，本脚本不做）：真建一个**矮窗口**里的 `FSToolApp`，
    断言面板 `yview() == (0.0, 1.0)`、`try_scroll()` 不吃事件、强行 `yview_scroll` 也不动。
    ★ 为什么不放在这里：本脚本是 Hub 式布局 —— 页面视口 `fit="content"` + `minsize_y`
    让每个 App 恒定拿到自己的**自然高度**，面板永远压不矮。实测（窗口压到 900x320）
    fs 面板仍有 **396px** 高、`yview=(0.0, 1.0)` —— 在这里写行为判据**永远不可能红**
    （死锁比没锁更糟）。能复现那个机制的是"裸 Toplevel + 矮窗口"（视口 63px < 树
    最小请求高 180px），那里注入后实测 `yview=(0.0, 0.4038)`。

用法：python run_scroll_audit.py     退出码 0 = 全过
"""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)
for _s in ("file_system", "font_pack", "plugins"):
    _p = os.path.join(BASE, _s)
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import tkinter as tk                      # noqa: E402
from tkinter import ttk                   # noqa: E402

from toolkit_base import _BaseTk          # noqa: E402
from toolkit_theme import apply_theme, px  # noqa: E402
import toolkit_widgets as W                # noqa: E402

FAILS = []          # 断言失败（含"装不下却看不到滚动条"）


def pump(win, times=6):
    """把待处理的事件跑干净（几何、<Configure>、视口的 after 看门狗都要跑到）。

    `update_idletasks()` 不够：滚动条的显隐是在 `<Configure>`/`set()` 回调里做的，
    而 `_watch_req` 走的是 `after`。多跑几轮 `update()` 才能到稳定态。
    """
    for _ in range(times):
        try:
            win.update_idletasks()
            win.update()
        except tk.TclError:
            return


def rect(w):
    try:
        return (w.winfo_rootx(), w.winfo_rooty(),
                w.winfo_width(), w.winfo_height())
    except Exception:
        return (0, 0, 0, 0)


def overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    if aw <= 0 or ah <= 0 or bw <= 0 or bh <= 0:
        return False
    return not (ax + aw <= bx or bx + bw <= ax or ay + ah <= by or by + bh <= ay)


def bar_state(w):
    """滚动条的真实状态（四个数一起看，缺一不可）。"""
    try:
        return {"mgr": w.winfo_manager() or "",
                "map": int(w.winfo_ismapped()),
                "w": int(w.winfo_width()), "h": int(w.winfo_height())}
    except Exception:
        return {"mgr": "?", "map": 0, "w": 0, "h": 0}


def bar_really_visible(st):
    return bool(st["mgr"]) and st["map"] == 1 and st["w"] > 1 and st["h"] > 1


def viewport_state(vp):
    """一个 ScrollViewport 的完整真实状态。"""
    c = vp.canvas
    x0, x1 = c.xview()
    y0, y1 = c.yview()
    return {
        "canvas": (int(c.winfo_width()), int(c.winfo_height())),
        "req": (int(vp.content.winfo_reqwidth()), int(vp.content.winfo_reqheight())),
        "content": (int(vp.content.winfo_width()), int(vp.content.winfo_height())),
        "view": (int(vp.winfo_width()), int(vp.winfo_height())),
        "ovf_x": not (x0 <= 0.0 and x1 >= 1.0),
        "ovf_y": not (y0 <= 0.0 and y1 >= 1.0),
        "xview": (round(x0, 3), round(x1, 3)),
        "yview": (round(y0, 3), round(y1, 3)),
        "hbar": bar_state(vp.hbar) if vp.hbar is not None else None,
        "vbar": bar_state(vp.vbar),
        "hbar_rect": rect(vp.hbar) if vp.hbar is not None else None,
        "vbar_rect": rect(vp.vbar),
        "canvas_rect": rect(c),
        "view_rect": rect(vp),
    }


def check_one(tag, vp, st):
    """对一个视口做全部断言；返回本次发现的"装不下却看不到"计数。"""
    bad = 0
    for axis, key, bar_key, rect_key in (("横", "ovf_x", "hbar", "hbar_rect"),
                                         ("纵", "ovf_y", "vbar", "vbar_rect")):
        st_bar = st[bar_key]
        if st_bar is None:
            continue
        vis = bar_really_visible(st_bar)
        if st[key]:
            # 内容显示不完全 → 必须**真的**看得见
            if not vis:
                bad += 1
                FAILS.append("%s %s轴：内容显示不完全却看不到滚动条 %r（xview=%r yview=%r）"
                             % (tag, axis, st_bar, st["xview"], st["yview"]))
            if st_bar["map"] == 1:
                # 不许盖在内容上（place 那版的回归）
                if overlap(st[rect_key], st["canvas_rect"]):
                    FAILS.append("%s %s轴：滚动条盖在内容上 bar=%r canvas=%r"
                                 % (tag, axis, st[rect_key], st["canvas_rect"]))
                # 滚动条必须**占满自己那一条**：横条横跨内容区（右边让给竖条），
                # 竖条竖跨内容区（下边让给横条）。实测过的坏形态是贴在画布右边的
                # `44x15` 小方块 —— `manager='pack'`、`ismapped()=1`、也有尺寸，
                # 只是短；只查 manager/ismapped 都拦不住，正是用户问的
                # "我正常的大滚动条呢？"。
                vw_, vh_ = st["view"]
                other = st["vbar"] if key == "ovf_x" else st["hbar"]
                other_len = 0
                if other is not None and other["map"] == 1:
                    other_len = other["w"] if key == "ovf_y" else other["h"]
                span = st_bar["w"] if key == "ovf_x" else st_bar["h"]
                need = (vw_ if key == "ovf_x" else vh_) - other_len
                if span < need - 2:
                    FAILS.append("%s %s轴：滚动条没占满自己那一条（长 %d < 应有 %d）bar=%r"
                                 % (tag, axis, span, need, st_bar))
                # 滚动条必须挤在视口内（真的占了自己那一条，而不是伸到面板外面）
                vx, vy, vw_, vh_ = st["view_rect"]
                bx, by, bw_, bh_ = st[rect_key]
                if (bx < vx - 1 or by < vy - 1
                        or bx + bw_ > vx + vw_ + 1 or by + bh_ > vy + vh_ + 1):
                    FAILS.append("%s %s轴：滚动条跑到视口外面了 bar=%r view=%r"
                                 % (tag, axis, st[rect_key], st["view_rect"]))
        else:
            # 装得下 → 必须收起（智能隐藏：空着的东西不该占位）
            if st_bar["mgr"] or st_bar["map"] == 1:
                FAILS.append("%s %s轴：装得下却仍然占着滚动条 %r" % (tag, axis, st_bar))
    return bad


def walk_viewports(w, out=None):
    if out is None:
        out = []
    try:
        if isinstance(w, W.ScrollViewport):
            out.append(w)
        for c in w.winfo_children():
            walk_viewports(c, out)
    except Exception:
        pass
    return out


def line(tag, st):
    def _b(s):
        if s is None:
            return "  无           "
        return "%-9s %4dx%-4d map=%d" % (s["mgr"] or "-", s["w"], s["h"], s["map"])
    return ("    %-22s 画布=%dx%-5d 内容req=%dx%-5d 内容=%dx%-5d 视口=%dx%-5d "
            "xview=%s yview=%s\n%34s 横条 %s | 竖条 %s" % (
                tag, st["canvas"][0], st["canvas"][1],
                st["req"][0], st["req"][1],
                st["content"][0], st["content"][1],
                st["view"][0], st["view"][1],
                st["xview"], st["yview"], "",
                _b(st["hbar"]), _b(st["vbar"])))


# ══════════════════════ 夹具：真页面 ══════════════════════
def _fs_factory(parent):
    from apps.fs_app import FSToolApp
    return FSToolApp(parent)


def _panel_factory(parent):
    """夹具：一行超宽按钮（用户实测里那个"按钮被遮住却没有滚动条"的形状）。"""
    p = W.ScrollPanel(parent, "夹具面板")
    p.pack(fill="both", expand=True)
    row = tk.Frame(p.body)
    for i in range(8):
        ttk.Button(row, text="按钮%d" % i, width=8).pack(side="left", padx=(0, 4))
    row.pack(fill="x")
    p.refresh()
    return p


def build_real_pages(root):
    """按 Hub 的真实结构搭：Notebook + 每页一层页面视口 + 页内真组件。

    `stalker_toolkit.py::_build_one` 原样：
        tab = tk.Frame(nb); nb.add(tab, text=label)
        page_view = ScrollViewport(tab, fit="content", minsize_y=page_min_h())   # px(430)
        page_view.pack(fill="both", expand=True)
        apps[label] = factory(page_view.content)
    """
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    pages = []
    for label, factory in (("文件系统", _fs_factory), ("滚动面板夹具", _panel_factory)):
        tab = tk.Frame(nb)
        nb.add(tab, text=label)
        page_view = W.ScrollViewport(tab, fit="content", minsize_y=px(430))
        page_view.pack(fill="both", expand=True)
        try:
            app = factory(page_view.content)
        except Exception:
            traceback.print_exc()
            ttk.Label(page_view.content, text="构建失败").pack()
            app = None
        pages.append((label, tab, page_view, app))
    return nb, pages


SIZES = [(1500, 1000), (1280, 860), (1100, 700), (1024, 700),
         (900, 620), (800, 520), (700, 460), (640, 400)]


def walk_widgets(w):
    for ch in w.winfo_children():
        yield ch
        yield from walk_widgets(ch)


def _body_self_scrolls(panel):
    """面板 body 里有没有**自己的**滚动条。

    有 = 里装的东西自己会滚（弹性内容，如 `CanvasTree`）→ 面板自己不该再滚。
    这是 app 无关的结构判据：面板自己的两条条子挂在 `ScrollViewport` 上，**不在**
    `panel.body` 里，所以 body 子树里出现 `AutoScrollbar` 只可能是内容自带的。
    （★ 别用 `isinstance(子控件, CanvasTree)` 判：`CanvasTree(...)` 返回的是**包装
    对象**，进控件树的只有 `CanvasTree.get()` 那个 frame，这样判永远 False。）
    """
    return any(isinstance(w, W.AutoScrollbar) for w in walk_widgets(panel.body))


def walk_panels(w, out=None):
    if out is None:
        out = []
    try:
        if isinstance(w, W.ScrollPanel):
            out.append(w)
        for c in w.winfo_children():
            walk_panels(c, out)
    except Exception:
        pass
    return out


def audit_all_panels(host, tag):
    """**类级契约**：`host` 子树里所有 `ScrollPanel`，`fit` 必须与里装的东西一致。

    body 里自带滚动条（弹性内容）→ 必须 `fit="viewport"`：面板自己不滚，
    "行多了怎么办"交给内容自己的条子（用户判据："没有出现滚动条的时候不该能滚"）。
    静态内容 → 必须 `fit="content"`，由面板自己滚。

    不点名、不按 app 硬编码 —— 任何页面、任何面板都查。返回本页查到的面板数与失败数。
    """
    n = 0
    bad = 0
    for panel in walk_panels(host):
        view = panel.view
        if not isinstance(view, W.ScrollViewport):
            continue
        elastic = _body_self_scrolls(panel)
        want = "viewport" if elastic else "content"
        n += 1
        if view._fit != want or not view._horizontal:
            bad += 1
            FAILS.append("面板用法核对（全页面）%s：%s 的 body 里%s自带滚动条，"
                         "视口却是 horizontal=%r / fit=%r —— 应为 horizontal=True / "
                         "fit=%r"
                         % (tag, panel, "" if elastic else "没",
                            getattr(view, "_horizontal", None),
                            getattr(view, "_fit", None), want))
    return n, bad


def audit_panel_wiring(app):
    """核对 `ScrollPanel` 与 fs_app 两面板"**直接当窗格**"的用法与实现是否一致。

    现状（apps/fs_app.py）：
        panel = ScrollPanel(pan, "…"); pan.add(panel, weight=…)
        pan.set_minsize(panel, min(panel.min_height(), px(200)))
    **当契约来测**的是结构与语义（这些一旦被改回去就会重现用户踩过的坑）：
      * 面板真的是 `ScrollPanel`，而且**直接**是窗格 —— 不是被 `add_clipped` 又套了
        一层（那层裁剪会把面板底部切掉，而横向滚动条恰好就在那儿：用户实测过的坑）；
      * 面板的内部视口是 `horizontal=True` —— 横向开关决定"宽了会不会出横条"；
      * **`fit` 必须与里装的东西一致**：面板 body 里若有自带滚动条的 `CanvasTree`
        （弹性内容，纵向跟着视口走），就必须 `fit="viewport"` —— 否则树的最小请求高
        会把"内容自然高"顶到视口之上，**只有 1 行的列表也能上下拖**（用户 2026-09-15
        的原话："不是竖条的问题，是不该滚动的时候也滚"）；反之（静态内容）用
        `fit="content"`，让面板自己滚。

    **只打印、不判定**的是 `set_minsize` 的实际落值：实测它当前恒为 `1`
    （构造期 `ScrollPanel.min_height()` 读到的是容器的**陈旧请求尺寸** 1，
    不是最终的 168/210），`ScrollPanel._pad_y()` 也因为在 `cget("padding")`
    返回元组 `(6,)` 时 `int()` 失败而恒返回 0。这两件都属于 fs_app 的**窗格下限
    策略**（"布局/间距"范畴，用户已明确否决过擅自改动），所以这里如实量出来、
    写进报告，不由本次滚动条修复顺手改掉。
    """
    pan = app.db_panel.master
    panes = pan._panes()
    for name, panel in (("db_panel", app.db_panel), ("file_panel", app.file_panel)):
        if not isinstance(panel, W.ScrollPanel):
            FAILS.append("面板用法核对：%s 不是 ScrollPanel（是 %r）"
                         % (name, type(panel).__name__))
            continue
        if panel not in panes:
            FAILS.append("面板用法核对：%s 不是窗格的直接成员（被又套了一层？）" % name)
        view = panel.view
        elastic = _body_self_scrolls(panel)
        want_fit = "viewport" if elastic else "content"
        ok_view = (isinstance(view, W.ScrollViewport) and view._horizontal
                   and view._fit == want_fit)
        if not ok_view:
            FAILS.append("面板用法核对：%s 的内部视口不是 horizontal=True/fit=%s（%r/%r）"
                         "（里装的是%s内容 → %s）"
                         % (name, want_fit, getattr(view, "_horizontal", None),
                            getattr(view, "_fit", None),
                            "弹性" if elastic else "静态",
                            "弹性内容不许面板自己滚" if elastic
                            else "静态内容由面板滚"))
        stored = pan._mins.get(panel)
        need = min(panel.min_height(), px(200))
        note = "" if stored == need else "  ← 注意：与内容自己说的不一致（见函数文档）"
        print("    面板 %-10s ScrollPanel=%s 是窗格成员=%s 视口=%s/%s 自带滚动条=%s "
              "窗格 minsize=%r（内容自己说 %r）%s"
              % (name, isinstance(panel, W.ScrollPanel), panel in panes,
                 getattr(view, "_horizontal", None), getattr(view, "_fit", None),
                 elastic, stored, need, note))


def dead_rect(state):
    """画布已经拿到真实尺寸、但视口本身没被映射 → 这一屏量不出结论。"""
    return state["canvas"][0] <= 1 or state["canvas"][1] <= 1


def main():
    root = _BaseTk()
    apply_theme("dark")
    root.title("scroll audit")
    root.geometry("1280x860+60+60")
    nb, pages = build_real_pages(root)
    pump(root, 10)

    total_bad = 0
    skipped = 0
    n_panels = 0
    bad_panels = 0
    print("=" * 112)
    print("真页面滚动条审计（判定用 Tk 自己的 xview/yview；每页都先 select 再量）")
    print("=" * 112)

    print("\n面板用法核对（ScrollPanel 直接当窗格 + minsize 由内容自己说）：")
    audit_panel_wiring(pages[0][3])

    # ★ 类级契约：**所有**页面里**所有**面板，fit 必须与"body 里有没有自带滚动条"一致
    print("\n面板用法核对（全页面，类级契约：弹性内容 ⇒ fit=viewport）：")
    for idx, (label, tab, page_view, app) in enumerate(pages):
        nb.select(idx)
        pump(root, 6)
        n, b = audit_all_panels(page_view, "页%d %s" % (idx, label))
        n_panels += n
        bad_panels += b
        print("    页%d %-8s 面板 %d 个，违约 %d 个" % (idx, label, n, b))

    for idx, (label, tab, page_view, app) in enumerate(pages):
        nb.select(idx)
        pump(root, 8)
        print("\n" + "─" * 112)
        print("页面 [%d] %s" % (idx, label))
        print("─" * 112)
        for w_, h_ in SIZES:
            root.geometry("%dx%d+60+60" % (w_, h_))
            pump(root, 8)
            vps = [vp for vp in walk_viewports(root) if vp.winfo_ismapped()]
            print("\n── 窗口 %dx%d（在布局里的视口 %d 个）" % (w_, h_, len(vps)))
            for i, vp in enumerate(vps):
                st = viewport_state(vp)
                # 每个视口自己再稳一轮：滚动条出现会改变画布尺寸，可能引出另一条
                for _ in range(5):
                    pump(root, 2)
                    st2 = viewport_state(vp)
                    if (st2["xview"] == st["xview"] and st2["yview"] == st["yview"]
                            and st2["canvas"] == st["canvas"]):
                        break
                    st = st2
                tag = "页%d %s #%d" % (idx, label, i)
                if dead_rect(st):
                    skipped += 1
                    print("    %-22s 画布还没拿到尺寸（跳过判定）" % tag)
                    continue
                print(line(tag, st))
                total_bad += check_one("窗口%dx%d %s" % (w_, h_, tag), vp, st)

    # ── 反复 宽↔窄：隐藏再出现多次仍要正确（用户口径里的"智能隐藏"）──
    print("\n" + "=" * 112)
    print("反复 宽↔窄 8 轮（夹具页面板）：横条应当 收→出→收→出 每次都真的可见")
    print("=" * 112)
    nb.select(1)
    pump(root, 6)
    panel = pages[1][3]
    for i in range(8):
        wide = (i % 2 == 0)
        root.geometry("%dx520+60+60" % (1300 if wide else 640,))
        pump(root, 6)
        st = viewport_state(panel.view)
        print("  第%d轮(%s) ovf_x=%-5s 横条=%r" % (i + 1, "宽" if wide else "窄",
                                                  st["ovf_x"], st["hbar"]))
        total_bad += check_one("宽窄第%d轮(%s)" % (i + 1, "宽" if wide else "窄"),
                               panel.view, st)

    # ── 汇总 ──
    print("\n" + "=" * 112)
    print("内容显示不完全却看不到滚动条的计数：%d（必须为 0）｜ 跳过（画布无尺寸）：%d"
          % (total_bad, skipped))
    print("面板用法核对（全页面）：查了 %d 个面板，违约 %d 个（必须为 0）"
          % (n_panels, bad_panels))
    if FAILS:
        print("失败断言 %d 条：" % len(FAILS))
        for f in FAILS[:40]:
            print("  FAIL " + f)
        if len(FAILS) > 40:
            print("  … 其余 %d 条省略" % (len(FAILS) - 40))
    else:
        print("全部断言通过：该出现的真的出现（有尺寸、ismapped=1、不盖内容），该收起的真的收起，"
              "弹性内容的面板自己都不滚。")
    print("=" * 112)

    try:
        root.destroy()
    except Exception:
        pass
    return 0 if (total_bad == 0 and bad_panels == 0 and not FAILS) else 1


if __name__ == "__main__":
    sys.exit(main())
