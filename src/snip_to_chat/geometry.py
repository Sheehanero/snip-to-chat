"""화면 좌표 계산. 모든 좌표는 물리 픽셀 기준의 '가상 화면' 좌표다.

보조 모니터가 주 모니터 왼쪽·위쪽에 있으면 좌표가 음수가 될 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar


@dataclass(frozen=True)
class Rect:
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)

    @property
    def empty(self) -> bool:
        return self.width == 0 or self.height == 0

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom

    def intersect(self, other: "Rect") -> "Rect":
        r = Rect(
            max(self.left, other.left),
            max(self.top, other.top),
            min(self.right, other.right),
            min(self.bottom, other.bottom),
        )
        return r if not r.empty else Rect(0, 0, 0, 0)

    def offset(self, dx: int, dy: int) -> "Rect":
        return Rect(self.left + dx, self.top + dy, self.right + dx, self.bottom + dy)

    def as_box(self) -> tuple[int, int, int, int]:
        return (self.left, self.top, self.right, self.bottom)


def rect_from_drag(x0: int, y0: int, x1: int, y1: int) -> Rect:
    """드래그 시작·끝점으로 사각형을 만든다. 어느 방향으로 끌어도 같은 결과."""
    return Rect(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def is_drag(x0: int, y0: int, x1: int, y1: int, threshold: int = 6) -> bool:
    """이 거리 이상 움직였으면 클릭이 아니라 드래그로 본다."""
    return abs(x1 - x0) >= threshold or abs(y1 - y0) >= threshold


T = TypeVar("T")


def hit_test(items: Sequence[T], x: int, y: int, rect_of=lambda w: w.rect) -> T | None:
    """z-순서(맨 위가 먼저) 목록에서 (x, y)를 덮고 있는 맨 위 항목을 찾는다."""
    for item in items:
        if rect_of(item).contains(x, y):
            return item
    return None


def monitor_at(monitors: Sequence[Rect], x: int, y: int) -> Rect:
    """(x, y)가 있는 모니터. 모니터 사이 빈 공간이면 가장 가까운 모니터.

    모니터 높이·위치가 서로 다르면 가상 화면 안에 어느 모니터에도 속하지 않는 빈 영역이 생긴다.
    """
    if not monitors:
        raise ValueError("모니터 목록이 비어 있어요")
    for m in monitors:
        if m.contains(x, y):
            return m

    def dist2(m: Rect) -> int:
        dx = max(m.left - x, 0, x - (m.right - 1))
        dy = max(m.top - y, 0, y - (m.bottom - 1))
        return dx * dx + dy * dy

    return min(monitors, key=dist2)


def place_in(monitor: Rect, width: int, x: int) -> int:
    """폭 width인 상자의 왼쪽 x를 모니터 안으로 밀어 넣는다 (모니터 경계를 걸치지 않게)."""
    return max(monitor.left + 4, min(x, monitor.right - width - 4))


def to_local(rect: Rect, origin_left: int, origin_top: int) -> Rect:
    """가상 화면 좌표 → 오버레이 캔버스 좌표 (캔버스 (0,0) = 가상 화면 왼쪽 위)."""
    return rect.offset(-origin_left, -origin_top)


def clamp_to(rect: Rect, bounds: Rect) -> Rect:
    return rect.intersect(bounds)


def union(rects: Iterable[Rect]) -> Rect:
    rects = [r for r in rects if not r.empty]
    if not rects:
        return Rect(0, 0, 0, 0)
    return Rect(
        min(r.left for r in rects),
        min(r.top for r in rects),
        max(r.right for r in rects),
        max(r.bottom for r in rects),
    )
