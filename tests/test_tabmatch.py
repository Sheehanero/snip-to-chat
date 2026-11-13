from dataclasses import dataclass

import pytest

from snip_to_chat.tabmatch import (
    display_name, is_browser, list_order, pick_tab, same_name, title_shows_tab, wait_condition,
)


@dataclass
class T:
    name: str
    index: int


@pytest.mark.parametrize(
    "window, tab, ok",
    [
        ("나라배움터 > 나의 강의실 - Chrome", "나라배움터 > 나의 강의실", True),
        ("공직자통합메일 - 개인 - Microsoft Edge", "공직자통합메일", True),
        ("REDTAB - Google Chrome", "REDTAB", True),
        ("BLUETAB - Google Chrome", "REDTAB", False),
        ("새 탭 - Chrome", "새 탭 - 오디오 재생 중", True),  # 탭 이름의 꼬리는 무시
        ("Gemini - Chrome", "", False),
        ("", "Gemini", False),
        (
            "아주 긴 제목의 문서입니다 두 줄로 넘어가서 잘리는 경우 - Chrome",
            "아주 긴 제목의 문서입니다 두 줄로 넘어가서 잘리는 경우를 시험",
            True,
        ),
    ],
)
def test_title_shows_tab(window, tab, ok):
    assert title_shows_tab(window, tab) is ok


@pytest.mark.parametrize(
    "window, tab, ok",
    [
        # 빌드 서버의 실제 엣지에서 본 형식: 다른 탭 수가 창 제목에 붙는다
        ("BLUETAB and 1 more page - Profile 1 - Microsoft Edge", "BLUETAB", True),
        ("BLUETAB 및 페이지 1개 더 - 개인 - Microsoft Edge", "BLUETAB", True),
        ("REDTAB and 1 more page - Profile 1 - Microsoft Edge", "REDTAB - Memory usage - 19.1 MB", True),
        ("REDTABX - Chrome", "REDTAB", False),
    ],
)
def test_title_shows_tab_edge_formats(window, tab, ok):
    assert title_shows_tab(window, tab) is ok


@pytest.mark.parametrize(
    "raw, shown",
    [
        ("REDTAB - Memory usage - 19.1 MB", "REDTAB"),
        ("공직자통합메일 - 메모리 사용량 - 120 MB", "공직자통합메일"),
        ("유튜브 - 오디오 재생 중", "유튜브"),
        ("GitHub - Sheehanero/snip-to-chat", "GitHub - Sheehanero/snip-to-chat"),
        ("", "(제목 없는 탭)"),
    ],
)
def test_display_name(raw, shown):
    assert display_name(raw) == shown


def test_title_shows_tab_rejects_short_prefix_collision():
    # 탭 'a'가 창 제목 'abc - Chrome'에 성급히 맞으면 안 된다
    assert title_shows_tab("abc - Chrome", "a") is False


def test_wait_condition_needs_actual_change():
    before = "GitHub - Sheehanero/snip-to-chat - Chrome"
    # 같은 접두어 탭으로 바꿀 때: 제목이 아직 안 바뀌었으면 통과시키지 않는다
    assert wait_condition(before, before, "GitHub - Sheehanero/other") is False
    assert wait_condition("GitHub - Sheehanero/other - Chrome", before, "GitHub - Sheehanero/other") is True
    # 다른 탭으로 바뀌었으면(엉뚱한 탭) 통과 안 함
    assert wait_condition("메일 - Chrome", before, "Gemini") is False


def test_pick_tab_same_position_and_name():
    tabs = [T("메일", 0), T("Gemini", 1), T("나라배움터", 2)]
    assert pick_tab(tabs, 1, "Gemini") is tabs[1]


def test_pick_tab_after_a_tab_was_opened_before_it():
    # 목록을 연 뒤 앞에 탭이 하나 생겨 순서가 밀린 경우: 자리 말고 이름으로
    tabs = [T("새 탭", 0), T("메일", 1), T("Gemini", 2)]
    assert pick_tab(tabs, 1, "Gemini") is tabs[2]


def test_pick_tab_duplicate_names_nearest_position():
    tabs = [T("새 탭", 0), T("메일", 1), T("새 탭", 2), T("새 탭", 3)]
    assert pick_tab(tabs, 2, "새 탭") is tabs[2]
    assert pick_tab(tabs, 4, "새 탭") is tabs[3]  # 자리 이름이 달라졌으면 가장 가까운 같은 이름


def test_pick_tab_ignores_changing_status_tail():
    # 엣지는 탭 이름 끝의 메모리 사용량이 계속 바뀌고, 그 꼬리가 생겼다 없어지기도 한다
    # (빌드 서버에서 'REDTAB' → 'REDTAB - Memory usage - 19.4 MB'로 바뀐 것을 봄)
    tabs = [T("REDTAB - Memory usage - 19.4 MB", 0), T("BLUETAB", 1)]
    assert pick_tab(tabs, 0, "REDTAB - Memory usage - 19.1 MB") is tabs[0]
    assert pick_tab(tabs, 0, "REDTAB") is tabs[0]
    assert pick_tab([T("REDTAB", 0)], 0, "REDTAB - Memory usage - 19.1 MB").name == "REDTAB"
    assert pick_tab([T("유튜브", 0)], 0, "유튜브 - 오디오 재생 중").name == "유튜브"
    # 꼬리를 떼도 다른 탭은 다른 탭
    assert pick_tab(tabs, 0, "BLUETAB - Memory usage - 3 MB") is tabs[1]
    assert pick_tab(tabs, 0, "GREENTAB - Memory usage - 19.1 MB") is None


def test_same_name_ignores_status_tail_only():
    assert same_name("REDTAB", "REDTAB - Memory usage - 19.4 MB")
    assert same_name("메일 - 메모리 사용량 - 120 MB", "메일 - 메모리 사용량 - 98 MB")
    assert not same_name("GitHub - A", "GitHub - B")  # ' - 다른 말'은 꼬리가 아니다
    assert not same_name("REDTAB", "BLUETAB - Memory usage - 1 MB")


def test_pick_tab_closed_returns_none():
    assert pick_tab([T("메일", 0)], 1, "Gemini") is None
    assert pick_tab([], 0, "메일") is None


@dataclass
class W:
    label: str
    exe: str
    minimized: bool = False


def test_list_order_browsers_first_edge_then_chrome():
    hwp = W("한글", "hwp.exe")
    chrome1 = W("크롬1", "chrome.exe")
    edge = W("엣지", "msedge.exe")
    memo = W("메모장", "notepad.exe")
    chrome2 = W("크롬2", "Chrome.exe")
    edge_min = W("엣지-최소화", "msedge.exe", minimized=True)
    hwp_min = W("한글-최소화", "hwp.exe", minimized=True)
    claude = W("Claude", "claude.exe")
    # 보이는 창(z-순서) 뒤에 최소화된 창이 붙어 들어온다
    entries = [hwp, chrome1, edge, memo, chrome2, claude, edge_min, hwp_min]
    got = [e.label for e in list_order(entries)]
    assert got == ["엣지", "엣지-최소화", "크롬1", "크롬2", "한글", "메모장", "Claude", "한글-최소화"]


def test_list_order_keeps_objects_and_handles_missing_exe():
    class NoExe:
        label = "?"

    a, b = NoExe(), W("엣지", "msedge.exe")
    assert list_order([a, b]) == [b, a] and list_order([]) == []


@pytest.mark.parametrize("exe, ok", [("chrome.exe", True), ("MSEDGE.EXE", True), ("whale.exe", True), ("hwp.exe", False), ("", False)])
def test_is_browser(exe, ok):
    assert is_browser(exe) is ok
