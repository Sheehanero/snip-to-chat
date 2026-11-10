"""선택 화면 (tkinter).

화면을 얼려서 어둡게 깔고, 마우스 아래 창을 밝게 강조한다.
클릭 = 그 창 전체, 드래그 = 영역, Shift를 누른 채 고르면 여러 장 담기, Enter = 한 번에 첨부,
Esc·오른쪽 클릭 = 취소.
"""

from __future__ import annotations

import time
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Sequence

from PIL import Image, ImageTk

from .geometry import Rect, hit_test, is_drag, rect_from_drag
from .imaging import dim

ACCENT = "#378ADD"
FONT = ("Malgun Gothic", 11)
FONT_BOLD = ("Malgun Gothic", 11, "bold")
SHIFT_MASK = 0x0001


@dataclass
class Selection:
    kind: str  # "window" | "region"
    rect: Rect  # 가상 화면 좌표
    window: object | None  # win32.WindowInfo
    label: str


class Overlay:
    def __init__(
        self,
        root: tk.Tk,
        screenshot: Image.Image,
        origin: Rect,
        windows: Sequence,
        on_finish: Callable[[list[Selection]], None],
        on_cancel: Callable[[], None],
        max_items: int = 20,
    ):
        self.root = root
        self.shot = screenshot
        self.origin = origin
        self.windows = list(windows)
        self.on_finish = on_finish
        self.on_cancel = on_cancel
        self.max_items = max_items
        self.bag: list[Selection] = []
        self.press: tuple[int, int] | None = None
        self.dragging = False
        self.hovered = None
        self.last_draw = 0.0
        self.closed = False
        self._photos: list[ImageTk.PhotoImage] = []

        top = tk.Toplevel(root)
        self.top = top
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        top.geometry(f"{origin.width}x{origin.height}+{origin.left}+{origin.top}")
        c = tk.Canvas(top, width=origin.width, height=origin.height, highlightthickness=0, cursor="crosshair", bd=0)
        c.pack(fill="both", expand=True)
        self.canvas = c

        self.bg_photo = ImageTk.PhotoImage(dim(screenshot))
        c.create_image(0, 0, anchor="nw", image=self.bg_photo)
        self.bright_id = c.create_image(0, 0, anchor="nw")
        self.outline_id = c.create_rectangle(0, 0, 0, 0, outline=ACCENT, width=3, state="hidden")
        self.label_bg = c.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline=ACCENT, state="hidden")
        self.label_id = c.create_text(0, 0, anchor="nw", text="", font=FONT, fill="#111111", state="hidden")
        self.marks: list[int] = []

        # 안내 문구 (커서가 있는 모니터 위쪽 가운데 대신, 가상 화면 위쪽 가운데)
        hint = "클릭: 창 전체   드래그: 영역   Shift 누른 채: 여러 장 담기   Enter: 첨부   Esc: 취소"
        cx = origin.width // 2
        self.hint_bg = c.create_rectangle(0, 0, 0, 0, fill="#1f1f1f", outline="")
        self.hint_id = c.create_text(cx, 22, text=hint, font=FONT, fill="#ffffff")
        self._fit_bg(self.hint_bg, self.hint_id, pad=10)

        self.tray_bg = c.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline=ACCENT, width=2, state="hidden")
        self.tray_id = c.create_text(cx, origin.height - 40, text="", font=FONT_BOLD, fill="#0C447C", state="hidden")

        for seq, fn in (
            ("<Motion>", self._motion),
            ("<ButtonPress-1>", self._press),
            ("<B1-Motion>", self._drag),
            ("<ButtonRelease-1>", self._release),
            ("<ButtonPress-3>", lambda e: self.cancel()),
        ):
            c.bind(seq, fn)
        for seq in ("<Escape>",):
            top.bind(seq, lambda e: self.cancel())
        for seq in ("<Return>", "<KP_Enter>"):
            top.bind(seq, lambda e: self.finish())

        top.lift()
        top.focus_force()
        top.after(60, self._refocus)

    # ------------------------------------------------------------ 좌표 변환
    def _screen(self, e) -> tuple[int, int]:
        return e.x + self.origin.left, e.y + self.origin.top

    def _local(self, r: Rect) -> Rect:
        return r.intersect(self.origin).offset(-self.origin.left, -self.origin.top)

    def _refocus(self):
        if not self.closed:
            self.top.focus_force()

    # ------------------------------------------------------------ 그리기
    def _fit_bg(self, bg_id, text_id, pad=6):
        x0, y0, x1, y1 = self.canvas.bbox(text_id)
        self.canvas.coords(bg_id, x0 - pad, y0 - pad // 2, x1 + pad, y1 + pad // 2)

    def _show_box(self, r: Rect, label: str):
        local = self._local(r)
        c = self.canvas
        if local.empty:
            self._hide_box()
            return
        crop = self.shot.crop(local.as_box())
        photo = ImageTk.PhotoImage(crop)
        self._photos = [photo]  # 이전 것은 버려서 메모리를 아낀다
        c.itemconfigure(self.bright_id, image=photo, state="normal")
        c.coords(self.bright_id, local.left, local.top)
        c.coords(self.outline_id, local.left + 1, local.top + 1, local.right - 1, local.bottom - 1)
        c.itemconfigure(self.outline_id, state="normal")
        c.itemconfigure(self.label_id, text=label, state="normal")
        ly = local.top - 30 if local.top >= 34 else local.top + 8
        lx = max(4, min(local.left, self.origin.width - 420))
        c.coords(self.label_id, lx + 8, ly + 4)
        self._fit_bg(self.label_bg, self.label_id)
        c.itemconfigure(self.label_bg, state="normal")
        for item in (self.bright_id, self.outline_id, self.label_bg, self.label_id):
            c.tag_raise(item)
        for item in (self.hint_bg, self.hint_id, self.tray_bg, self.tray_id):
            c.tag_raise(item)

    def _hide_box(self):
        for item in (self.bright_id, self.outline_id, self.label_bg, self.label_id):
            self.canvas.itemconfigure(item, state="hidden")

    def _update_tray(self, message: str | None = None):
        c = self.canvas
        if not self.bag and not message:
            c.itemconfigure(self.tray_bg, state="hidden")
            c.itemconfigure(self.tray_id, state="hidden")
            return
        text = message or f"{len(self.bag)}장 담음 · Enter 또는 여기를 눌러 한 번에 첨부 · Esc 취소"
        c.itemconfigure(self.tray_id, text=text, state="normal")
        self._fit_bg(self.tray_bg, self.tray_id, pad=14)
        c.itemconfigure(self.tray_bg, state="normal")
        c.tag_raise(self.tray_bg)
        c.tag_raise(self.tray_id)

    def _mark(self, sel: Selection):
        local = self._local(sel.rect)
        if local.empty:
            return
        n = len(self.bag)
        c = self.canvas
        self.marks.append(c.create_rectangle(*local.as_box(), outline=ACCENT, width=2, dash=(6, 4)))
        self.marks.append(
            c.create_text(local.left + 14, local.top + 14, text=str(n), font=FONT_BOLD, fill=ACCENT)
        )

    # ------------------------------------------------------------ 마우스
    def _motion(self, e):
        if self.press is not None:
            return
        x, y = self._screen(e)
        w = hit_test(self.windows, x, y)
        if w is self.hovered:
            return
        self.hovered = w
        if w is None:
            self._hide_box()
        else:
            self._show_box(w.rect, f"{w.label}   클릭: 창 전체")

    def _press(self, e):
        self.press = self._screen(e)
        self.dragging = False

    def _drag(self, e):
        if self.press is None:
            return
        x, y = self._screen(e)
        if not self.dragging and is_drag(*self.press, x, y):
            self.dragging = True
            self.hovered = None
        if self.dragging:
            now = time.monotonic()
            if now - self.last_draw < 0.016:
                return
            self.last_draw = now
            r = rect_from_drag(*self.press, x, y)
            self._show_box(r, f"영역 {r.width} × {r.height}")

    def _release(self, e):
        if self.press is None:
            return
        x, y = self._screen(e)
        start = self.press
        self.press = None
        shift = bool(e.state & SHIFT_MASK)

        if self.bag and not self.dragging and self._in_tray(e.x, e.y):
            self.finish()
            return

        if self.dragging or is_drag(*start, x, y):
            self.dragging = False
            r = rect_from_drag(*start, x, y)
            if r.width < 8 or r.height < 8:
                self._hide_box()
                return
            sel = Selection("region", r, None, f"영역 {r.width}×{r.height}")
        else:
            w = hit_test(self.windows, x, y)
            if w is None:
                return
            sel = Selection("window", w.rect, w, w.label)

        if len(self.bag) >= self.max_items:
            self._update_tray(f"한 메시지에 {self.max_items}장까지예요 · Enter로 첨부하세요")
            return
        self.bag.append(sel)
        if shift:
            self._mark(sel)
            self._hide_box()
            self.hovered = None
            self._update_tray()
        else:
            self.finish()

    def _in_tray(self, lx: int, ly: int) -> bool:
        if self.canvas.itemcget(self.tray_bg, "state") == "hidden":
            return False
        x0, y0, x1, y1 = self.canvas.coords(self.tray_bg)
        return x0 <= lx <= x1 and y0 <= ly <= y1

    # ------------------------------------------------------------ 끝내기
    def _close(self):
        self.closed = True
        try:
            self.top.destroy()
        except tk.TclError:
            pass
        self._photos.clear()
        self.root.update_idletasks()

    def finish(self):
        if self.closed:
            return
        if not self.bag:
            return
        picked = list(self.bag)
        self._close()
        self.on_finish(picked)

    def cancel(self):
        if self.closed:
            return
        self._close()
        self.on_cancel()
