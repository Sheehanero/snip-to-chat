"""선택 화면 동작 시험 (Tk가 있는 환경에서만: Windows CI).

마우스 이벤트를 흉내 내서 듀얼 모니터 배치, 클릭·드래그·Shift 담기·Enter·Esc를 확인한다.
"""

from dataclasses import dataclass

import pytest

tk = pytest.importorskip("tkinter")
pytest.importorskip("PIL.ImageTk")

from PIL import Image  # noqa: E402

from snip_to_chat.geometry import Rect  # noqa: E402

LEFT = Rect(0, 0, 1920, 1080)
RIGHT = Rect(1920, 0, 3840, 1080)
ORIGIN = Rect(0, 0, 3840, 1080)


@dataclass
class FakeWin:
    label: str
    rect: Rect
    minimized: bool = False
    exe: str = ""


@dataclass
class Ev:
    x: int
    y: int
    state: int = 0


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:
        pytest.skip(f"화면 없음: {e}")
    r.withdraw()
    yield r
    r.destroy()


def make(root, cursor=(2500, 500), windows=None, active=None, hidden=(), thumbnail=None, start_in_list=False,
         tabs_of=None, tab_previews=None):
    from snip_to_chat.overlay import Overlay

    got = {"finish": None, "cancel": 0}
    wins = windows or [
        FakeWin("PDF · 아주 긴 제목의 지침 문서.pdf", Rect(3650, 50, 3840, 300)),  # 오른쪽 끝의 좁은 창
        FakeWin("Edge · 창 2", Rect(300, 110, 900, 600)),
        FakeWin("메모장 · 모니터 경계 근처에 붙은 이름이 긴 창", Rect(1750, 700, 1920, 900)),
        FakeWin("Chrome · 창 1", Rect(0, 0, 1000, 700)),
        FakeWin("한글 · 보고서", Rect(2000, 100, 3800, 1000)),
    ]
    ov = Overlay(
        root,
        Image.new("RGB", (ORIGIN.width, ORIGIN.height), (40, 40, 40)),
        ORIGIN,
        wins,
        lambda sels: got.__setitem__("finish", sels),
        lambda: got.__setitem__("cancel", got["cancel"] + 1),
        monitors=[LEFT, RIGHT],
        cursor=cursor,
        active=active,
        hidden_windows=hidden,
        thumbnail=thumbnail,
        start_in_list=start_in_list,
        tabs_of=tabs_of,
        tab_previews=tab_previews,
    )
    root.update_idletasks()
    return ov, got


def bbox(ov, item):
    return ov.canvas.bbox(item)


def inside(box, mon: Rect) -> bool:
    x0, y0, x1, y1 = box
    return mon.left <= x0 and x1 <= mon.right and mon.top <= y0 and y1 <= mon.bottom


def test_hint_on_cursor_monitor_and_follows(root):
    ov, _ = make(root, cursor=(2500, 500))
    assert inside(bbox(ov, ov.hint_bg), RIGHT)  # 경계(1920)에 걸치지 않고 오른쪽 모니터 안
    ov._motion(Ev(400, 400))  # 왼쪽 모니터로 이동
    root.update_idletasks()
    assert inside(bbox(ov, ov.hint_bg), LEFT)
    ov.cancel()


def test_click_selects_topmost_window(root):
    ov, got = make(root)
    ov._press(Ev(500, 300))
    ov._release(Ev(501, 301))  # 6px 미만 움직임 = 클릭
    assert got["finish"] and got["finish"][0].label == "Edge · 창 2"  # 겹친 곳은 위 창
    assert got["finish"][0].kind == "window"


def test_drag_across_monitors_makes_one_region(root):
    ov, got = make(root)
    ov._press(Ev(1800, 200))
    ov._drag(Ev(2100, 500))
    ov._release(Ev(2100, 500))
    sel = got["finish"][0]
    assert sel.kind == "region" and sel.rect == Rect(1800, 200, 2100, 500)


def test_label_stays_inside_monitor(root):
    ov, _ = make(root)
    ov._motion(Ev(3700, 200))  # 오른쪽 끝 좁은 창 위: 이름표가 창보다 넓다
    root.update_idletasks()
    assert ov.hovered.label.startswith("PDF")
    assert inside(bbox(ov, ov.label_bg), RIGHT)  # 화면 밖으로 안 나가고 왼쪽으로 당겨짐
    ov._motion(Ev(1800, 800))  # 왼쪽 모니터 경계에 붙은 창: 이름표가 오른쪽 모니터로 넘어가면 안 됨
    root.update_idletasks()
    assert ov.hovered.label.startswith("메모장")
    assert inside(bbox(ov, ov.label_bg), LEFT)
    ov.cancel()


def test_shift_collects_then_enter(root):
    ov, got = make(root)
    for x, y in ((500, 300), (2500, 500)):
        ov._press(Ev(x, y, state=0x0001))
        ov._release(Ev(x, y, state=0x0001))
    assert got["finish"] is None and len(ov.bag) == 2
    assert inside(bbox(ov, ov.tray_bg), RIGHT)  # 담기 바도 지금 모니터 안
    ov.finish()
    assert [s.label for s in got["finish"]] == ["Edge · 창 2", "한글 · 보고서"]


def test_limit_twenty(root):
    ov, got = make(root, windows=[FakeWin("창", Rect(0, 0, 3840, 1080))])
    ov.max_items = 3
    for _ in range(5):
        ov._press(Ev(100, 100, state=0x0001))
        ov._release(Ev(100, 100, state=0x0001))
    assert len(ov.bag) == 3
    ov.finish()
    assert len(got["finish"]) == 3


def test_escape_and_tiny_drag(root):
    ov, got = make(root)
    ov._press(Ev(100, 100))
    ov._drag(Ev(110, 103))
    ov._release(Ev(110, 103))  # 10×3 영역은 너무 작아서 무시
    assert got["finish"] is None and not ov.closed
    ov.cancel()
    ov.cancel()  # 두 번 불러도 한 번만
    assert got["cancel"] == 1 and got["finish"] is None


ACTIVE = FakeWin("한글 · 지금 쓰던 문서", Rect(100, 100, 1800, 1000))


def test_active_window_is_highlighted_on_open(root):
    ov, _ = make(root, cursor=(500, 500), active=ACTIVE)
    root.update_idletasks()
    assert ov.canvas.itemcget(ov.outline_id, "state") == "normal"
    assert "지금 쓰던 창" in ov.canvas.itemcget(ov.label_id, "text")
    assert inside(bbox(ov, ov.label_bg), LEFT)
    ov.cancel()


def test_space_attaches_active_window(root):
    ov, got = make(root, active=ACTIVE)
    ov._space(Ev(0, 0))
    assert [s.label for s in got["finish"]] == ["한글 · 지금 쓰던 문서"]


def test_shift_space_collects_then_click_attaches_both(root):
    ov, got = make(root, active=ACTIVE)
    ov._space(Ev(0, 0, state=0x0001))
    assert got["finish"] is None and len(ov.bag) == 1
    ov._press(Ev(2500, 500))
    ov._release(Ev(2500, 500))  # Shift 없이 고르면 담아 둔 것까지 함께 첨부
    assert [s.label for s in got["finish"]] == ["한글 · 지금 쓰던 문서", "한글 · 보고서"]


def test_space_without_active_does_nothing(root):
    ov, got = make(root, active=None)
    ov._space(Ev(0, 0))
    assert got["finish"] is None and not ov.closed
    assert "찾지 못했어요" in ov.canvas.itemcget(ov.tray_id, "text")
    ov.cancel()


def test_space_after_close_is_ignored(root):
    ov, got = make(root, active=ACTIVE)
    ov.cancel()
    ov._space(Ev(0, 0))
    assert got["finish"] is None


def test_click_on_desktop_does_nothing(root):
    ov, got = make(root, windows=[FakeWin("창", Rect(0, 0, 100, 100))])
    ov._press(Ev(1000, 1000))
    ov._release(Ev(1000, 1000))
    assert got["finish"] is None and not ov.closed
    ov.cancel()


# ---------------------------------------------------------------- 창 목록 (Tab)
COVERED = FakeWin("Edge · 크롬 뒤에 완전히 가려진 창", Rect(100, 100, 280, 280))
MINI = FakeWin("한글 · 최소화된 문서", Rect(-32000, -32000, -31840, -31972), minimized=True)


def list_windows():
    return [
        FakeWin("Chrome · 맨 앞 창", Rect(0, 0, 1000, 700)),
        COVERED,  # z-순서상 크롬 뒤: 일반 화면에서는 클릭할 수 없다
        FakeWin("한글 · 보고서", Rect(2000, 100, 3800, 1000)),
    ]


def center(card):
    return Ev((card.rect.left + card.rect.right) // 2, (card.rect.top + card.rect.bottom) // 2)


def test_covered_window_cannot_be_clicked_on_screen(root):
    ov, got = make(root, cursor=(500, 500), windows=list_windows())
    ov._press(Ev(150, 150))
    ov._release(Ev(150, 150))
    assert got["finish"][0].label == "Chrome · 맨 앞 창"  # 그래서 창 목록이 필요


def test_tab_lists_covered_and_minimized_windows(root):
    ov, _ = make(root, cursor=(500, 500), windows=list_windows(), hidden=[MINI])
    ov._toggle_list()
    root.update_idletasks()
    assert ov.list_mode
    assert [c.entry.label for c in ov.cards] == [w.label for w in list_windows()] + [MINI.label]
    assert all(inside(c.rect.as_box(), LEFT) for c in ov.cards)  # 연 모니터 안에 격자
    ov._toggle_list()  # Tab 다시 → 원래 화면
    assert not ov.list_mode and ov.cards == []
    ov.cancel()


def test_list_thumbnails_skip_minimized(root):
    calls = []

    def thumb(w):
        calls.append(w.label)
        return Image.new("RGB", (1920, 1080), (90, 120, 200))

    ov, _ = make(root, cursor=(500, 500), windows=list_windows(), hidden=[MINI], thumbnail=thumb)
    ov._toggle_list()
    for _ in range(10):
        ov._next_thumb()
    assert MINI.label not in calls and len(calls) == 3
    by_label = {c.entry.label: c for c in ov.cards}
    assert by_label[COVERED.label].thumb_id is not None
    assert by_label[MINI.label].thumb_id is None
    ov.cancel()


def test_list_click_attaches_covered_window(root):
    ov, got = make(root, cursor=(500, 500), windows=list_windows(), hidden=[MINI])
    ov._toggle_list()
    card = next(c for c in ov.cards if c.entry is COVERED)
    ov._press(center(card))
    ov._release(center(card))
    assert [s.label for s in got["finish"]] == [COVERED.label]


def test_list_shift_click_then_click_minimized(root):
    ov, got = make(root, cursor=(500, 500), windows=list_windows(), hidden=[MINI])
    ov._toggle_list()
    cov = next(c for c in ov.cards if c.entry is COVERED)
    mini = next(c for c in ov.cards if c.entry is MINI)
    e = center(cov)
    ov._press(Ev(e.x, e.y, 0x0001))
    ov._release(Ev(e.x, e.y, 0x0001))
    assert got["finish"] is None and len(ov.bag) == 1 and cov.badge_ids  # 번호 표시
    ov._press(center(mini))
    ov._release(center(mini))
    sels = got["finish"]
    assert [s.label for s in sels] == [COVERED.label, MINI.label] and sels[1].window.minimized


def test_start_in_list_and_space(root):
    ov, got = make(root, cursor=(2500, 500), windows=list_windows(), active=COVERED, start_in_list=True)
    assert ov.list_mode and all(inside(c.rect.as_box(), RIGHT) for c in ov.cards)
    ov._space(Ev(0, 0))
    assert [s.label for s in got["finish"]] == [COVERED.label]


def test_list_has_no_region_drag(root):
    ov, got = make(root, cursor=(500, 500), windows=list_windows())
    ov._toggle_list()
    ov._press(Ev(1500, 900))
    ov._drag(Ev(1700, 1000))
    ov._release(Ev(1700, 1000))
    assert got["finish"] is None and not ov.bag
    ov.cancel()


# ---------------------------------------------------------------- 탭 목록 (브라우저 창 → 탭)
@dataclass
class FakeTab:
    name: str
    selected: bool
    index: int


BROWSER = FakeWin("Chrome · 나라배움터", Rect(2000, 100, 3000, 900))
HWP = FakeWin("한글 · 보고서", Rect(0, 0, 900, 700))
TABS = [FakeTab("나라배움터 > 나의 강의실", True, 0), FakeTab("공직자통합메일", False, 1),
        FakeTab("Gemini - Memory usage - 19.1 MB", False, 2)]


def tabs_of_factory(result=TABS, boom=False):
    calls = []

    def f(w):
        calls.append(w.label)
        if boom:
            raise RuntimeError("UIA 실패")
        return result if w is BROWSER else None

    return f, calls


def card_of(ov, entry):
    return next(c for c in ov.cards if c.entry is entry)


def test_browser_card_opens_tab_list_then_background_tab(root):
    f, calls = tabs_of_factory()
    ov, got = make(root, cursor=(2500, 500), windows=[BROWSER, HWP], tabs_of=f)
    ov._toggle_list()
    e = center(card_of(ov, BROWSER))
    ov._press(e)
    ov._release(e)
    assert calls == [BROWSER.label] and ov.tab_window is BROWSER and got["finish"] is None
    assert [r.tab.name for r in ov.tab_rows] == [t.name for t in TABS]
    assert all(inside(r.rect.as_box(), RIGHT) for r in ov.tab_rows)
    row = ov.tab_rows[1]
    ov._press(center(row))
    ov._release(center(row))
    sel = got["finish"][0]
    assert sel.kind == "tab" and sel.tab is TABS[1] and sel.window is BROWSER
    assert sel.label == "Chrome 탭 · 공직자통합메일"


def test_tab_list_shift_collect_then_back_to_windows(root):
    f, _ = tabs_of_factory()
    ov, got = make(root, cursor=(500, 500), windows=[BROWSER, HWP], tabs_of=f)
    ov._toggle_list()
    e = center(card_of(ov, BROWSER))
    ov._press(e)
    ov._release(e)
    for row in ov.tab_rows[1:]:
        c = center(row)
        ov._press(Ev(c.x, c.y, 0x0001))
        ov._release(Ev(c.x, c.y, 0x0001))
    assert len(ov.bag) == 2 and all(r.badge_ids for r in ov.tab_rows[1:])
    assert "Memory usage" not in ov.bag[1].label  # 엣지 꼬리는 떼고 보여줌
    ov._toggle_list()  # Tab → 창 목록으로 (선택 화면으로 가는 게 아님)
    assert ov.list_mode and ov.tab_window is None and card_of(ov, BROWSER).badge_ids
    e = center(card_of(ov, HWP))
    ov._press(e)
    ov._release(e)
    assert [s.kind for s in got["finish"]] == ["tab", "tab", "window"]


def test_single_tab_or_failure_attaches_window_directly(root):
    for f in (tabs_of_factory(result=[FakeTab("하나", True, 0)])[0], tabs_of_factory(boom=True)[0]):
        ov, got = make(root, cursor=(500, 500), windows=[BROWSER, HWP], tabs_of=f)
        ov._toggle_list()
        e = center(card_of(ov, BROWSER))
        ov._press(e)
        ov._release(e)
        assert got["finish"][0].kind == "window" and got["finish"][0].window is BROWSER


def test_shift_on_browser_card_takes_window_without_tab_list(root):
    f, calls = tabs_of_factory()
    ov, got = make(root, cursor=(500, 500), windows=[BROWSER, HWP], tabs_of=f)
    ov._toggle_list()
    c = center(card_of(ov, BROWSER))
    ov._press(Ev(c.x, c.y, 0x0001))
    ov._release(Ev(c.x, c.y, 0x0001))
    assert calls == [] and ov.tab_window is None and ov.bag[0].kind == "window"
    ov.cancel()


def test_thumbnails_pause_under_tab_list(root):
    f, _ = tabs_of_factory()
    ov, _ = make(root, cursor=(500, 500), windows=[BROWSER, HWP], tabs_of=f,
                 thumbnail=lambda w: Image.new("RGB", (100, 60), (1, 2, 3)))
    ov._toggle_list()
    e = center(card_of(ov, BROWSER))
    ov._press(e)
    ov._release(e)
    before = len(ov._thumb_todo)
    ov._next_thumb()
    assert len(ov._thumb_todo) == before  # 탭 목록 위로 그리지 않음
    ov.cancel()



# ---------------------------------------------------------------- 탭 미리보기 · 브라우저 먼저
class FakePreviewer:
    def __init__(self, window, on_image, log):
        self.stopped = False
        self.joined = False
        self.log = log
        for t in TABS:  # 실제로는 뒤 스레드가 한 장씩 넘긴다
            on_image(t.index, t.name, Image.new("RGB", (1600, 900), (10 * (t.index + 1), 0, 0)))

    def stop(self):
        self.stopped = True
        self.log.append("stop")

    def join(self, timeout=None):
        self.joined = True
        self.log.append("join")

    def is_alive(self):
        return False


def open_tab_panel(root, log, cursor=(2500, 500)):
    f, _ = tabs_of_factory()
    made = []

    def previews(w, on_image):
        made.append(FakePreviewer(w, on_image, log))
        return made[-1]

    ov, got = make(root, cursor=cursor, windows=[BROWSER, HWP], tabs_of=f, tab_previews=previews)
    ov._toggle_list()
    e = center(card_of(ov, BROWSER))
    ov._press(e)
    ov._release(e)
    ov._drain_previews()
    return ov, got, made


def test_tab_cards_get_preview_thumbnails(root):
    log = []
    ov, _, made = open_tab_panel(root, log)
    assert len(made) == 1
    assert all(r.thumb_id and r.image is not None for r in ov.tab_rows)
    assert all(inside(r.rect.as_box(), RIGHT) for r in ov.tab_rows)
    ov.cancel()
    assert log[:2] == ["stop", "join"]  # 취소해도 원래 탭으로 돌아오게 멈추고 기다림


def test_picking_previewed_tab_reuses_image_after_stopping(root):
    log = []
    ov, got, made = open_tab_panel(root, log)
    row = ov.tab_rows[2]

    def finish(sels):
        log.append("finish")
        got["finish"] = sels

    ov.on_finish = finish
    ov._press(center(row))
    ov._release(center(row))
    sel = got["finish"][0]
    assert sel.kind == "tab" and sel.image is row.image  # 다시 찍지 않고 미리보기 그림 사용
    assert log == ["stop", "join", "finish"]  # 원래 탭으로 돌아온 뒤에 첨부 처리


def test_back_to_window_list_stops_previews(root):
    log = []
    ov, _, _ = open_tab_panel(root, log)
    ov._toggle_list()  # 탭 목록 → 창 목록
    assert ov.tab_window is None and log == ["stop", "join"]
    ov.cancel()


def test_window_list_puts_edge_and_chrome_first(root):
    edge = FakeWin("Edge · 공직자통합메일", Rect(2100, 200, 2900, 800), exe="msedge.exe")
    chrome = FakeWin("Chrome · 나라배움터", Rect(2000, 100, 3000, 900), exe="chrome.exe")
    hwp = FakeWin("한글 · 보고서", Rect(0, 0, 900, 700), exe="hwp.exe")
    edge_min = FakeWin("Edge · 최소화", Rect(-32000, -32000, -31840, -31972), minimized=True, exe="msedge.exe")
    ov, _ = make(root, windows=[hwp, chrome, edge], hidden=[edge_min])
    ov._toggle_list()
    order = [c.entry.label for c in ov.cards]
    assert order == ["Edge · 공직자통합메일", "Edge · 최소화", "Chrome · 나라배움터", "한글 · 보고서"]
    first = ov.cards[0].rect
    assert all(first.top <= c.rect.top for c in ov.cards) and first.left == min(c.rect.left for c in ov.cards)
    ov.cancel()
