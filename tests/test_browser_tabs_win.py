"""실제 크롬·엣지로 탭 캡처 시험 (Windows 빌드 서버 전용).

빨간 탭과 파란 탭 두 개로 브라우저를 띄우고,
1) UI Automation으로 탭 두 개를 읽는지
2) 뒤에 있는(안 보이는) 탭을 찍으면 그 탭 색이 나오는지
3) 찍은 뒤 원래 보던 탭으로 돌아오는지
4) 다른 창에 가려져 있어도 되는지
를 본다.
"""

import os
import subprocess
import sys
import time

import pytest

from snip_to_chat.tabmatch import same_name

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")

BROWSERS = {
    "chrome.exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge.exe": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
}
RED = "data:text/html,<title>REDTAB</title><body style='margin:0;background:%23ff0000'></body>"
BLUE = "data:text/html,<title>BLUETAB</title><body style='margin:0;background:%230000ff'></body>"


def _kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def _find_window(exe_name, timeout=40):
    from snip_to_chat import win32

    deadline = time.time() + timeout
    while time.time() < deadline:
        for w in win32.list_windows():
            if w.exe == exe_name and ("REDTAB" in w.title or "BLUETAB" in w.title):
                return w
        time.sleep(0.5)
    return None


def _center_color(img):
    w, h = img.size
    box = img.crop((w // 2 - 20, int(h * 0.6) - 20, w // 2 + 20, int(h * 0.6) + 20)).convert("RGB")
    px = list(box.getdata())
    return tuple(sum(p[i] for p in px) // len(px) for i in range(3))


def _is(color, target):
    r, g, b = color
    if target == "red":
        return r > 200 and g < 60 and b < 60
    return b > 200 and r < 60 and g < 60


@pytest.mark.parametrize("exe_name", list(BROWSERS))
def test_capture_background_tab_and_restore(exe_name, tmp_path):
    exe = BROWSERS[exe_name]
    if not os.path.exists(exe):
        pytest.skip(f"{exe_name} 없음")
    from snip_to_chat import browser_tabs, win32

    p = subprocess.Popen([
        exe, f"--user-data-dir={tmp_path / 'profile'}", "--no-first-run", "--no-default-browser-check",
        "--disable-sync", "--new-window", "--window-size=1000,700", "--window-position=40,40", RED, BLUE,
    ])
    try:
        win = _find_window(exe_name)
        assert win is not None, "브라우저 창을 찾지 못함"
        time.sleep(2.0)

        t0 = time.perf_counter()
        tabs = browser_tabs.list_tabs(win.hwnd)
        print(f"{exe_name} 탭 목록 {len(tabs)}개 · {time.perf_counter() - t0:.2f}초 · {[ (t.name, t.selected) for t in tabs]}")
        names = [t.name for t in tabs]
        red = next((t for t in tabs if "REDTAB" in t.name), None)
        blue = next((t for t in tabs if "BLUETAB" in t.name), None)
        assert red is not None and blue is not None, names
        assert sum(t.selected for t in tabs) == 1
        shown, hidden = (red, blue) if red.selected else (blue, red)
        hidden_color = "blue" if hidden is blue else "red"
        shown_color = "red" if hidden_color == "blue" else "blue"

        # 보이는 탭: 바꾸지 않고 바로
        res = browser_tabs.capture_tab(win.hwnd, shown)
        assert _is(_center_color(res.image), shown_color), _center_color(res.image)

        # 안 보이는 탭: 잠깐 바꿔서 찍고 되돌림
        t0 = time.perf_counter()
        res = browser_tabs.capture_tab(win.hwnd, hidden)
        print(f"뒤쪽 탭 캡처 {time.perf_counter() - t0:.2f}초 · 방식 {res.method} · 색 {_center_color(res.image)}")
        assert _is(_center_color(res.image), hidden_color), _center_color(res.image)
        assert res.method.endswith("+tab")
        time.sleep(0.5)
        after = browser_tabs.list_tabs(win.hwnd)
        now = next(t for t in after if t.selected)
        assert same_name(now.name, shown.name), f"원래 보던 탭으로 돌아오지 않음: {shown.name} → {now.name}"
        assert shown.name.split()[0] in win32._text(win.hwnd)
    finally:
        _kill_tree(p.pid)


def test_capture_tab_of_covered_window(tmp_path):
    """다른 창에 완전히 가려진 브라우저 창의 뒤쪽 탭도 찍히는지."""
    exe = BROWSERS["chrome.exe"]
    if not os.path.exists(exe):
        pytest.skip("chrome 없음")
    from snip_to_chat import browser_tabs

    p = subprocess.Popen([
        exe, f"--user-data-dir={tmp_path / 'profile'}", "--no-first-run", "--no-default-browser-check",
        "--new-window", "--window-size=800,600", "--window-position=60,60", RED, BLUE,
    ])
    cover = subprocess.Popen([
        exe, f"--user-data-dir={tmp_path / 'profile2'}", "--no-first-run", "--no-default-browser-check",
        "--new-window", "--window-size=1100,900", "--window-position=0,0",
        "data:text/html,<title>COVER</title><body style='background:%2300ff00'></body>",
    ])
    try:
        win = _find_window("chrome.exe")
        assert win is not None
        time.sleep(3.0)  # 덮는 창이 위로 올라올 시간
        tabs = browser_tabs.list_tabs(win.hwnd)
        hidden = next(t for t in tabs if not t.selected)
        color = "red" if "REDTAB" in hidden.name else "blue"
        res = browser_tabs.capture_tab(win.hwnd, hidden)
        print(f"가려진 창 뒤쪽 탭: 방식 {res.method} · 색 {_center_color(res.image)}")
        assert _is(_center_color(res.image), color), _center_color(res.image)
    finally:
        _kill_tree(p.pid)
        _kill_tree(cover.pid)


GREEN = "data:text/html,<title>GREENTAB</title><body style='margin:0;background:%2300ff00'></body>"


def _is_green(c):
    r, g, b = c
    return g > 200 and r < 60 and b < 60


@pytest.mark.parametrize("exe_name", list(BROWSERS))
def test_previewer_shows_every_tab_and_restores(exe_name, tmp_path):
    """탭 미리보기: 탭 3개를 모두 찍고(각자 제 색), 끝나면 원래 보던 탭으로 돌아오는지."""
    exe = BROWSERS[exe_name]
    if not os.path.exists(exe):
        pytest.skip(f"{exe_name} 없음")
    from snip_to_chat import browser_tabs

    p = subprocess.Popen([
        exe, f"--user-data-dir={tmp_path / 'profile'}", "--no-first-run", "--no-default-browser-check",
        "--disable-sync", "--new-window", "--window-size=900,650", "--window-position=80,80", RED, BLUE, GREEN,
    ])
    try:
        win = _find_window(exe_name)
        assert win is not None
        time.sleep(2.0)
        before = [t for t in browser_tabs.list_tabs(win.hwnd) if t.selected][0].name

        got = {}
        t0 = time.perf_counter()
        pv = browser_tabs.TabPreviewer(win.hwnd, lambda i, n, img: got.__setitem__(n, img))
        pv.start()
        pv.join(timeout=20)
        took = time.perf_counter() - t0
        print(f"{exe_name} 미리보기 {len(got)}장 · {took:.2f}초 · 오류 '{pv.error}' · "
              + ", ".join(f"{n[:8]}={_center_color(im)}" for n, im in got.items()))
        assert not pv.is_alive() and pv.restored.is_set() and not pv.error
        colors = {("REDTAB", "red"), ("BLUETAB", "blue"), ("GREENTAB", "green")}
        for key, color in colors:
            name = next((n for n in got if key in n), None)
            assert name is not None, f"{key} 미리보기 없음: {list(got)}"
            c = _center_color(got[name])
            assert (_is_green(c) if color == "green" else _is(c, color)), (key, c)
        time.sleep(0.4)
        now = [t for t in browser_tabs.list_tabs(win.hwnd) if t.selected][0].name
        assert same_name(now, before), f"원래 탭으로 안 돌아옴: {before} → {now}"
    finally:
        _kill_tree(p.pid)


def test_previewer_stop_midway_still_restores(tmp_path):
    exe = BROWSERS["chrome.exe"]
    if not os.path.exists(exe):
        pytest.skip("chrome 없음")
    from snip_to_chat import browser_tabs

    p = subprocess.Popen([
        exe, f"--user-data-dir={tmp_path / 'profile'}", "--no-first-run", "--no-default-browser-check",
        "--new-window", RED, BLUE, GREEN, RED.replace("REDTAB", "REDTWO"),
    ])
    try:
        win = _find_window("chrome.exe")
        assert win is not None
        time.sleep(2.0)
        before = [t for t in browser_tabs.list_tabs(win.hwnd) if t.selected][0].name
        got = []
        pv = browser_tabs.TabPreviewer(win.hwnd, lambda i, n, img: got.append(n))
        pv.start()
        time.sleep(0.9)  # 한두 장 찍는 중에 사용자가 골랐다고 치고 멈춤
        pv.stop()
        pv.join(timeout=5)
        assert not pv.is_alive() and pv.restored.is_set()
        time.sleep(0.4)
        now = [t for t in browser_tabs.list_tabs(win.hwnd) if t.selected][0].name
        print(f"중간 멈춤: {len(got)}장 찍고 멈춤 · 복귀 {before} → {now}")
        assert same_name(now, before), f"원래 탭으로 안 돌아옴: {before} → {now}"
    finally:
        _kill_tree(p.pid)
