"""알림 영역 아이콘 시험 (Windows 전용).

아이콘 창을 만들고, 아이콘을 왼쪽 클릭했을 때 Windows가 보내는 메시지를 흉내 내서
선택 화면 열기 요청이 큐로 들어오는지, 멈추면 스레드가 끝나는지 본다.
"""

import queue
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")


def test_tray_left_click_requests_selection(tmp_path):
    from snip_to_chat import tray

    q = queue.Queue()
    t = tray.TrayIcon(
        q,
        tooltip="snip-to-chat · 고르기 Ctrl+Alt+A " * 10,  # 128자 넘는 안내도 잘라서 넣는다
        menu_labels={1: "고르기", 2: "지금 창", 3: "폴더", 4: "끝내기"},
        allow_quit=True,
        icon_path=tmp_path / "tray.ico",
    )
    t.start()
    assert t.ready.wait(5)
    assert t.hwnd, t.error
    assert (tmp_path / "tray.ico").exists()
    print("알림 영역 표시:", t.added, t.error)  # 화면 없는 빌드 서버에선 False일 수 있어 판정에서 뺀다

    tray.SendMessageW(t.hwnd, tray.CALLBACK_MSG, 1, tray.WM_LBUTTONUP)
    assert q.get(timeout=2) == ("tray", "select")

    tray.SendMessageW(t.hwnd, tray.CALLBACK_MSG, 1, 0x0200)  # 마우스 이동은 무시
    assert q.empty()

    t.stop()
    t.join(timeout=3)
    assert not t.is_alive()


def test_icon_file_is_valid_ico(tmp_path):
    from PIL import Image

    from snip_to_chat.tray import make_icon_file

    p = make_icon_file(tmp_path / "x" / "tray.ico")
    im = Image.open(p)
    assert im.format == "ICO" and (16, 16) in im.info.get("sizes", {(16, 16)})
