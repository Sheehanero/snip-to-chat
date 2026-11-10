"""앱 조립: 단축키 → 선택 화면 → 캡처 → 저장 → Claude 창에 붙여넣기, 그리고 MCP 도구."""

from __future__ import annotations

import json
import logging
import os
import queue
import sys
import threading
import time
import tkinter as tk
from collections import deque
from dataclasses import dataclass

from PIL import Image

from . import APP_NAME, __version__, win32
from .config import MAX_IMAGES_PER_MESSAGE, Settings
from .diag import Diagnostics, summarize
from .geometry import Rect, monitor_at
from .imaging import to_mcp_image_content
from .mcp_server import McpServer, Tool, ToolFailure, text
from .overlay import Overlay, Selection
from .storage import CaptureStore, recent_capture_files, resolve_capture_dir

log = logging.getLogger(__name__)

HOTKEY_SELECT = 1
HOTKEY_ACTIVE = 2

INSTRUCTIONS = (
    "snip-to-chat은 사용자가 단축키로 고른 창·영역 캡처를 Claude 데스크톱 입력칸에 직접 첨부한다. "
    "사용자가 방금 캡처한 걸 다시 보라고 하면 get_recent_captures를, "
    "특정 창을 직접 보라고 하면 list_windows로 찾은 뒤 capture_window를 쓴다. "
    "작동 상태를 물으면 diagnostics를 쓴다."
)


@dataclass
class Captured:
    image: Image.Image
    kind: str  # window / region / active / tool
    label: str
    method: str


class App:
    def __init__(self, settings: Settings, mode: str, diag: Diagnostics, stdout=None):
        self.settings = settings
        self.mode = mode
        self.diag = diag
        self.stdout = stdout  # MCP 모드에서 쓸 진짜 stdout
        self.events: queue.Queue = queue.Queue()
        self.overlay: Overlay | None = None
        self.recent: deque[dict] = deque(maxlen=MAX_IMAGES_PER_MESSAGE)
        self.recent_lock = threading.Lock()
        self.pid = os.getpid()
        directory = resolve_capture_dir(settings.capture_dir_override)
        self.store = CaptureStore(directory)
        self.diag.set("storage", {"dir": str(directory), "safe": self.store.safe, "reason": self.store.reason})
        if not self.store.safe:
            self.diag.error(self.store.reason)

    # ================================================================ 실행
    def run(self) -> int:
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title(APP_NAME)
        self.root.update_idletasks()
        try:
            self.owner_hwnd = int(self.root.wm_frame(), 16)
        except (ValueError, tk.TclError):
            self.owner_hwnd = self.root.winfo_id()

        self.hotkeys = None
        self.tray = None
        self.leadership = None
        if self.mode == "standalone":
            # 시험 모드는 시작 전에 이미 담당을 확보했다 (__main__의 try_lead_now)
            self.diag.set("role", "담당")
            self._start_lead_duties()
        else:
            # Claude가 여러 개 띄울 수 있으니 하나만 단축키·아이콘을 맡고 나머지는 대기
            self.diag.set("role", "대기 (다른 snip-to-chat이 단축키·아이콘 담당)")
            self.leadership = win32.Leadership(on_lead=lambda: self.events.put(("lead", None)))
            self.leadership.start()

        if self.mode == "mcp":
            server = McpServer(APP_NAME, __version__, self.tools(), INSTRUCTIONS)
            t = threading.Thread(target=self._serve, args=(server,), name="mcp", daemon=True)
            t.start()

        self.root.after(30, self._pump)
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            pass
        finally:
            if self.hotkeys is not None:
                self.hotkeys.stop()
                self.hotkeys.join(timeout=2)
            if self.tray is not None:
                self.tray.stop()
                self.tray.join(timeout=2)
            if self.leadership is not None:
                self.leadership.stop()
                self.leadership.join(timeout=2)
        return 0

    def _start_lead_duties(self):
        """단축키 감시와 알림 영역 아이콘을 켠다 (담당 프로세스 하나만)."""
        if self.hotkeys is not None:
            return
        self.diag.set("role", "담당")
        s = self.settings
        self.hotkeys = win32.HotkeyThread(
            [(HOTKEY_SELECT, "선택 화면", s.select_hotkey), (HOTKEY_ACTIVE, "활성 창", s.active_hotkey)],
            self.events,
            self.diag,
        )
        self.hotkeys.start()
        self.hotkeys.ready.wait(5)

        try:
            from .tray import CMD_ACTIVE, CMD_FOLDER, CMD_LIST, CMD_QUIT, CMD_SELECT, TrayIcon

            self.tray = TrayIcon(
                self.events,
                tooltip=f"snip-to-chat · 고르기 {s.select_hotkey.text} (Space=지금 창) · 지금 창 {s.active_hotkey.text}",
                menu_labels={
                    CMD_SELECT: f"창·영역 고르기\t{s.select_hotkey.text}",
                    CMD_LIST: f"창 목록에서 고르기 (가려진 창)\t{s.select_hotkey.text} → Tab",
                    CMD_ACTIVE: f"지금 쓰던 창 찍기\t{s.active_hotkey.text}",
                    CMD_FOLDER: "캡처 폴더 열기",
                    CMD_QUIT: "끝내기",
                },
                allow_quit=self.mode == "standalone",
                icon_path=self.store.directory.parent / "tray.ico",
            )
            self.tray.start()
            self.tray.ready.wait(3)
            self.diag.set("tray", {"shown": self.tray.added, "error": self.tray.error})
        except Exception as e:
            log.warning("알림 영역 아이콘 없이 계속: %s", e)
            self.diag.set("tray", {"shown": False, "error": str(e)})

    def _serve(self, server: McpServer):
        try:
            server.serve(sys.stdin.buffer, self.stdout)
        except Exception as e:
            log.exception("MCP 루프 오류")
            self.diag.error(f"MCP 루프 오류: {e}")
        finally:
            # stdin이 닫혔다 = Claude 앱이 종료됐다. 같이 끝난다.
            self.events.put(("quit", None))

    def _pump(self):
        try:
            while True:
                kind, arg = self.events.get_nowait()
                if kind == "quit":
                    self.root.quit()
                    return
                if kind == "lead":
                    self._safe(self._start_lead_duties)
                if kind == "hotkey" and arg == HOTKEY_SELECT:
                    self.note(f"단축키 {self.settings.select_hotkey.text}: 선택 화면")
                    self._safe(self.open_overlay)
                elif kind == "hotkey" and arg == HOTKEY_ACTIVE:
                    self.note(f"단축키 {self.settings.active_hotkey.text}: 활성 창 찍기")
                    self._safe(self.capture_active)
                elif kind == "tray":
                    self.note(f"알림 영역 아이콘: {arg}")
                    if arg == "select":
                        self._safe(self.open_overlay)
                    elif arg == "active":
                        self._safe(self.capture_active)
                    elif arg == "list":
                        self._safe(self.open_list)
                    elif arg == "folder":
                        self._safe(self.open_folder)
                    elif arg == "quit" and self.mode == "standalone":
                        self.root.quit()
                        return
        except queue.Empty:
            pass
        self.root.after(30, self._pump)

    def _safe(self, fn):
        try:
            fn()
        except Exception as e:
            log.exception("처리 중 오류")
            self.diag.error(f"{fn.__name__}: {e}")
            self.toast(f"오류: {e}")

    def note(self, message: str) -> None:
        """작동 기록: 로그 파일에 남기고, 시험 모드에서는 콘솔에도 보여준다."""
        log.info(message)
        if self.mode == "standalone":
            print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)

    # ================================================================ 선택 화면
    def open_folder(self):
        d = self.store.directory
        d.mkdir(parents=True, exist_ok=True)
        os.startfile(str(d))

    def open_list(self):
        self.open_overlay(start_in_list=True)

    def _thumbnail(self, w):
        """창 목록 썸네일: 가려진 창도 PrintWindow로 내용 그대로. 최소화된 창은 목록에서 고를 때 찍는다."""
        if getattr(w, "minimized", False):
            return None
        try:
            return win32.capture_window(w.hwnd).image
        except win32.CaptureError:
            return None

    def open_overlay(self, start_in_list: bool = False):
        if self.overlay is not None and not self.overlay.closed:
            return
        active = win32.work_window(exclude_pid=self.pid)  # 화면을 얼리기 전에, 지금 쓰던 창부터 기억
        shot, origin = win32.grab_screen()
        windows = win32.list_windows(exclude_pid=self.pid)
        hidden = win32.list_minimized_windows(exclude_pid=self.pid)
        monitors = win32.list_monitors()
        cursor = win32.cursor_pos()
        self.note(
            f"선택 화면 열림: 모니터 {len(monitors)}대 "
            + " / ".join(f"{m.width}×{m.height}@({m.left},{m.top})" for m in monitors)
            + f", 고를 수 있는 창 {len(windows)}개(최소화 {len(hidden)}개 별도), 지금 쓰던 창: {active.label if active else '없음'}"
            + (" · 창 목록으로 시작" if start_in_list else "")
        )

        def finished(selections: list[Selection]):
            self.overlay = None
            self.note(f"선택 {len(selections)}개: " + ", ".join(s.label for s in selections))
            items = [self._capture_selection(sel, shot, origin) for sel in selections]
            self.deliver([i for i in items if i is not None])

        def cancelled():
            self.overlay = None
            self.note("선택 화면 취소")

        self.overlay = Overlay(
            self.root, shot, origin, windows, finished, cancelled,
            max_items=MAX_IMAGES_PER_MESSAGE, monitors=monitors, cursor=cursor, active=active,
            hidden_windows=hidden, thumbnail=self._thumbnail, start_in_list=start_in_list,
        )

    def _capture_selection(self, sel: Selection, shot: Image.Image, origin: Rect) -> Captured | None:
        if sel.kind == "region":
            box = sel.rect.intersect(origin).offset(-origin.left, -origin.top)
            if box.empty:
                return None
            img = shot.crop(box.as_box())
            self.diag.capture("region", "screen", img.size, False)
            return Captured(img, "region", sel.label, "screen")
        try:
            if getattr(sel.window, "minimized", False) or win32.IsIconic(sel.window.hwnd):
                res = win32.capture_minimized(sel.window.hwnd)  # 잠깐 펼쳐서 찍고 다시 내림
            else:
                res = win32.capture_window(sel.window.hwnd, screen=(shot, origin))
        except win32.CaptureError as e:
            self.diag.error(f"창 캡처 실패({sel.label}): {e}")
            box = sel.rect.intersect(origin).offset(-origin.left, -origin.top)
            if box.empty:
                return None
            img = shot.crop(box.as_box())
            self.diag.capture("window", "screen", img.size, True)
            return Captured(img, "window", sel.label, "screen")
        self.diag.capture("window", res.method, res.image.size, res.blank_fallback)
        return Captured(res.image, "window", sel.label, res.method)

    # ================================================================ 활성 창
    def capture_active(self):
        # 앞 창이 Claude·작업 표시줄이면 그 뒤의 창 (알림 영역 메뉴에서 눌렀을 때도 같은 규칙)
        info = win32.work_window(exclude_pid=self.pid)
        if info is None:
            self.note("지금 쓰던 창 없음")
            win32.beep()
            self.toast("찍을 창이 없어요")
            return
        res = win32.capture_window(info.hwnd)
        self.diag.capture("active", res.method, res.image.size, res.blank_fallback)
        self.deliver([Captured(res.image, "active", info.label, res.method)])

    # ================================================================ 전달
    def deliver(self, items: list[Captured]):
        if not items:
            return
        for it in items:
            saved = self.store.save(it.image, it.kind)
            self.diag.set("storage", {"dir": str(self.store.directory), "safe": self.store.safe, "reason": self.store.reason})
            self.note(
                f"캡처: {it.label} · {it.image.width}×{it.image.height} · {it.method} · "
                + (f"저장 {saved.path.name}" if saved.path else f"저장 안 함({saved.reason})")
            )
            with self.recent_lock:
                self.recent.appendleft(
                    {
                        "at": time.strftime("%H:%M:%S"),
                        "label": it.label,
                        "kind": it.kind,
                        "method": it.method,
                        "path": str(saved.path) if saved.path else None,
                        "image": it.image,
                    }
                )
        if not self.settings.auto_paste:
            self.toast(f"{len(items)}장 캡처했어요 (자동 붙여넣기 꺼짐)")
            return
        report = win32.paste_into_claude([it.image for it in items], self.owner_hwnd, exclude_pid=self.pid)
        self.diag.set(
            "activation",
            {
                "at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "claude_found": report.claude_found,
                "activated": report.activated,
                "method": report.method,
                "pasted": report.pasted,
                "requested": len(items),
                "note": report.note,
            },
        )
        self.note(
            f"붙여넣기: Claude 창 {'찾음' if report.claude_found else '못 찾음'}, "
            f"앞으로 가져오기 {report.method or '실패'}, {report.pasted}/{len(items)}장"
            + (f" · {report.note}" if report.note else "")
        )
        if not report.activated:
            self.diag.error(report.note)
            win32.beep()
            self.toast(report.note + " · 캡처는 저장돼 있어요")
        elif report.note:
            self.toast(report.note)

    # ================================================================ 알림
    def toast(self, message: str, ms: int = 2600):
        try:
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            lbl = tk.Label(t, text=message, font=("Malgun Gothic", 11), bg="#1f1f1f", fg="#ffffff", padx=16, pady=10)
            lbl.pack()
            t.update_idletasks()
            # 마우스가 있는 모니터의 오른쪽 아래에 띄운다 (주 모니터 고정이 아니라)
            try:
                m = monitor_at(win32.list_monitors(), *win32.cursor_pos())
                x, y = m.right - t.winfo_width() - 24, m.bottom - t.winfo_height() - 72
            except Exception:
                x = t.winfo_screenwidth() - t.winfo_width() - 24
                y = t.winfo_screenheight() - t.winfo_height() - 72
            t.geometry(f"+{x}+{y}")
            t.after(ms, t.destroy)
        except tk.TclError:
            pass

    # ================================================================ MCP 도구
    def tools(self) -> list[Tool]:
        return [
            Tool(
                "list_windows",
                "지금 화면에 보이는 창 목록(앱, 제목, hwnd)을 보여준다. capture_window에 넘길 창을 찾을 때 쓴다.",
                {"type": "object", "properties": {}},
                self._tool_list_windows,
            ),
            Tool(
                "capture_window",
                "창 하나를 캡처해 이미지로 돌려준다. hwnd나 제목 일부(title_contains) 중 하나로 고른다.",
                {
                    "type": "object",
                    "properties": {
                        "hwnd": {"type": "integer", "description": "list_windows에서 받은 창 번호"},
                        "title_contains": {"type": "string", "description": "창 제목에 들어 있는 글자 (대소문자 무시)"},
                    },
                },
                self._tool_capture_window,
            ),
            Tool(
                "get_recent_captures",
                "사용자가 단축키로 최근에 찍은 캡처를 최신순으로 돌려준다.",
                {
                    "type": "object",
                    "properties": {"count": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1}},
                },
                self._tool_recent,
            ),
            Tool(
                "diagnostics",
                "snip-to-chat 작동 상태(단축키 등록, Claude 창 활성화, 캡처 품질, 저장 폴더)를 보여준다.",
                {"type": "object", "properties": {}},
                self._tool_diag,
            ),
        ]

    def _tool_list_windows(self, args):
        wins = win32.list_windows(exclude_pid=self.pid)
        lines = [f"{w.hwnd}\t{w.label}\t{w.rect.width}×{w.rect.height}" for w in wins]
        return [text("hwnd\t창\t크기\n" + "\n".join(lines) if lines else "보이는 창이 없어요")]

    def _tool_capture_window(self, args):
        hwnd = args.get("hwnd")
        needle = (args.get("title_contains") or "").strip().lower()
        target = None
        if isinstance(hwnd, int) and hwnd > 0:
            target = win32.window_info(hwnd)
        elif needle:
            for w in win32.list_windows(exclude_pid=self.pid):
                if needle in w.title.lower() or needle in w.label.lower():
                    target = w
                    break
        else:
            raise ToolFailure("hwnd나 title_contains 중 하나를 주세요")
        if target is None:
            raise ToolFailure("그 창을 찾지 못했어요. list_windows로 목록을 먼저 확인하세요")
        try:
            res = win32.capture_window(target.hwnd)
        except win32.CaptureError as e:
            raise ToolFailure(str(e))
        self.diag.capture("tool", res.method, res.image.size, res.blank_fallback)
        self.store.save(res.image, "tool")
        note = " (캡처가 빈 화면이라 화면 잘라내기로 대체함)" if res.blank_fallback else ""
        return [text(f"{target.label} · {res.image.width}×{res.image.height} · {res.method}{note}"), to_mcp_image_content(res.image)]

    def _tool_recent(self, args):
        count = args.get("count", 1)
        if not isinstance(count, int):
            count = 1
        count = max(1, min(5, count))
        with self.recent_lock:
            items = list(self.recent)[:count]
        if items:
            content = []
            for it in items:
                content.append(text(f"{it['at']} · {it['label']} · {it['method']}"))
                content.append(to_mcp_image_content(it["image"]))
            return content
        # 단축키를 맡은 게 다른 프로세스면 이 프로세스 메모리에는 없다 → 저장 폴더에서 읽는다
        files = recent_capture_files(self.store.directory, count)
        if not files:
            raise ToolFailure("아직 단축키로 찍은 캡처가 없어요")
        content = []
        for p in files:
            with Image.open(p) as im:
                img = im.convert("RGB")
            stamp = time.strftime("%H:%M:%S", time.localtime(p.stat().st_mtime))
            content.append(text(f"{stamp} · {p.name}"))
            content.append(to_mcp_image_content(img))
        return content

    def _tool_diag(self, args):
        snap = self.diag.snapshot()
        return [text(summarize(snap)), text(json.dumps(snap, ensure_ascii=False, indent=1, default=str))]
