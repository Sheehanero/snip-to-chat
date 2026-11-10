"""브라우저(크롬·엣지·웨일) 창 안의 탭 목록 읽기와 탭 캡처 (Windows UI Automation).

뒤쪽 탭은 브라우저가 그리지 않아서 그대로는 찍을 수 없다. 그래서 고른 탭을 잠깐 선택해
창 제목이 그 탭으로 바뀌고 다시 그려질 때까지 기다렸다가 찍고, 원래 보던 탭으로 되돌린다.
창을 앞으로 가져오지는 않는다 (가려진 창이면 가려진 채로 찍힌다).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from . import win32
from .tabmatch import is_browser, pick_tab, same_name, wait_condition

log = logging.getLogger(__name__)

__all__ = ["TabInfo", "TabPreviewer", "is_browser", "list_tabs", "capture_tab"]


@dataclass
class TabInfo:
    name: str
    selected: bool
    index: int
    element: object = field(default=None, repr=False, compare=False)

    @property
    def label(self) -> str:
        return self.name or "(제목 없는 탭)"


_U = None
_uia = None


def _module():
    import comtypes  # noqa: F401  (import 시 이 스레드의 COM 초기화)
    import comtypes.client

    try:
        from comtypes.gen import UIAutomationClient as U
    except ImportError:  # 개발 환경: 처음 한 번 형식 라이브러리에서 만든다 (실행 파일에는 미리 포함)
        comtypes.client.GetModule("UIAutomationCore.dll")
        from comtypes.gen import UIAutomationClient as U
    return U


def _new_client():
    """지금 스레드용 UI Automation 객체 (스레드마다 따로 만든다)."""
    import comtypes.client

    U = _module()
    return U, comtypes.client.CreateObject(U.CUIAutomation, interface=U.IUIAutomation)


def _client():
    """Tk 메인 스레드용 UI Automation 객체 (한 번 만들어 다시 쓴다)."""
    global _U, _uia
    if _uia is None:
        _U, _uia = _new_client()
    return _U, _uia


def _inside_document(el, walker, U, limit: int = 40) -> bool:
    """웹 페이지 안의 탭 위젯(role=tab)은 브라우저 탭이 아니라서 뺀다."""
    cur = el
    for _ in range(limit):
        try:
            cur = walker.GetParentElement(cur)
        except Exception:
            return False
        if not cur:
            return False
        try:
            if cur.CurrentControlType == U.UIA_DocumentControlTypeId:
                return True
        except Exception:
            return False
    return False


def _selection(el, U):
    pat = el.GetCurrentPattern(U.UIA_SelectionItemPatternId)
    if not pat:
        return None
    return pat.QueryInterface(U.IUIAutomationSelectionItemPattern)


def list_tabs(hwnd: int, client=None) -> list[TabInfo]:
    U, uia = client or _client()
    root = uia.ElementFromHandle(hwnd)
    is_item = uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, U.UIA_TabItemControlTypeId)
    # 탭 표시줄(Tab 컨트롤)을 먼저 찾고 그 안에서만 찾는다: 창 전체(웹 페이지 포함)를 뒤지면 느리다
    is_strip = uia.CreatePropertyCondition(U.UIA_ControlTypePropertyId, U.UIA_TabControlTypeId)
    walker = uia.ControlViewWalker
    scope = root
    strip = root.FindFirst(U.TreeScope_Descendants, is_strip)
    if strip and not _inside_document(strip, walker, U):
        scope = strip
    found = scope.FindAll(U.TreeScope_Descendants, is_item)
    tabs: list[TabInfo] = []
    for i in range(found.Length if found else 0):
        el = found.GetElement(i)
        if scope is root and _inside_document(el, walker, U):
            continue
        try:
            sel = _selection(el, U)
            selected = bool(sel.CurrentIsSelected) if sel else False
        except Exception:
            selected = False
        tabs.append(TabInfo(el.CurrentName or "", selected, len(tabs), el))
    return tabs


def _select(tab: TabInfo, client=None) -> None:
    U, _ = client or _client()
    sel = _selection(tab.element, U)
    if sel is not None:
        sel.Select()
        return
    pat = tab.element.GetCurrentPattern(U.UIA_LegacyIAccessiblePatternId)
    pat.QueryInterface(U.IUIAutomationLegacyIAccessiblePattern).DoDefaultAction()


def _wait_title(hwnd: int, name: str, before: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if wait_condition(win32._text(hwnd), before, name):
            return True
        time.sleep(0.05)
    return False


def capture_tab(hwnd: int, target: TabInfo, settle: float = 0.6, timeout: float = 3.0) -> win32.CaptureResult:
    """target 탭을 찍는다. 보이던 탭이면 바로, 아니면 잠깐 바꿔서 찍고 되돌린다."""
    if not hwnd or not win32.IsWindow(hwnd):
        raise win32.CaptureError("창이 이미 닫혔어요")
    was_iconic = bool(win32.IsIconic(hwnd))
    if was_iconic:
        win32.ShowWindow(hwnd, win32.SW_SHOWNOACTIVATE)
        time.sleep(0.3)
    original = None
    switched = False
    try:
        tabs = list_tabs(hwnd)  # 목록을 연 뒤 바뀌었을 수 있어 다시 읽는다
        tab = pick_tab(tabs, target.index, target.name)
        if tab is None:
            raise win32.CaptureError(f"탭을 찾지 못했어요 (닫혔을 수 있어요): {target.label}")
        original = next((t for t in tabs if t.selected), None)
        if not tab.selected:
            before = win32._text(hwnd)
            _select(tab)
            switched = True
            # 보던 탭과 이름이 같으면 제목으로는 전환을 알 수 없어 기다리지 않는다
            if not (original is not None and same_name(original.name, tab.name)):
                if not _wait_title(hwnd, tab.name, before, timeout):
                    log.warning("탭 전환 확인 시간 초과: %s", tab.name)
            time.sleep(settle)  # 내용이 다시 그려질 시간
        res = win32.capture_window(hwnd)
        method = res.method + ("+tab" if switched else "")
        return win32.CaptureResult(res.image, method, res.blank_fallback)
    finally:
        if switched and original is not None:
            try:
                _select(original)
            except Exception as e:
                log.warning("원래 탭으로 되돌리기 실패: %s", e)
        if was_iconic:
            win32.ShowWindow(hwnd, win32.SW_SHOWMINNOACTIVE)


class TabPreviewer(threading.Thread):
    """탭 목록 미리보기: 선택 화면 뒤에서 탭을 하나씩 바꿔 찍고, 끝나면(또는 멈추면) 원래 탭으로 되돌린다.

    선택 화면이 화면 전체를 덮고 있어서 사용자는 브라우저가 탭을 넘기는 걸 보지 않는다.
    Tk 화면이 멈추지 않게 별도 스레드에서 하고, 그 스레드 전용 COM(MTA)·UI Automation 객체를 쓴다.
    찍은 그림은 on_image(index, name, image)로 넘긴다 (호출은 이 스레드에서 일어난다).
    """

    def __init__(self, hwnd: int, on_image, settle: float = 0.35, timeout: float = 1.5):
        super().__init__(name="tab-preview", daemon=True)
        self.hwnd = hwnd
        self.on_image = on_image
        self.settle = settle
        self.timeout = timeout
        self._halt = threading.Event()
        self.restored = threading.Event()
        self.error = ""

    def stop(self):
        self._halt.set()

    def run(self):
        import comtypes

        comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
        try:
            self._work()
        except Exception as e:
            self.error = str(e)
            log.warning("탭 미리보기 중단: %s", e)
        finally:
            self.restored.set()
            comtypes.CoUninitialize()

    def _shot(self):
        try:
            return win32.capture_window(self.hwnd, fallback=False).image
        except win32.CaptureError:
            return None

    def _work(self):
        if not win32.IsWindow(self.hwnd) or win32.IsIconic(self.hwnd):
            return
        client = _new_client()
        tabs = list_tabs(self.hwnd, client)
        original = next((t for t in tabs if t.selected), None)
        if original is not None:  # 지금 보이는 탭은 바꾸지 않고 바로
            img = self._shot()
            if img is not None:
                self.on_image(original.index, original.name, img)
        switched = False
        try:
            for tab in tabs:
                if self._halt.is_set():
                    break
                if tab is original:
                    continue
                before = win32._text(self.hwnd)
                _select(tab, client)
                switched = True
                if not (original is not None and same_name(original.name, tab.name)):
                    deadline = time.time() + self.timeout
                    while time.time() < deadline and not self._halt.is_set():
                        if wait_condition(win32._text(self.hwnd), before, tab.name):
                            break
                        time.sleep(0.04)
                if self._halt.is_set():
                    break
                time.sleep(self.settle)
                img = self._shot()
                if img is not None:
                    self.on_image(tab.index, tab.name, img)
        finally:
            if switched and original is not None:
                try:
                    _select(original, client)
                except Exception as e:
                    log.warning("미리보기 뒤 원래 탭으로 되돌리기 실패: %s", e)
