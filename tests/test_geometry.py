from dataclasses import dataclass

from snip_to_chat.geometry import Rect, hit_test, is_drag, rect_from_drag, to_local


@dataclass
class W:
    name: str
    rect: Rect


def test_drag_any_direction_same_rect():
    a = rect_from_drag(10, 20, 110, 220)
    b = rect_from_drag(110, 220, 10, 20)  # 오른쪽 아래 → 왼쪽 위
    c = rect_from_drag(110, 20, 10, 220)
    assert a == b == c == Rect(10, 20, 110, 220)


def test_negative_coordinates_left_monitor():
    # 보조 모니터가 주 모니터 왼쪽에 있으면 좌표가 음수
    r = rect_from_drag(-1900, 100, -1500, 400)
    assert (r.width, r.height) == (400, 300)
    local = to_local(r, origin_left=-1920, origin_top=0)
    assert local == Rect(20, 100, 420, 400)


def test_click_vs_drag_threshold():
    assert not is_drag(100, 100, 103, 104)
    assert is_drag(100, 100, 106, 100)
    assert is_drag(100, 100, 100, 94)


def test_hit_test_respects_z_order():
    top = W("edge2", Rect(300, 110, 510, 240))
    below = W("chrome1", Rect(0, 0, 400, 300))
    z = [top, below]  # 맨 위가 먼저
    assert hit_test(z, 350, 150).name == "edge2"  # 겹친 곳은 위 창
    assert hit_test(z, 50, 50).name == "chrome1"  # 아래 창만 있는 곳
    assert hit_test(z, 600, 600) is None  # 바탕화면


def test_right_and_bottom_edges_are_exclusive():
    r = Rect(0, 0, 100, 100)
    assert r.contains(0, 0) and r.contains(99, 99)
    assert not r.contains(100, 50) and not r.contains(50, 100)


def test_intersect_disjoint_is_empty():
    assert Rect(0, 0, 10, 10).intersect(Rect(20, 20, 30, 30)).empty
