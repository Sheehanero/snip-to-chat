"""브라우저 탭 처리 중 순수 로직 (Windows 없이 시험 가능)."""

from __future__ import annotations

import re

BROWSER_EXES = {"chrome.exe", "msedge.exe", "whale.exe"}


def is_browser(exe: str) -> bool:
    return (exe or "").lower() in BROWSER_EXES


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def title_shows_tab(window_title: str, tab_name: str) -> bool:
    """창 제목이 그 탭으로 바뀌었는지.

    크롬 창 제목은 '<탭 제목> - Chrome', 엣지는 '<탭 제목> - 개인 - Microsoft Edge' 같은 꼴이고,
    탭 이름에는 ' - 오디오 재생 중' 같은 꼬리가 붙기도 하며, 긴 제목은 서로 다르게 잘린다.
    그래서 탭 이름의 앞부분이 창 제목의 앞부분과 맞는지로 본다.
    """
    w, t = _norm(window_title), _norm(tab_name)
    if not w or not t:
        return False
    if len(t) > 24:
        if w.startswith(t[:24]):  # 긴 제목은 서로 다르게 잘려도 앞 24자는 같다
            return True
    elif w == t or w.startswith(t + " - "):  # 짧은 제목은 통째로 맞고 바로 뒤가 ' - 브라우저'
        return True
    main = t.split(" - ")[0]  # 탭 이름 꼬리(' - 오디오 재생 중' 등)를 뗀 본 제목
    return bool(main) and w.startswith(main + " - ")


def wait_condition(now_title: str, before_title: str, tab_name: str) -> bool:
    """탭을 바꾼 뒤 '바뀌었다'고 볼 조건: 창 제목이 바뀌었고, 새 제목이 그 탭을 가리킨다.

    제목 앞부분이 같은 탭끼리(예: 'GitHub - A', 'GitHub - B') 바꿀 때 바뀌기 전 제목으로
    성급하게 통과하지 않도록 '바뀜'도 함께 본다.
    """
    return _norm(now_title) != _norm(before_title) and title_shows_tab(now_title, tab_name)


def same_name(a: str, b: str) -> bool:
    return _norm(a) == _norm(b)


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
