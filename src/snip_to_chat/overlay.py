"""선택 화면 (tkinter).

화면을 얼려서 어둡게 깔고, 마우스 아래 창을 밝게 강조한다.
클릭 = 그 창 전체, 드래그 = 영역, Space = 지금 쓰던 창, Shift를 누른 채 고르면 여러 장 담기,
Enter = 한 번에 첨부, Esc·오른쪽 클릭 = 취소.
Tab = 창 목록: 다른 창에 가려졌거나 최소화된 창까지 썸네일로 보여주고 거기서 고른다.
창 목록에서 크롬·엣지 창을 누르면 그 창의 탭 목록이 한 번 더 뜬다 (뒤쪽 탭도 고를 수 있다).
"""

from __future__ import annotations

import queue
import time
import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Sequence

from PIL import Image, ImageTk

from .geometry import (
    Rect, fit_inside, grid_layout, hit_test, is_drag, monitor_at, place_in, rect_from_drag,
)
from .imaging import dim
from .tabmatch import list_order

ACCENT = "#378ADD"
FONT = ("Malgun Gothic", 11)
FONT_SMALL = ("Malgun Gothic", 10)
FONT_BOLD = ("Malgun Gothic", 11, "bold")
SHIFT_MASK = 0x0001


@dataclass(eq=False)
class Card:
    rect: Rect  # 캔버스 좌표
    entry: object  # win32.WindowInfo (최소화된 창이면 minimized=True)
    frame_id: int
    thumb_id: int | None = None
    photo: object = None
    badge_ids: tuple = ()


@dataclass
class Selection:
    kind: str  # "window" | "region" | "tab"
    rect: Rect  # 가상 화면 좌표
    window: object | None  # win32.WindowInfo
    label: str
    tab: object = None  # kind == "tab"일 때 browser_tabs.TabInfo
    image: object = None  # 미리보기로 이미 찍어 둔 그림 (있으면 다시 찍지 않는다)


@dataclass(eq=False)
class TabRow:
    rect: Rect  # 캔버스 좌표
    tab: object  # TabInfo
    frame_id: int
    badge_ids: tuple = ()
    thumb_id: int | None = None
    photo: object = None
    image: object = None  # 미리보기 원본 (고르면 그대로 첨부)


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
        monitors: Sequence[Rect] = (),
        cursor: tuple[int, int] | None = None,
        active=None,
        hidden_windows: Sequence = (),
        thumbnail: Callable[[object], Image.Image | None] | None = None,
        start_in_list: bool = False,
        tabs_of: Callable[[object], list | None] | None = None,
        tab_previews: Callable[[object, Callable], object] | None = None,
    ):
        self.root = root
        self.active = active  # 지금 쓰던 창 (Space로 바로 고름). 없으면 None
        self.hidden_windows = list(hidden_windows)  # 최소화된 창 (창 목록에서만 보임)
        self.thumbnail = thumbnail  # 창 → 썸네일 이미지 (가려진 창도 내용 그대로)
        self.list_mode = False
        self.cards: list[Card] = []
        self._list_ids: list[int] = []
        self._thumb_todo: list[Card] = []
        self._hover_card: Card | None = None
        self.tabs_of = tabs_of  # 브라우저 창 → 탭 목록 (없거나 1개면 None/짧은 목록)
        self.tab_window = None  # 탭 목록을 보고 있는 브라우저 창
        self.tab_rows: list[TabRow] = []
        self._tab_ids: list[int] = []
        self._hover_row: TabRow | None = None
        self.tab_previews = tab_previews  # (창, 그림받기) → 멈출 수 있는 미리보기 작업
        self._previewer = None
        self._preview_q: queue.Queue = queue.Queue()
        self.shot = screenshot
        self.origin = origin
        # 듀얼 모니터: 선택 화면은 모든 모니터를 덮지만, 안내 문구·담기 바·이름표는
        # 마우스가 있는 모니터 안에만 둔다 (가상 화면 가운데에 두면 두 모니터 경계에 걸친다)
        self.monitors = list(monitors) or [origin]
        start = cursor or (origin.left + origin.width // 2, origin.top + origin.height // 2)
        self.monitor = monitor_at(self.monitors, *start)
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

        hint = "Space: 지금 쓰던 창   클릭: 창 전체   드래그: 영역   Tab: 가려진 창 목록   Shift: 여러 장   Enter: 첨부   Esc: 취소"
        self.hint_bg = c.create_rectangle(0, 0, 0, 0, fill="#1f1f1f", outline="")
        self.hint_id = c.create_text(0, 0, text=hint, font=FONT, fill="#ffffff")
        self.tray_bg = c.create_rectangle(0, 0, 0, 0, fill="#ffffff", outline=ACCENT, width=2, state="hidden")
        self.tray_id = c.create_text(0, 0, text="", font=FONT_BOLD, fill="#0C447C", state="hidden")
        self._place_chrome()

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
        top.bind("<space>", self._space)
        top.bind("<Tab>", self._toggle_list)
        top.bind("<Shift-Tab>", self._toggle_list)

        # 열자마자 지금 쓰던 창을 강조해 둔다: 그대로 Space(또는 클릭)면 그 창이 찍힌다
        if start_in_list:
            self._open_list()
        elif self.active is not None:
            self._show_box(self.active.rect, f"지금 쓰던 창 · {self.active.label}   Space: 이 창 찍기")

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

    def _place_chrome(self):
        """안내 문구는 지금 모니터 위쪽 가운데, 담기 바는 아래쪽 가운데."""
        m = self._local(self.monitor)
        cx = (m.left + m.right) // 2
        self.canvas.coords(self.hint_id, cx, m.top + 22)
        self._fit_bg(self.hint_bg, self.hint_id, pad=10)
        self.canvas.coords(self.tray_id, cx, m.bottom - 40)
        if self.canvas.itemcget(self.tray_bg, "state") != "hidden":
            self._fit_bg(self.tray_bg, self.tray_id, pad=14)

    def _follow_cursor(self, x: int, y: int):
        if self.list_mode:  # 목록은 연 모니터에 고정
            return
        m = monitor_at(self.monitors, x, y)
        if m != self.monitor:
            self.monitor = m
            self._place_chrome()

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
        # 이름표는 상자 왼쪽 위가 있는 모니터 안에 둔다 (모니터 경계에 걸치지 않게)
        mon = self._local(monitor_at(self.monitors, r.left, r.top))
        ly = local.top - 30 if local.top - mon.top >= 34 else local.top + 8
        x0, _, x1, _ = c.bbox(self.label_id)
        lx = place_in(mon, (x1 - x0) + 16, local.left)
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

    # ------------------------------------------------------------ 창 목록
    def _toggle_list(self, e=None):
        if self.closed:
            return "break"
        if self.tab_window is not None:
            self._close_tabs()  # 탭 목록 → 창 목록
        elif self.list_mode:
            self._close_list()
        else:
            self._open_list()
        return "break"  # Tab이 다른 위젯으로 포커스를 옮기지 않게

    def _open_list(self):
        self.list_mode = True
        self.press = None
        self.dragging = False
        self.hovered = None
        self._hide_box()
        c = self.canvas
        m = self._local(self.monitor)
        ids = self._list_ids
        ids.append(c.create_rectangle(m.left, m.top, m.right, m.bottom, fill="#161616", outline=""))
        ids.append(c.create_text(
            m.left + 28, m.top + 22, anchor="nw", fill="#ffffff", font=FONT_BOLD,
            text="창 목록 · 다른 창에 가려졌거나 최소화된 창도 고를 수 있어요",
        ))
        ids.append(c.create_text(
            m.right - 28, m.top + 24, anchor="ne", fill="#bbbbbb", font=FONT,
            text="클릭: 첨부   Shift+클릭: 담기   Space: 지금 쓰던 창   Tab: 돌아가기   Esc: 취소",
        ))
        # 엣지·크롬을 왼쪽 위에, 같은 앱 안에서는 앞에 있던 창 먼저
        entries = list_order(list(self.windows) + list(self.hidden_windows))
        area = Rect(m.left + 28, m.top + 64, m.right - 28, m.bottom - 80)  # 아래는 담기 바 자리
        rects = grid_layout(len(entries), area)
        self.cards = []
        for entry, r in zip(entries, rects):
            frame = c.create_rectangle(r.left, r.top, r.right, r.bottom, fill="#262626", outline="#444444", width=2)
            ids.append(frame)
            card = Card(r, entry, frame)
            img_box = self._thumb_box(r)
            note = "최소화된 창 · 고르면 잠깐 펼쳐서 찍어요" if getattr(entry, "minimized", False) else "불러오는 중…"
            ids.append(c.create_text((img_box.left + img_box.right) // 2, (img_box.top + img_box.bottom) // 2,
                                     text=note, fill="#888888", font=FONT_SMALL))
            ids.append(c.create_text(r.left + 8, r.bottom - 24, anchor="nw", fill="#dddddd", font=FONT_SMALL,
                                     text=_clip(getattr(entry, "label", "창"), r.width), width=r.width - 16))
            self.cards.append(card)
            if not getattr(entry, "minimized", False):
                self._thumb_todo.append(card)
        if len(rects) < len(entries):
            ids.append(c.create_text((m.left + m.right) // 2, m.bottom - 64, fill="#bbbbbb", font=FONT_SMALL,
                                     text=f"화면이 좁아 {len(entries) - len(rects)}개는 안 보여요"))
        for item in (self.tray_bg, self.tray_id):
            c.tag_raise(item)
        for mark in self.bag:  # 앞 화면에서 담아 둔 창은 목록에서도 표시
            self._mark_card_for(mark)
        self.top.after(15, self._next_thumb)

    def _close_list(self):
        self._close_tabs()
        self.list_mode = False
        self._thumb_todo.clear()
        self._hover_card = None
        for i in self._list_ids:
            self.canvas.delete(i)
        for card in self.cards:
            for i in (card.thumb_id, *card.badge_ids):
                if i:
                    self.canvas.delete(i)
        self._list_ids = []
        self.cards = []
        self._place_chrome()

    @staticmethod
    def _thumb_box(r: Rect, label_h: int = 30) -> Rect:
        return Rect(r.left + 6, r.top + 6, r.right - 6, r.bottom - label_h)

    def _next_thumb(self):
        """썸네일을 한 장씩 채운다 (한꺼번에 하면 목록이 늦게 뜬다)."""
        if self.closed or not self.list_mode or not self._thumb_todo:
            return
        if self.tab_window is not None:  # 탭 목록 위로 썸네일이 그려지지 않게, 닫힐 때까지 잠깐 멈춤
            self.top.after(100, self._next_thumb)
            return
        card = self._thumb_todo.pop(0)
        img = None
        if self.thumbnail is not None:
            try:
                img = self.thumbnail(card.entry)
            except Exception:
                img = None
        if img is not None and card in self.cards:
            box = self._thumb_box(card.rect)
            w, h = fit_inside(img.width, img.height, box.width, box.height)
            if w and h:
                card.photo = ImageTk.PhotoImage(img.convert("RGB").resize((w, h), Image.BILINEAR))
                card.thumb_id = self.canvas.create_image(
                    (box.left + box.right) // 2, (box.top + box.bottom) // 2, image=card.photo
                )
                for i in card.badge_ids:
                    self.canvas.tag_raise(i)
        self.top.after(1, self._next_thumb)

    # ------------------------------------------------------------ 탭 목록 (브라우저)
    def _open_tabs(self, window, tabs: list):
        """브라우저 창의 탭들을 카드로 보여준다. 미리보기는 뒤에서 탭을 하나씩 넘기며 채운다."""
        self.tab_window = window
        self.tab_rows = []
        self._hover_row = None
        c = self.canvas
        m = self._local(self.monitor)
        ids = self._tab_ids
        ids.append(c.create_rectangle(m.left, m.top, m.right, m.bottom, fill="#161616", outline=""))
        ids.append(c.create_text(
            m.left + 28, m.top + 22, anchor="nw", fill="#ffffff", font=FONT_BOLD,
            text=f"{window.label} · 탭 {len(tabs)}개",
        ))
        ids.append(c.create_text(
            m.right - 28, m.top + 24, anchor="ne", fill="#bbbbbb", font=FONT,
            text="클릭: 첨부   Shift+클릭: 담기   Tab: 창 목록으로   Esc: 취소",
        ))
        minimized = bool(getattr(window, "minimized", False))
        ids.append(c.create_text(
            m.left + 28, m.top + 52, anchor="nw", fill="#999999", font=FONT_SMALL,
            text=("최소화된 창이라 미리보기 없이 제목만 보여요. 고르면 잠깐 펼쳐서 찍어요" if minimized else
                  "미리보기는 이 화면 뒤에서 탭을 하나씩 넘기며 채우고, 끝나면 원래 보던 탭으로 돌려놔요"),
        ))
        area = Rect(m.left + 28, m.top + 86, m.right - 28, m.bottom - 80)
        rects = grid_layout(len(tabs), area, label_h=34, max_w=380)
        for tab, r in zip(tabs, rects):
            shown = bool(getattr(tab, "selected", False))
            frame = c.create_rectangle(r.left, r.top, r.right, r.bottom,
                                       fill="#22324a" if shown else "#262626", outline="#444444", width=2)
            ids.append(frame)
            box = self._thumb_box(r, label_h=34)
            ids.append(c.create_text((box.left + box.right) // 2, (box.top + box.bottom) // 2,
                                     text="" if minimized else "미리보기 불러오는 중…", fill="#888888", font=FONT_SMALL))
            prefix = "● 지금 보이는 탭 · " if shown else ""
            ids.append(c.create_text(r.left + 8, r.bottom - 28, anchor="nw", fill="#eeeeee", font=FONT_SMALL,
                                     text=_clip(prefix + _tab_title(tab), r.width), width=r.width - 16))
            self.tab_rows.append(TabRow(r, tab, frame))
        if len(rects) < len(tabs):
            ids.append(c.create_text((m.left + m.right) // 2, m.bottom - 64, fill="#bbbbbb", font=FONT_SMALL,
                                     text=f"화면이 좁아 {len(tabs) - len(rects)}개는 안 보여요"))
        for item in (self.tray_bg, self.tray_id):
            c.tag_raise(item)
        for s_ in self.bag:
            self._mark_row_for(s_)
        if self.tab_previews is not None and not minimized and self.tab_rows:
            try:
                self._previewer = self.tab_previews(window, lambda i, n, img: self._preview_q.put((i, n, img)))
            except Exception:
                self._previewer = None
            self.top.after(40, self._drain_previews)

    def _drain_previews(self):
        """미리보기 스레드가 넘긴 그림을 Tk 스레드에서 카드에 붙인다."""
        if self.closed or self.tab_window is None:
            return
        from .tabmatch import pick_tab

        while True:
            try:
                index, name, img = self._preview_q.get_nowait()
            except queue.Empty:
                break
            tabs = [row.tab for row in self.tab_rows]
            tab = pick_tab(tabs, index, name)
            row = next((r for r in self.tab_rows if r.tab is tab), None)
            if row is None or img is None:
                continue
            row.image = img
            box = self._thumb_box(row.rect, label_h=34)
            w, h = fit_inside(img.width, img.height, box.width, box.height)
            if w and h:
                if row.thumb_id:
                    self.canvas.delete(row.thumb_id)
                row.photo = ImageTk.PhotoImage(img.convert("RGB").resize((w, h), Image.BILINEAR))
                row.thumb_id = self.canvas.create_image(
                    (box.left + box.right) // 2, (box.top + box.bottom) // 2, image=row.photo
                )
                for i in row.badge_ids:
                    self.canvas.tag_raise(i)
        if self._previewer is not None and not getattr(self._previewer, "is_alive", lambda: False)() \
                and self._preview_q.empty():
            return
        self.top.after(40, self._drain_previews)

    def _stop_previews(self, wait: float = 3.0):
        """미리보기를 멈추고 원래 탭으로 돌아올 때까지 기다린다 (그 뒤에 탭을 찍어야 엉키지 않는다)."""
        p = self._previewer
        self._previewer = None
        if p is None:
            return
        try:
            p.stop()
            p.join(timeout=wait)
        except Exception:
            pass

    def _close_tabs(self):
        if self.tab_window is None:
            return
        self._stop_previews()
        for i in self._tab_ids:
            self.canvas.delete(i)
        for row in self.tab_rows:
            for i in (row.thumb_id, *row.badge_ids):
                if i:
                    self.canvas.delete(i)
        self._tab_ids = []
        self.tab_rows = []
        self.tab_window = None
        self._hover_row = None
        while not self._preview_q.empty():
            self._preview_q.get_nowait()
        # 탭을 담았으면 창 목록 카드에도 표시
        for s_ in self.bag:
            self._mark_card_for(s_)

    def _row_at(self, lx: int, ly: int) -> TabRow | None:
        for row in self.tab_rows:
            if row.rect.contains(lx, ly):
                return row
        return None

    def _hover_tabs(self, lx: int, ly: int):
        row = self._row_at(lx, ly)
        if row is self._hover_row:
            return
        if self._hover_row is not None and self._hover_row in self.tab_rows:
            picked = any(s.tab is self._hover_row.tab for s in self.bag)
            self.canvas.itemconfigure(self._hover_row.frame_id, outline=ACCENT if picked else "#444444")
        self._hover_row = row
        if row is not None:
            self.canvas.itemconfigure(row.frame_id, outline="#85B7EB")

    def _mark_row_for(self, sel: Selection):
        if sel.kind != "tab" or not _same(sel.window, self.tab_window):
            return
        for row in self.tab_rows:
            if row.tab is sel.tab:
                c = self.canvas
                r = row.rect
                n = self.bag.index(sel) + 1
                c.itemconfigure(row.frame_id, outline=ACCENT, width=4)
                bg = c.create_oval(r.right - 38, r.top + 8, r.right - 8, r.top + 38, fill=ACCENT, outline="")
                tx = c.create_text(r.right - 23, r.top + 23, text=str(n), fill="#ffffff", font=FONT_BOLD)
                row.badge_ids = (bg, tx)
                return

    def _card_at(self, lx: int, ly: int) -> Card | None:
        for card in self.cards:
            if card.rect.contains(lx, ly):
                return card
        return None

    def _hover_list(self, lx: int, ly: int):
        card = self._card_at(lx, ly)
        if card is self._hover_card:
            return
        if self._hover_card is not None and self._hover_card in self.cards:
            picked = any(_same(s.window, self._hover_card.entry) for s in self.bag)
            self.canvas.itemconfigure(self._hover_card.frame_id, outline=ACCENT if picked else "#444444")
        self._hover_card = card
        if card is not None:
            self.canvas.itemconfigure(card.frame_id, outline="#85B7EB")

    def _mark_card_for(self, sel: Selection):
        for card in self.cards:
            if card.badge_ids:
                continue
            if _same(card.entry, sel.window):
                c = self.canvas
                r = card.rect
                n = self.bag.index(sel) + 1
                c.itemconfigure(card.frame_id, outline=ACCENT, width=4)
                bg = c.create_oval(r.right - 38, r.top + 8, r.right - 8, r.top + 38, fill=ACCENT, outline="")
                tx = c.create_text(r.right - 23, r.top + 23, text=str(n), fill="#ffffff", font=FONT_BOLD)
                card.badge_ids = (bg, tx)
                return

    # ------------------------------------------------------------ 마우스
    def _motion(self, e):
        if self.tab_window is not None:
            self._hover_tabs(e.x, e.y)
            return
        if self.list_mode:
            self._hover_list(e.x, e.y)
            return
        if self.press is not None:
            return
        x, y = self._screen(e)
        self._follow_cursor(x, y)
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
        if self.press is None or self.list_mode:
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

        if self.tab_window is not None:  # 탭 목록: 줄 클릭
            row = self._row_at(e.x, e.y)
            if row is None:
                return
            if any(s.kind == "tab" and _same(s.window, self.tab_window) and s.tab is row.tab for s in self.bag):
                if not shift:
                    self.finish()
                return
            w = self.tab_window
            app = w.label.split(" · ")[0]
            self._add(Selection("tab", w.rect, w, f"{app} 탭 · {_tab_title(row.tab)}", tab=row.tab, image=row.image), shift)
            return

        if self.list_mode:  # 목록에서는 카드 클릭만 (드래그 영역 없음)
            card = self._card_at(e.x, e.y)
            if card is None:
                return
            entry = card.entry
            if any(s.kind == "window" and _same(s.window, entry) for s in self.bag):
                if not shift:
                    self.finish()  # 이미 담은 카드를 Shift 없이 누르면 담은 것 전부 첨부
                return
            if not shift and self.tabs_of is not None:
                tabs = None
                try:
                    tabs = self.tabs_of(entry)
                except Exception:
                    tabs = None
                if tabs and len(tabs) >= 2:  # 브라우저 창이면 탭을 한 번 더 고른다
                    self._open_tabs(entry, tabs)
                    return
            self._add(Selection("window", entry.rect, entry, entry.label), shift)
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
        self._add(sel, shift)

    def _space(self, e):
        """Space = 지금 쓰던 창. Shift+Space = 담기만."""
        if self.closed:
            return
        if self.active is None:
            self._update_tray("지금 쓰던 창을 찾지 못했어요 · 클릭해서 골라 주세요")
            return
        a = self.active
        self._add(Selection("window", a.rect, a, a.label), bool(e.state & SHIFT_MASK))

    def _add(self, sel: Selection, shift: bool):
        """담기(shift) 또는 담고 바로 첨부. 담아 둔 게 있으면 Shift 없이 고른 것까지 함께 첨부한다."""
        if len(self.bag) >= self.max_items:
            self._update_tray(f"한 메시지에 {self.max_items}장까지예요 · Enter로 첨부하세요")
            return
        self.bag.append(sel)
        if shift:
            if self.list_mode:
                if self.tab_window is not None:
                    self._mark_row_for(sel)  # 탭 목록에서는 줄에 번호 표시
                else:
                    self._mark_card_for(sel)  # 목록에서는 카드에 번호 표시
            else:
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
        self._stop_previews()
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


def _clip(text: str, width_px: int, px_per_char: int = 11) -> str:
    """카드 폭에 맞게 이름을 자른다 (한글 기준 대략 글자당 11px)."""
    limit = max(4, (width_px - 16) // px_per_char * 2)  # 두 줄까지
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _same(a, b) -> bool:
    """같은 창인지: 목록·지금 쓰던 창이 서로 다른 객체로 같은 창을 가리킬 수 있어 hwnd로 비교."""
    if a is None or b is None:
        return False
    ha, hb = getattr(a, "hwnd", None), getattr(b, "hwnd", None)
    return a is b if ha is None or hb is None else ha == hb


def _tab_title(tab) -> str:
    from .tabmatch import display_name

    return display_name(getattr(tab, "name", "") or "")
