from dataclasses import dataclass

import pytest

from snip_to_chat.tabmatch import is_browser, pick_tab, title_shows_tab, wait_condition


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


def test_pick_tab_closed_returns_none():
    assert pick_tab([T("메일", 0)], 1, "Gemini") is None
    assert pick_tab([], 0, "메일") is None


@pytest.mark.parametrize("exe, ok", [("chrome.exe", True), ("MSEDGE.EXE", True), ("whale.exe", True), ("hwp.exe", False), ("", False)])
def test_is_browser(exe, ok):
    assert is_browser(exe) is ok
