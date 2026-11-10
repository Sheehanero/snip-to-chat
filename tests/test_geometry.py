from dataclasses import dataclass

import pytest

from snip_to_chat.geometry import (
    Rect,
    fit_inside,
    grid_layout,
    hit_test,
    is_drag,
    monitor_at,
    place_in,
    rect_from_drag,
    rows_layout,
    to_local,
)


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


LEFT_PRIMARY = Rect(0, 0, 1920, 1080)
RIGHT = Rect(1920, 0, 3840, 1080)


def test_monitor_at_side_by_side():
    mons = [LEFT_PRIMARY, RIGHT]
    assert monitor_at(mons, 100, 100) == LEFT_PRIMARY
    assert monitor_at(mons, 1919, 500) == LEFT_PRIMARY  # 경계 바로 왼쪽
    assert monitor_at(mons, 1920, 500) == RIGHT  # 경계는 오른쪽 모니터
    assert monitor_at(mons, 3839, 1079) == RIGHT


def test_monitor_at_secondary_left_negative():
    left = Rect(-1920, 0, 0, 1080)
    mons = [Rect(0, 0, 1920, 1080), left]
    assert monitor_at(mons, -5, 10) == left


def test_monitor_at_gap_picks_nearest():
    # 큰 모니터(1440) 옆에 작은 모니터(1080)를 위쪽 정렬: 오른쪽 아래가 빈 공간
    big = Rect(0, 0, 2560, 1440)
    small = Rect(2560, 0, 4480, 1080)
    assert monitor_at([big, small], 3000, 1300) == small  # 빈 공간 → 바로 위 작은 모니터
    assert monitor_at([big, small], 2600, 1430) == big  # 큰 모니터 오른쪽 끝이 더 가까움


def test_hint_center_is_not_on_the_seam():
    # 예전처럼 가상 화면 가운데(1920)에 두면 두 모니터에 걸친다
    mons = [LEFT_PRIMARY, RIGHT]
    m = monitor_at(mons, 2500, 300)
    cx = (m.left + m.right) // 2
    assert m.left < cx - 300 and cx + 300 < m.right


def test_place_in_keeps_box_inside_monitor():
    assert place_in(RIGHT, 400, 3700) == 3840 - 400 - 4  # 오른쪽 끝에서 안으로
    assert place_in(RIGHT, 400, 1800) == 1920 + 4  # 왼쪽 모니터로 넘어가지 않게
    assert place_in(RIGHT, 400, 2500) == 2500


def _no_overlap(rects):
    for i, a in enumerate(rects):
        for b in rects[i + 1:]:
            if not a.intersect(b).empty:
                return False
    return True


def _all_inside(rects, area):
    return all(r.intersect(area) == r for r in rects)


@pytest.mark.parametrize("n", [1, 2, 7, 20, 23, 40])
def test_grid_fits_all_on_one_monitor(n):
    area = Rect(1944, 60, 3816, 1010)  # 오른쪽 모니터 안쪽 (여백 뺀 영역)
    cards = grid_layout(n, area)
    assert len(cards) == n
    assert _no_overlap(cards) and _all_inside(cards, area)
    assert len({(c.width, c.height) for c in cards}) == 1  # 크기 통일


def test_grid_prefers_big_cards_when_few():
    area = Rect(0, 0, 1872, 950)
    assert grid_layout(1, area)[0].width == 420  # 최대 폭
    assert grid_layout(20, area)[0].width >= 250  # 20개여도 알아볼 만한 크기


def test_grid_truncates_when_too_many():
    area = Rect(0, 0, 800, 400)
    cards = grid_layout(500, area)
    assert 0 < len(cards) < 500
    assert _no_overlap(cards) and _all_inside(cards, area)


def test_grid_empty_cases():
    assert grid_layout(0, Rect(0, 0, 100, 100)) == []
    assert grid_layout(5, Rect(0, 0, 0, 0)) == []
    assert grid_layout(5, Rect(0, 0, 1000, 50)) == []  # 카드 한 장도 안 들어가는 높이


@pytest.mark.parametrize("n", [1, 2, 18, 19, 40, 60])
def test_rows_layout_fits_and_orders_top_to_bottom(n):
    area = Rect(28, 120, 1892, 1000)
    rows = rows_layout(n, area)
    assert len(rows) == n
    assert _no_overlap(rows) and _all_inside(rows, area)
    if n >= 2:
        assert rows[1].top > rows[0].top and rows[1].left == rows[0].left  # 아래로 먼저


def test_rows_layout_truncates_and_empty():
    area = Rect(0, 0, 500, 200)
    rows = rows_layout(100, area)
    assert 0 < len(rows) < 100 and _no_overlap(rows) and _all_inside(rows, area)
    assert rows_layout(0, area) == [] and rows_layout(3, Rect(0, 0, 500, 20)) == []


@pytest.mark.parametrize(
    "src, box, expected",
    [((1920, 1080), (300, 200), (300, 168)), ((500, 1000), (300, 200), (100, 200)), ((0, 10), (5, 5), (0, 0))],
)
def test_fit_inside(src, box, expected):
    assert fit_inside(*src, *box) == expected


def test_intersect_disjoint_is_empty():
    assert Rect(0, 0, 10, 10).intersect(Rect(20, 20, 30, 30)).empty
