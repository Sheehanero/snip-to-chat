"""브라우저 탭 처리 중 순수 로직 (Windows 없이 시험 가능)."""

from __future__ import annotations

import re

BROWSER_EXES = {"chrome.exe", "msedge.exe", "whale.exe"}


def is_browser(exe: str) -> bool:
    return (exe or "").lower() in BROWSER_EXES


# 창 목록 맨 앞(왼쪽 위)에 둘 순서: 엣지 → 크롬 → 웨일 → 나머지
_LIST_RANK = {"msedge.exe": 0, "chrome.exe": 1, "whale.exe": 2}


def list_order(entries: list) -> list:
    """창 목록 순서. 브라우저가 맨 앞, 같은 앱 안에서는 보이는 창 → 최소화된 창,
    그 안에서는 원래 순서(앞에 있던 창 먼저)를 지킨다."""
    def key(pair):
        z, e = pair
        rank = _LIST_RANK.get((getattr(e, "exe", "") or "").lower(), len(_LIST_RANK))
        return (rank, bool(getattr(e, "minimized", False)), z)

    return [e for _, e in sorted(enumerate(entries), key=key)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def title_shows_tab(window_title: str, tab_name: str) -> bool:
    """창 제목이 그 탭으로 바뀌었는지.

    크롬 창 제목은 '<탭 제목> - Chrome', 엣지는 '<탭 제목> 및 페이지 1개 더 - 개인 - Microsoft Edge'
    같은 꼴이다. 탭 이름에는 ' - Memory usage - 19.1 MB'(엣지), ' - 오디오 재생 중' 같은 꼬리가
    붙기도 하고, 긴 제목은 서로 다르게 잘린다. 그래서 꼬리를 뗀 탭 제목이 창 제목 맨 앞에
    단어 단위로 있는지 본다.
    """
    w = _norm(window_title)
    if not w or not _norm(tab_name):
        return False
    t = _norm(_STATUS_TAIL.sub("", tab_name or "")) or _norm(tab_name)
    if len(t) > 24:
        return w.startswith(t[:24])  # 긴 제목은 서로 다르게 잘려도 앞 24자는 같다
    if _word_prefix(w, t):
        return True
    main = t.split(" - ")[0]  # 모르는 꼬리가 붙은 경우: 본 제목 + ' - 브라우저'
    return bool(main) and main != t and w.startswith(main + " - ")


def _word_prefix(w: str, t: str) -> bool:
    """w가 t로 시작하고 거기서 단어가 끝나는지 ('REDTAB' 은 'REDTABX'의 앞이 아님)."""
    return w.startswith(t) and (len(w) == len(t) or not w[len(t)].isalnum())


def wait_condition(now_title: str, before_title: str, tab_name: str) -> bool:
    """탭을 바꾼 뒤 '바뀌었다'고 볼 조건: 창 제목이 바뀌었고, 새 제목이 그 탭을 가리킨다.

    제목 앞부분이 같은 탭끼리(예: 'GitHub - A', 'GitHub - B') 바꿀 때 바뀌기 전 제목으로
    성급하게 통과하지 않도록 '바뀜'도 함께 본다.
    """
    return _norm(now_title) != _norm(before_title) and title_shows_tab(now_title, tab_name)


def same_name(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


_STATUS_TAIL = re.compile(
    r"\s+-\s+(memory usage|메모리 사용량)\b.*$|\s+-\s+(audio playing|오디오 재생 중|일시중지됨|paused)\s*$",
    re.IGNORECASE,
)


def display_name(tab_name: str) -> str:
    """목록에 보여줄 탭 이름: 엣지가 붙이는 ' - Memory usage - 19.1 MB' 같은 꼬리를 뗀다."""
    name = _STATUS_TAIL.sub("", tab_name or "").strip()
    return name or "(제목 없는 탭)"


def pick_tab(tabs: list, index: int, name: str):
    """다시 읽은 탭 목록에서 고른 탭 찾기: 같은 자리·같은 이름 → 같은 이름 → None.

    목록을 연 뒤에 탭이 열리거나 닫혀 순서가 바뀌어도 엉뚱한 탭을 찍지 않게 한다.
    """
    if 0 <= index < len(tabs) and _norm(tabs[index].name) == _norm(name):
        return tabs[index]
    same = [t for t in tabs if _norm(t.name) == _norm(name)]
    if len(same) == 1:
        return same[0]
    if same:
        return min(same, key=lambda t: abs(t.index - index))
    return None
