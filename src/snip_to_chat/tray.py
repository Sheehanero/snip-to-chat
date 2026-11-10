"""작업 표시줄 알림 영역 아이콘 (Windows, ctypes).

- 마우스를 올리면 단축키 안내
- 왼쪽 클릭: 선택 화면 열기
- 오른쪽 클릭: 메뉴 (고르기 · 지금 쓰던 창 · 캡처 폴더 · 끝내기)

아이콘 이벤트는 out_queue에 ("tray", 동작)으로 넣는다. 실제 처리는 Tk 메인 스레드가 한다.
의존성을 늘리지 않으려고 Shell_NotifyIcon을 직접 부른다.
"""

from __future__ import annotations

import ctypes
import logging
import threading
from ctypes import wintypes as wt
from pathlib import Path

from PIL import Image, ImageDraw

from . import win32
from .win32 import _fn, kernel32, user32

log = logging.getLogger(__name__)

shell32 = ctypes.WinDLL("shell32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.UINT),
        ("style", wt.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wt.HINSTANCE),
        ("hIcon", wt.HICON),
        ("hCursor", wt.HANDLE),
        ("hbrBackground", wt.HBRUSH),
        ("lpszMenuName", wt.LPCWSTR),
        ("lpszClassName", wt.LPCWSTR),
        ("hIconSm", wt.HICON),
    ]


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


class NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wt.DWORD),
        ("hWnd", wt.HWND),
        ("uID", wt.UINT),
        ("uFlags", wt.UINT),
        ("uCallbackMessage", wt.UINT),
        ("hIcon", wt.HICON),
        ("szTip", wt.WCHAR * 128),
        ("dwState", wt.DWORD),
        ("dwStateMask", wt.DWORD),
        ("szInfo", wt.WCHAR * 256),
        ("uVersion", wt.UINT),
        ("szInfoTitle", wt.WCHAR * 64),
        ("dwInfoFlags", wt.DWORD),
        ("guidItem", GUID),
        ("hBalloonIcon", wt.HICON),
    ]


RegisterClassExW = _fn(user32, "RegisterClassExW", wt.ATOM, ctypes.POINTER(WNDCLASSEXW))
CreateWindowExW = _fn(
    user32, "CreateWindowExW", wt.HWND, wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID,
)
DefWindowProcW = _fn(user32, "DefWindowProcW", LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
DestroyWindow = _fn(user32, "DestroyWindow", wt.BOOL, wt.HWND)
PostMessageW = _fn(user32, "PostMessageW", wt.BOOL, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
SendMessageW = _fn(user32, "SendMessageW", LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
PostQuitMessage = _fn(user32, "PostQuitMessage", None, ctypes.c_int)
TranslateMessage = _fn(user32, "TranslateMessage", wt.BOOL, ctypes.POINTER(wt.MSG))
DispatchMessageW = _fn(user32, "DispatchMessageW", LRESULT, ctypes.POINTER(wt.MSG))
RegisterWindowMessageW = _fn(user32, "RegisterWindowMessageW", wt.UINT, wt.LPCWSTR)
LoadImageW = _fn(user32, "LoadImageW", wt.HANDLE, wt.HINSTANCE, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT)
LoadIconW = _fn(user32, "LoadIconW", wt.HICON, wt.HINSTANCE, wt.LPVOID)
DestroyIcon = _fn(user32, "DestroyIcon", wt.BOOL, wt.HICON)
GetSystemMetrics = _fn(user32, "GetSystemMetrics", ctypes.c_int, ctypes.c_int)
CreatePopupMenu = _fn(user32, "CreatePopupMenu", wt.HMENU)
AppendMenuW = _fn(user32, "AppendMenuW", wt.BOOL, wt.HMENU, wt.UINT, ctypes.c_size_t, wt.LPCWSTR)
SetMenuDefaultItem = _fn(user32, "SetMenuDefaultItem", wt.BOOL, wt.HMENU, wt.UINT, wt.UINT)
TrackPopupMenu = _fn(
    user32, "TrackPopupMenu", wt.BOOL, wt.HMENU, wt.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HWND, wt.LPVOID
)
DestroyMenu = _fn(user32, "DestroyMenu", wt.BOOL, wt.HMENU)
GetModuleHandleW = _fn(kernel32, "GetModuleHandleW", wt.HMODULE, wt.LPCWSTR)
Shell_NotifyIconW = _fn(shell32, "Shell_NotifyIconW", wt.BOOL, wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW))

WM_NULL, WM_DESTROY, WM_CLOSE, WM_CONTEXTMENU = 0x0000, 0x0002, 0x0010, 0x007B
WM_LBUTTONUP, WM_RBUTTONUP = 0x0202, 0x0205
WM_APP = 0x8000
CALLBACK_MSG = WM_APP + 1
NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP = 0x1, 0x2, 0x4
MF_STRING, MF_GRAYED, MF_SEPARATOR = 0x0, 0x1, 0x800
TPM_RIGHTBUTTON, TPM_NONOTIFY, TPM_RETURNCMD = 0x2, 0x80, 0x100
IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
SM_CXSMICON, SM_CYSMICON = 49, 50
IDI_APPLICATION = 32512

CMD_SELECT, CMD_ACTIVE, CMD_FOLDER, CMD_QUIT = 1, 2, 3, 4
ACTIONS = {CMD_SELECT: "select", CMD_ACTIVE: "active", CMD_FOLDER: "folder", CMD_QUIT: "quit"}


def make_icon_file(path: Path) -> Path:
    """선택 영역 모서리 모양의 작은 아이콘을 그려 .ico로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 3, size - 3), radius=14, fill=(55, 138, 221, 255))
    w, m, L = 6, 14, 14  # 선 두께, 여백, 모서리 길이
    white = (255, 255, 255, 255)
    for x, y, dx, dy in ((m, m, 1, 1), (size - m, m, -1, 1), (m, size - m, 1, -1), (size - m, size - m, -1, -1)):
        d.line([(x, y), (x + dx * L, y)], fill=white, width=w)
        d.line([(x, y), (x, y + dy * L)], fill=white, width=w)
    img.save(path, format="ICO", sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (48, 48)])
    return path


class TrayIcon(threading.Thread):
    def __init__(self, out_queue, tooltip: str, menu_labels: dict[int, str], allow_quit: bool, icon_path: Path):
        super().__init__(name="tray", daemon=True)
        self.out_queue = out_queue
        self.tooltip = tooltip[:127]
        self.menu_labels = menu_labels
        self.allow_quit = allow_quit
        self.icon_path = icon_path
        self.hwnd = None
        self.hicon = None
        self.added = False
        self.error = ""
        self.ready = threading.Event()
        self._wndproc = WNDPROC(self._proc)  # 참조를 붙잡아 둬야 GC로 사라지지 않는다
        self._taskbar_created = RegisterWindowMessageW("TaskbarCreated")

    # ------------------------------------------------------------ 스레드
    def run(self):
        try:
            hinst = GetModuleHandleW(None)
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = self._wndproc
            wc.hInstance = hinst
            wc.lpszClassName = "snip-to-chat-tray"
            if not RegisterClassExW(ctypes.byref(wc)):
                err = ctypes.get_last_error()
                if err != 1410:  # ERROR_CLASS_ALREADY_EXISTS
                    raise OSError(f"창 클래스 등록 실패 {err}")
            # 화면에 보이지 않는 최상위 창 (TaskbarCreated 방송을 받으려면 메시지 전용 창이면 안 된다)
            self.hwnd = CreateWindowExW(0, "snip-to-chat-tray", "snip-to-chat", 0, 0, 0, 0, 0, None, None, hinst, None)
            if not self.hwnd:
                raise OSError(f"창 만들기 실패 {ctypes.get_last_error()}")
            self.hicon = self._load_icon()
            self._add()
        except Exception as e:
            self.error = str(e)
            log.warning("알림 영역 아이콘 준비 실패: %s", e)
            self.ready.set()
            return
        self.ready.set()
        msg = wt.MSG()
        while True:
            r = win32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0 or r == -1:
                break
            TranslateMessage(ctypes.byref(msg))
            DispatchMessageW(ctypes.byref(msg))
        if self.hicon:
            DestroyIcon(self.hicon)

    def stop(self):
        if self.hwnd:
            PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    # ------------------------------------------------------------ 아이콘
    def _load_icon(self):
        try:
            make_icon_file(self.icon_path)
            h = LoadImageW(
                None, str(self.icon_path), IMAGE_ICON,
                GetSystemMetrics(SM_CXSMICON), GetSystemMetrics(SM_CYSMICON), LR_LOADFROMFILE,
            )
            if h:
                return h
        except Exception as e:
            log.warning("아이콘 파일 실패, 기본 아이콘 사용: %s", e)
        return LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))

    def _nid(self) -> NOTIFYICONDATAW:
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = CALLBACK_MSG
        nid.hIcon = self.hicon
        nid.szTip = self.tooltip
        return nid

    def _add(self):
        nid = self._nid()
        self.added = bool(Shell_NotifyIconW(NIM_ADD, ctypes.byref(nid)))
        if not self.added:
            self.error = f"알림 영역에 아이콘을 못 넣음 (오류 {ctypes.get_last_error()})"
            log.warning(self.error)
        else:
            log.info("알림 영역 아이콘 표시")

    def _remove(self):
        if self.added:
            nid = self._nid()
            Shell_NotifyIconW(NIM_DELETE, ctypes.byref(nid))
            self.added = False

    # ------------------------------------------------------------ 메시지
    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == CALLBACK_MSG:
                event = lparam & 0xFFFF
                if event == WM_LBUTTONUP:
                    self.out_queue.put(("tray", "select"))
                elif event in (WM_RBUTTONUP, WM_CONTEXTMENU):
                    self._menu()
                return 0
            if msg == self._taskbar_created:  # 탐색기가 다시 시작되면 아이콘을 다시 넣는다
                self.added = False
                self._add()
                return 0
            if msg == WM_DESTROY:
                self._remove()
                PostQuitMessage(0)
                return 0
        except Exception as e:
            log.warning("알림 영역 메시지 처리 오류: %s", e)
        return DefWindowProcW(hwnd, msg, wparam, lparam)

    def _menu(self):
        menu = CreatePopupMenu()
        try:
            for cmd in (CMD_SELECT, CMD_ACTIVE, CMD_FOLDER):
                AppendMenuW(menu, MF_STRING, cmd, self.menu_labels[cmd])
            AppendMenuW(menu, MF_SEPARATOR, 0, None)
            if self.allow_quit:
                AppendMenuW(menu, MF_STRING, CMD_QUIT, self.menu_labels[CMD_QUIT])
            else:
                AppendMenuW(menu, MF_STRING | MF_GRAYED, 0, "Claude를 끄면 같이 꺼져요")
            SetMenuDefaultItem(menu, CMD_SELECT, False)
            x, y = win32.cursor_pos()
            win32.SetForegroundWindow(self.hwnd)  # 이렇게 해야 메뉴 밖을 누르면 메뉴가 닫힌다
            cmd = TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_NONOTIFY | TPM_RETURNCMD, x, y, 0, self.hwnd, None)
            PostMessageW(self.hwnd, WM_NULL, 0, 0)
            if cmd in ACTIONS:
                self.out_queue.put(("tray", ACTIONS[cmd]))
        finally:
            DestroyMenu(menu)
