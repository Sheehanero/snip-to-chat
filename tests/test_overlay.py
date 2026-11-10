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


def make(root, cursor=(2500, 500), windows=None, active=None):
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
