"""Windows API 연동 (ctypes). Windows에서만 import된다.

64비트에서 핸들이 잘리지 않도록 모든 함수에 argtypes/restype을 지정한다.
"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from ctypes import wintypes as wt
from dataclasses import dataclass

if sys.platform != "win32":  # pragma: no cover
    raise ImportError("snip_to_chat.win32는 Windows 전용이에요")

import logging

from PIL import Image

from .geometry import Rect
from .imaging import is_blank, to_dib_bytes, to_png_bytes

_log = logging.getLogger(__name__)

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

LRESULT = ctypes.c_ssize_t
LONG_PTR = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t
HGLOBAL = wt.HANDLE


def _fn(dll, name, restype, *argtypes):
    f = getattr(dll, name)
    f.restype = restype
    f.argtypes = list(argtypes)
    return f


# ---------------------------------------------------------------- 구조체
class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wt.DWORD),
        ("biWidth", wt.LONG),
        ("biHeight", wt.LONG),
        ("biPlanes", wt.WORD),
        ("biBitCount", wt.WORD),
        ("biCompression", wt.DWORD),
        ("biSizeImage", wt.DWORD),
        ("biXPelsPerMeter", wt.LONG),
        ("biYPelsPerMeter", wt.LONG),
        ("biClrUsed", wt.DWORD),
        ("biClrImportant", wt.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wt.LONG),
        ("dy", wt.LONG),
        ("mouseData", wt.DWORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wt.WORD),
        ("wScan", wt.WORD),
        ("dwFlags", wt.DWORD),
        ("time", wt.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD), ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

# ---------------------------------------------------------------- 함수 선언
EnumWindows = _fn(user32, "EnumWindows", wt.BOOL, WNDENUMPROC, wt.LPARAM)
IsWindow = _fn(user32, "IsWindow", wt.BOOL, wt.HWND)
IsWindowVisible = _fn(user32, "IsWindowVisible", wt.BOOL, wt.HWND)
IsIconic = _fn(user32, "IsIconic", wt.BOOL, wt.HWND)
GetWindowTextLengthW = _fn(user32, "GetWindowTextLengthW", ctypes.c_int, wt.HWND)
GetWindowTextW = _fn(user32, "GetWindowTextW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetClassNameW = _fn(user32, "GetClassNameW", ctypes.c_int, wt.HWND, wt.LPWSTR, ctypes.c_int)
GetWindowThreadProcessId = _fn(user32, "GetWindowThreadProcessId", wt.DWORD, wt.HWND, ctypes.POINTER(wt.DWORD))
GetWindowRect = _fn(user32, "GetWindowRect", wt.BOOL, wt.HWND, ctypes.POINTER(wt.RECT))
GetWindowLongPtrW = _fn(user32, "GetWindowLongPtrW", LONG_PTR, wt.HWND, ctypes.c_int)
GetForegroundWindow = _fn(user32, "GetForegroundWindow", wt.HWND)
SetForegroundWindow = _fn(user32, "SetForegroundWindow", wt.BOOL, wt.HWND)
BringWindowToTop = _fn(user32, "BringWindowToTop", wt.BOOL, wt.HWND)
ShowWindow = _fn(user32, "ShowWindow", wt.BOOL, wt.HWND, ctypes.c_int)
AttachThreadInput = _fn(user32, "AttachThreadInput", wt.BOOL, wt.DWORD, wt.DWORD, wt.BOOL)
GetAncestor = _fn(user32, "GetAncestor", wt.HWND, wt.HWND, wt.UINT)
PrintWindow = _fn(user32, "PrintWindow", wt.BOOL, wt.HWND, wt.HDC, wt.UINT)
GetDC = _fn(user32, "GetDC", wt.HDC, wt.HWND)
ReleaseDC = _fn(user32, "ReleaseDC", ctypes.c_int, wt.HWND, wt.HDC)
RegisterHotKey = _fn(user32, "RegisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int, wt.UINT, wt.UINT)
UnregisterHotKey = _fn(user32, "UnregisterHotKey", wt.BOOL, wt.HWND, ctypes.c_int)
GetMessageW = _fn(user32, "GetMessageW", wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT)
PeekMessageW = _fn(user32, "PeekMessageW", wt.BOOL, ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT, wt.UINT)
PostThreadMessageW = _fn(user32, "PostThreadMessageW", wt.BOOL, wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM)
OpenClipboard = _fn(user32, "OpenClipboard", wt.BOOL, wt.HWND)
CloseClipboard = _fn(user32, "CloseClipboard", wt.BOOL)
EmptyClipboard = _fn(user32, "EmptyClipboard", wt.BOOL)
SetClipboardData = _fn(user32, "SetClipboardData", wt.HANDLE, wt.UINT, wt.HANDLE)
IsClipboardFormatAvailable = _fn(user32, "IsClipboardFormatAvailable", wt.BOOL, wt.UINT)
RegisterClipboardFormatW = _fn(user32, "RegisterClipboardFormatW", wt.UINT, wt.LPCWSTR)
SendInput = _fn(user32, "SendInput", wt.UINT, wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
GetAsyncKeyState = _fn(user32, "GetAsyncKeyState", wt.SHORT, ctypes.c_int)
MessageBeep = _fn(user32, "MessageBeep", wt.BOOL, wt.UINT)
GetCursorPos = _fn(user32, "GetCursorPos", wt.BOOL, ctypes.POINTER(wt.POINT))

CreateCompatibleDC = _fn(gdi32, "CreateCompatibleDC", wt.HDC, wt.HDC)
CreateCompatibleBitmap = _fn(gdi32, "CreateCompatibleBitmap", wt.HBITMAP, wt.HDC, ctypes.c_int, ctypes.c_int)
SelectObject = _fn(gdi32, "SelectObject", wt.HGDIOBJ, wt.HDC, wt.HGDIOBJ)
DeleteObject = _fn(gdi32, "DeleteObject", wt.BOOL, wt.HGDIOBJ)
DeleteDC = _fn(gdi32, "DeleteDC", wt.BOOL, wt.HDC)
GetDIBits = _fn(
    gdi32, "GetDIBits", ctypes.c_int, wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p,
    ctypes.POINTER(BITMAPINFO), wt.UINT,
)

GetCurrentThreadId = _fn(kernel32, "GetCurrentThreadId", wt.DWORD)
OpenProcess = _fn(kernel32, "OpenProcess", wt.HANDLE, wt.DWORD, wt.BOOL, wt.DWORD)
CloseHandle = _fn(kernel32, "CloseHandle", wt.BOOL, wt.HANDLE)
QueryFullProcessImageNameW = _fn(
    kernel32, "QueryFullProcessImageNameW", wt.BOOL, wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)
)
GlobalAlloc = _fn(kernel32, "GlobalAlloc", HGLOBAL, wt.UINT, ctypes.c_size_t)
GlobalLock = _fn(kernel32, "GlobalLock", ctypes.c_void_p, HGLOBAL)
GlobalUnlock = _fn(kernel32, "GlobalUnlock", wt.BOOL, HGLOBAL)
GlobalFree = _fn(kernel32, "GlobalFree", HGLOBAL, HGLOBAL)
GetConsoleWindow = _fn(kernel32, "GetConsoleWindow", wt.HWND)
GetConsoleProcessList = _fn(kernel32, "GetConsoleProcessList", wt.DWORD, ctypes.POINTER(wt.DWORD), wt.DWORD)

DwmGetWindowAttribute = _fn(dwmapi, "DwmGetWindowAttribute", ctypes.c_long, wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD)

# ---------------------------------------------------------------- 상수
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
GA_ROOT = 2
DWMWA_EXTENDED_FRAME_BOUNDS = 9
DWMWA_CLOAKED = 14
PW_RENDERFULLCONTENT = 0x00000002
DIB_RGB_COLORS = 0
BI_RGB = 0
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
PM_NOREMOVE = 0x0000
MOD_NOREPEAT = 0x4000
CF_DIB = 8
GMEM_MOVEABLE = 0x0002
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_V = 0x56
SW_HIDE, SW_RESTORE = 0, 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MB_ICONWARNING = 0x30

_SKIP_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd", "TaskManagerWindow"}

APP_LABELS = {
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "whale.exe": "Whale",
    "firefox.exe": "Firefox",
    "hwp.exe": "한글",
    "acrord32.exe": "PDF",
    "acrobat.exe": "PDF",
    "claude.exe": "Claude",
    "excel.exe": "Excel",
    "winword.exe": "Word",
    "powerpnt.exe": "PowerPoint",
    "explorer.exe": "탐색기",
}


# ---------------------------------------------------------------- DPI·콘솔
def set_dpi_awareness() -> str:
    """좌표를 물리 픽셀로 받기 위해 프로세스를 DPI 인식으로 만든다. Tk보다 먼저 호출해야 한다."""
    try:
        f = user32.SetProcessDpiAwarenessContext
        f.restype = wt.BOOL
        f.argtypes = [wt.HANDLE]
        if f(wt.HANDLE(-4)):  # PER_MONITOR_AWARE_V2
            return "per-monitor-v2"
    except AttributeError:
        pass
    try:
        if ctypes.WinDLL("shcore").SetProcessDpiAwareness(2) == 0:
            return "per-monitor"
    except (AttributeError, OSError):
        pass
    try:
        if user32.SetProcessDPIAware():
            return "system"
    except AttributeError:
        pass
    return "unaware"


def hide_console_window() -> bool:
    """Claude가 띄울 때 이 프로그램 몫으로 콘솔 창이 생겼다면 숨긴다. stdio 파이프는 그대로다.

    다른 프로그램(예: 사용자가 연 cmd)과 콘솔을 같이 쓰는 중이면 남의 창이므로 건드리지 않는다.
    """
    hwnd = GetConsoleWindow()
    if not hwnd:
        return False
    pids = (wt.DWORD * 8)()
    count = GetConsoleProcessList(pids, 8)
    if count != 1:
        return False
    ShowWindow(hwnd, SW_HIDE)
    return True


# ---------------------------------------------------------------- 창 정보
@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int
    exe: str  # 소문자 실행 파일 이름
    rect: Rect  # 화면에 보이는 테두리 (DWM extended frame bounds)

    @property
    def label(self) -> str:
        app = APP_LABELS.get(self.exe, self.exe.rsplit(".", 1)[0] if self.exe else "창")
        title = self.title if len(self.title) <= 50 else self.title[:49] + "…"
        return f"{app} · {title}" if title else app

    def to_dict(self) -> dict:
        return {
            "hwnd": self.hwnd,
            "title": self.title,
            "app": APP_LABELS.get(self.exe, self.exe),
            "exe": self.exe,
            "pid": self.pid,
            "rect": [self.rect.left, self.rect.top, self.rect.right, self.rect.bottom],
        }


def _text(hwnd) -> str:
    n = GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def _pid(hwnd) -> int:
    pid = wt.DWORD(0)
    GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


_exe_cache: dict[int, str] = {}


def exe_of_pid(pid: int) -> str:
    if pid in _exe_cache:
        return _exe_cache[pid]
    name = ""
    h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if h:
        try:
            size = wt.DWORD(1024)
            buf = ctypes.create_unicode_buffer(size.value)
            if QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.basename(buf.value).lower()
        finally:
            CloseHandle(h)
    if len(_exe_cache) > 512:
        _exe_cache.clear()
    _exe_cache[pid] = name
    return name


def _is_cloaked(hwnd) -> bool:
    val = wt.DWORD(0)
    hr = DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    return hr == 0 and val.value != 0


def window_rect(hwnd) -> Rect:
    r = wt.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    return Rect(r.left, r.top, r.right, r.bottom)


def visible_rect(hwnd) -> Rect:
    """창 그림자·투명 테두리를 뺀, 눈에 보이는 영역."""
    r = wt.RECT()
    hr = DwmGetWindowAttribute(hwnd, DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(r), ctypes.sizeof(r))
    if hr == 0:
        return Rect(r.left, r.top, r.right, r.bottom)
    return window_rect(hwnd)


def window_info(hwnd) -> WindowInfo | None:
    if not hwnd or not IsWindow(hwnd):
        return None
    pid = _pid(hwnd)
    return WindowInfo(
        hwnd=int(hwnd),
        title=_text(hwnd),
        class_name=_class(hwnd),
        pid=pid,
        exe=exe_of_pid(pid),
        rect=visible_rect(hwnd),
    )


def list_windows(exclude_pid: int | None = None) -> list[WindowInfo]:
    """화면에 보이는 최상위 창 목록. 맨 위 창이 먼저 온다 (z-순서)."""
    found: list[WindowInfo] = []

    def cb(hwnd, _lparam):
        try:
            if not IsWindowVisible(hwnd) or IsIconic(hwnd) or _is_cloaked(hwnd):
                return True
            cls = _class(hwnd)
            if cls in _SKIP_CLASSES:
                return True
            title = _text(hwnd)
            exstyle = GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            if (exstyle & WS_EX_TOOLWINDOW) and not title:
                return True
            pid = _pid(hwnd)
            if exclude_pid is not None and pid == exclude_pid:
                return True
            rect = visible_rect(hwnd)
            if rect.width < 40 or rect.height < 30:
                return True
            found.append(WindowInfo(int(hwnd), title, cls, pid, exe_of_pid(pid), rect))
        except Exception:
            pass
        return True

    EnumWindows(WNDENUMPROC(cb), 0)
    return found


def find_claude_window(exclude_pid: int | None = None) -> WindowInfo | None:
    """Claude 데스크톱 앱의 메인 창 (claude.exe 중 가장 큰 보이는 창)."""
    candidates = [
        w for w in list_windows(exclude_pid=exclude_pid) if w.exe == "claude.exe"
    ]
    if not candidates:
        # 최소화된 Claude 창도 찾아본다
        minimized: list[WindowInfo] = []

        def cb(hwnd, _lparam):
            try:
                if IsWindowVisible(hwnd) and IsIconic(hwnd):
                    pid = _pid(hwnd)
                    if exe_of_pid(pid) == "claude.exe" and _text(hwnd):
                        minimized.append(window_info(hwnd))
            except Exception:
                pass
            return True

        EnumWindows(WNDENUMPROC(cb), 0)
        candidates = [w for w in minimized if w]
        if not candidates:
            return None
        return candidates[0]
    return max(candidates, key=lambda w: w.rect.width * w.rect.height)


def foreground_window() -> WindowInfo | None:
    hwnd = GetForegroundWindow()
    if not hwnd:
        return None
    root = GetAncestor(hwnd, GA_ROOT) or hwnd
    return window_info(root)


def work_window(exclude_pid: int | None = None) -> WindowInfo | None:
    """'지금 쓰던 창': 앞에 있는 창. 단, 작업 표시줄·바탕화면·Claude·이 프로그램이면
    그 뒤에 있는 첫 번째 일반 창 (알림 영역 아이콘을 누르면 앞 창이 작업 표시줄이 되기 때문)."""
    fg = foreground_window()
    if (
        fg is not None
        and fg.class_name not in _SKIP_CLASSES
        and fg.exe != "claude.exe"
        and fg.pid != exclude_pid
        and IsWindowVisible(fg.hwnd)
        and not IsIconic(fg.hwnd)
        and fg.rect.width >= 40
    ):
        return fg
    for w in list_windows(exclude_pid=exclude_pid):
        if w.exe != "claude.exe":
            return w
    return None


# ---------------------------------------------------------------- 캡처
def _printwindow(hwnd, width: int, height: int, flags: int) -> Image.Image | None:
    screen_dc = GetDC(None)
    if not screen_dc:
        return None
    mem_dc = CreateCompatibleDC(screen_dc)
    bmp = CreateCompatibleBitmap(screen_dc, width, height)
    try:
        if not mem_dc or not bmp:
            return None
        old = SelectObject(mem_dc, bmp)
        ok = PrintWindow(hwnd, mem_dc, flags)
        SelectObject(mem_dc, old)  # GetDIBits 전에 비트맵을 DC에서 빼야 한다
        if not ok:
            return None
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = width
        bmi.bmiHeader.biHeight = -height  # 위에서 아래 순서
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        buf = ctypes.create_string_buffer(width * height * 4)
        lines = GetDIBits(mem_dc, bmp, 0, height, buf, ctypes.byref(bmi), DIB_RGB_COLORS)
        if lines != height:
            return None
        return Image.frombuffer("RGB", (width, height), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        if bmp:
            DeleteObject(bmp)
        if mem_dc:
            DeleteDC(mem_dc)
        ReleaseDC(None, screen_dc)


def grab_screen(rect: Rect | None = None) -> tuple[Image.Image, Rect]:
    """화면을 그대로 찍는다. rect가 없으면 모든 모니터를 합친 가상 화면 전체."""
    import mss

    with mss.mss() as sct:
        if rect is None:
            mon = sct.monitors[0]
            area = {"left": mon["left"], "top": mon["top"], "width": mon["width"], "height": mon["height"]}
        else:
            area = {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        shot = sct.grab(area)
        img = Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
        return img, Rect(area["left"], area["top"], area["left"] + area["width"], area["top"] + area["height"])


def list_monitors() -> list[Rect]:
    """모니터별 영역 (가상 화면 좌표, 물리 픽셀). 첫 번째가 주 모니터."""
    import mss

    with mss.mss() as sct:
        mons = [
            Rect(m["left"], m["top"], m["left"] + m["width"], m["top"] + m["height"]) for m in sct.monitors[1:]
        ]
    primary = [m for m in mons if m.left == 0 and m.top == 0]
    return primary + [m for m in mons if m not in primary]


def cursor_pos() -> tuple[int, int]:
    pt = wt.POINT()
    GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


@dataclass
class CaptureResult:
    image: Image.Image
    method: str  # printwindow-full / printwindow / screen
    blank_fallback: bool


class CaptureError(RuntimeError):
    pass


def capture_window(hwnd, screen: tuple[Image.Image, Rect] | None = None) -> CaptureResult:
    """창 하나를 찍는다. 다른 창에 가려져 있어도 그 창 내용 그대로 찍는 것이 목표다.

    PrintWindow 결과가 한 색으로만 채워져 있으면(=캡처 실패) 화면 잘라내기로 대체한다.
    screen: 미리 찍어둔 화면(선택 화면을 띄우기 직전 상태). 없으면 지금 화면을 찍는다.
    """
    if not hwnd or not IsWindow(hwnd):
        raise CaptureError("창이 이미 닫혔어요")
    if IsIconic(hwnd):
        raise CaptureError("최소화된 창은 찍을 수 없어요")
    wr = window_rect(hwnd)
    vr = visible_rect(hwnd)
    if wr.empty:
        raise CaptureError("창 크기가 0이에요")

    crop = (vr.left - wr.left, vr.top - wr.top, vr.right - wr.left, vr.bottom - wr.top)
    crop = (max(0, crop[0]), max(0, crop[1]), min(wr.width, crop[2]), min(wr.height, crop[3]))

    for flags, method in ((PW_RENDERFULLCONTENT, "printwindow-full"), (0, "printwindow")):
        img = _printwindow(hwnd, wr.width, wr.height, flags)
        if img is not None:
            img = img.crop(crop)
            if not is_blank(img):
                return CaptureResult(img, method, False)

    # 대체: 화면에 보이는 그대로 잘라낸다 (가려진 부분은 가린 창이 찍힌다)
    if screen is None:
        img, _ = grab_screen(vr)
    else:
        shot, origin = screen
        box = vr.intersect(origin).offset(-origin.left, -origin.top)
        if box.empty:
            raise CaptureError("창이 화면 밖에 있어요")
        img = shot.crop(box.as_box())
    return CaptureResult(img, "screen", True)


# ---------------------------------------------------------------- 클립보드
_PNG_FORMAT = None


def _png_format() -> int:
    global _PNG_FORMAT
    if _PNG_FORMAT is None:
        _PNG_FORMAT = RegisterClipboardFormatW("PNG")
    return _PNG_FORMAT


def _open_clipboard(owner_hwnd, tries: int = 20) -> bool:
    for _ in range(tries):
        if OpenClipboard(owner_hwnd):
            return True
        time.sleep(0.03)  # 다른 프로그램이 잡고 있으면 잠깐 기다린다
    return False


def set_clipboard_image(img: Image.Image, owner_hwnd) -> None:
    """이미지를 CF_DIB와 PNG 두 형식으로 클립보드에 넣는다.

    owner_hwnd는 이 프로세스의 창이어야 한다. NULL로 열면 SetClipboardData가 실패한다.
    """
    payloads = [(CF_DIB, to_dib_bytes(img)), (_png_format(), to_png_bytes(img))]
    if not _open_clipboard(owner_hwnd):
        raise RuntimeError("클립보드를 열 수 없어요 (다른 프로그램이 사용 중)")
    try:
        if not EmptyClipboard():
            raise RuntimeError(f"클립보드 비우기 실패 (오류 {ctypes.get_last_error()})")
        for fmt, data in payloads:
            h = GlobalAlloc(GMEM_MOVEABLE, len(data))
            if not h:
                raise MemoryError("클립보드 메모리 할당 실패")
            p = GlobalLock(h)
            if not p:
                GlobalFree(h)
                raise MemoryError("클립보드 메모리 잠금 실패")
            ctypes.memmove(p, data, len(data))
            GlobalUnlock(h)
            if not SetClipboardData(fmt, h):
                GlobalFree(h)  # 성공하면 시스템 소유가 되므로 실패할 때만 해제
                raise RuntimeError(f"클립보드에 넣기 실패 (오류 {ctypes.get_last_error()})")
    finally:
        CloseClipboard()


def clipboard_has_image() -> dict:
    return {
        "CF_DIB": bool(IsClipboardFormatAvailable(CF_DIB)),
        "PNG": bool(IsClipboardFormatAvailable(_png_format())),
    }


# ---------------------------------------------------------------- 키 입력·활성화
def _key(vk: int, up: bool) -> INPUT:
    i = INPUT()
    i.type = INPUT_KEYBOARD
    i.u.ki = KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP if up else 0, 0, 0)
    return i


def send_keys(*events: tuple[int, bool]) -> int:
    arr = (INPUT * len(events))(*[_key(vk, up) for vk, up in events])
    return SendInput(len(events), arr, ctypes.sizeof(INPUT))


def wait_modifiers_released(timeout: float = 1.5) -> bool:
    """단축키를 누른 손이 아직 Ctrl/Alt를 누르고 있으면 Ctrl+V가 Ctrl+Alt+V가 된다."""
    deadline = time.time() + timeout
    keys = (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN, VK_RWIN)
    while time.time() < deadline:
        if not any(GetAsyncKeyState(k) & 0x8000 for k in keys):
            return True
        time.sleep(0.02)
    return False


def activate(hwnd) -> str | None:
    """창을 앞으로 가져온다. 성공한 방법 이름, 실패하면 None."""
    if IsIconic(hwnd):
        ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.1)
    if SetForegroundWindow(hwnd) and _is_foreground(hwnd):
        return "direct"
    fg = GetForegroundWindow()
    cur = GetCurrentThreadId()
    fg_tid = GetWindowThreadProcessId(fg, None) if fg else 0
    if fg_tid and fg_tid != cur and AttachThreadInput(cur, fg_tid, True):
        try:
            BringWindowToTop(hwnd)
            SetForegroundWindow(hwnd)
        finally:
            AttachThreadInput(cur, fg_tid, False)
        if _is_foreground(hwnd):
            return "attach-input"
    return None


def _is_foreground(hwnd, wait: float = 0.3) -> bool:
    deadline = time.time() + wait
    while time.time() < deadline:
        fg = GetForegroundWindow()
        if fg and (int(fg) == int(hwnd) or int(GetAncestor(fg, GA_ROOT) or 0) == int(hwnd)):
            return True
        time.sleep(0.02)
    return False


@dataclass
class PasteReport:
    claude_found: bool
    activated: bool
    method: str | None
    pasted: int
    note: str = ""


def paste_into_claude(images: list[Image.Image], owner_hwnd, exclude_pid: int | None = None) -> PasteReport:
    """Claude 창을 앞으로 가져와 이미지를 한 장씩 붙여넣는다. 전송은 하지 않는다."""
    claude = find_claude_window(exclude_pid=exclude_pid)
    if claude is None:
        return PasteReport(False, False, None, 0, "Claude 데스크톱 창을 못 찾았어요")
    released = wait_modifiers_released()
    method = activate(claude.hwnd)
    if method is None:
        return PasteReport(True, False, None, 0, "Claude 창을 앞으로 가져오지 못했어요")
    time.sleep(0.15)
    pasted = 0
    note = "" if released else "단축키를 오래 누르고 있어서 수식키가 남아 있었을 수 있어요"
    for img in images:
        if not _is_foreground(claude.hwnd, wait=0.05):
            note = "붙여넣는 중에 다른 창으로 바뀌어서 멈췄어요"
            break
        set_clipboard_image(img, owner_hwnd)
        time.sleep(0.05)
        send_keys((VK_CONTROL, False), (VK_V, False), (VK_V, True), (VK_CONTROL, True))
        pasted += 1
        time.sleep(0.35)
    return PasteReport(True, True, method, pasted, note)


def beep() -> None:
    MessageBeep(MB_ICONWARNING)


# ---------------------------------------------------------------- 전역 단축키
class HotkeyThread(threading.Thread):
    """RegisterHotKey로 단축키를 등록하고 눌리면 큐에 ('hotkey', id)를 넣는다.

    키보드 전체를 가로채는 훅(키로거와 같은 방식)이 아니라, 등록한 조합만 OS가 알려주는 방식이다.
    """

    def __init__(self, bindings, out_queue, diag):
        super().__init__(name="hotkeys", daemon=True)
        self.bindings = bindings  # [(id, name, Hotkey)]
        self.out_queue = out_queue
        self.diag = diag
        self.thread_id = 0
        self.ready = threading.Event()

    def run(self):
        self.thread_id = GetCurrentThreadId()
        msg = wt.MSG()
        PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_NOREMOVE)  # 메시지 큐 생성
        registered = []
        for hk_id, name, hk in self.bindings:
            # Claude가 서버를 다시 띄울 때 이전 프로세스가 아직 단축키를 놓지 않았을 수 있어 잠깐 재시도한다
            for attempt in range(6):
                ok = RegisterHotKey(None, hk_id, hk.modifiers | MOD_NOREPEAT, hk.vk)
                err = ctypes.get_last_error()
                if ok or err != 1409:
                    break
                time.sleep(0.5)
            if ok:
                registered.append(hk_id)
                self.diag.hotkey(name, spec=hk.text, registered=True)
                _log.info("단축키 등록: %s %s", name, hk.text)
            else:
                reason = "다른 프로그램이 이미 쓰는 조합" if err == 1409 else f"Windows 오류 {err}"
                self.diag.hotkey(name, spec=hk.text, registered=False, error=reason)
                self.diag.error(f"단축키 {hk.text} 등록 실패: {reason}")
                _log.warning("단축키 등록 실패: %s %s (%s)", name, hk.text, reason)
        self.diag.set("hotkey_thread_alive", True)
        self.ready.set()
        try:
            while True:
                r = GetMessageW(ctypes.byref(msg), None, 0, 0)
                if r == 0 or r == -1:
                    break
                if msg.message == WM_HOTKEY:
                    self.diag.hotkey_fired()
                    self.out_queue.put(("hotkey", int(msg.wParam)))
        finally:
            for hk_id in registered:
                UnregisterHotKey(None, hk_id)
            self.diag.set("hotkey_thread_alive", False)

    def stop(self):
        if self.thread_id:
            PostThreadMessageW(self.thread_id, WM_QUIT, 0, 0)


def try_register(hk) -> tuple[bool, str]:
    """자체 점검용: 등록되는지만 보고 바로 해제한다."""
    ok = RegisterHotKey(None, 0xBEEF, hk.modifiers | MOD_NOREPEAT, hk.vk)
    err = ctypes.get_last_error()
    if ok:
        UnregisterHotKey(None, 0xBEEF)
        return True, "등록 가능"
    return False, "다른 프로그램이 이미 쓰는 조합" if err == 1409 else f"Windows 오류 {err}"


CreateMutexW = _fn(kernel32, "CreateMutexW", wt.HANDLE, ctypes.c_void_p, wt.BOOL, wt.LPCWSTR)
WaitForSingleObject = _fn(kernel32, "WaitForSingleObject", wt.DWORD, wt.HANDLE, wt.DWORD)
ReleaseMutex = _fn(kernel32, "ReleaseMutex", wt.BOOL, wt.HANDLE)
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0x0, 0x80, 0x102
LEADER_MUTEX = "Local\\snip-to-chat-leader"


class Leadership(threading.Thread):
    """단축키·알림 영역 아이콘을 맡을 프로세스를 하나만 고른다.

    Claude 데스크톱은 이 서버를 동시에 여러 개 띄울 수 있다(실제 PC에서 1초 간격으로 2개 확인).
    뮤텍스를 '소유'한 프로세스 하나만 맡고, 나머지는 기다리다가 맡던 쪽이 꺼지면
    (뮤텍스가 버려지면) 이어받는다. 소유권은 기다린 스레드에 붙으므로 이 스레드가 끝까지 쥔다.
    """

    def __init__(self, on_lead, name: str = LEADER_MUTEX):
        super().__init__(name="leadership", daemon=True)
        self.on_lead = on_lead
        self.handle = CreateMutexW(None, False, name)
        self.is_leader = False
        self._stop = threading.Event()

    def run(self):
        if not self.handle:  # 뮤텍스를 못 만들면 막지 않고 바로 맡는다
            self.is_leader = True
            self.on_lead()
            self._stop.wait()
            return
        while not self._stop.is_set():
            r = WaitForSingleObject(self.handle, 500)
            if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
                self.is_leader = True
                _log.info("단축키·아이콘 담당 시작%s", " (앞서 맡던 프로세스가 꺼져서 이어받음)" if r == WAIT_ABANDONED else "")
                self.on_lead()
                self._stop.wait()
                ReleaseMutex(self.handle)
                return

    def stop(self):
        self._stop.set()


def try_lead_now(name: str = LEADER_MUTEX) -> bool:
    """시험 모드용: 지금 바로 맡을 수 있으면 True (호출한 스레드가 프로세스 끝까지 소유)."""
    h = CreateMutexW(None, False, name)
    if not h:
        return True
    return WaitForSingleObject(h, 0) in (WAIT_OBJECT_0, WAIT_ABANDONED)


def input_struct_size() -> int:
    return ctypes.sizeof(INPUT)
