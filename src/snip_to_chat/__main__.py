"""실행 진입점.

- Claude 데스크톱이 띄울 때(stdin이 파이프): MCP 서버 + 단축키 감시
- 사용자가 직접 실행할 때(stdin이 콘솔): 단축키 감시만 (MCP 없이 시험용)
- --selftest: 자체 점검
"""

from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from . import APP_NAME, __version__


def _log_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    return Path(base) / APP_NAME


def _setup_logging(mode: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        d = _log_dir()
        d.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(d / f"{APP_NAME}.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    # stdout은 MCP 전용이므로 로그는 stderr로만 (Claude 앱이 MCP 로그로 모은다)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO if mode == "mcp" else logging.WARNING)
    root.addHandler(sh)


def _utf8_streams() -> None:
    """파이프로 연결되면 Windows 기본 인코딩(cp1252·cp949)이라 한글 출력·로그가 깨지거나 죽는다."""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _stdin_is_console() -> bool:
    try:
        return sys.stdin is not None and sys.stdin.isatty()
    except (AttributeError, ValueError, OSError):
        return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=APP_NAME, description="창·영역을 캡처해 Claude 데스크톱 채팅에 첨부")
    ap.add_argument("--selftest", action="store_true", help="이 PC에서 확인 항목을 점검")
    ap.add_argument("--standalone", action="store_true", help="MCP 없이 단축키만 (시험용)")
    ap.add_argument("--mcp", action="store_true", help="MCP 서버 모드 강제")
    ap.add_argument("--version", action="store_true")
    ap.add_argument("--check-uia", action="store_true", help="탭 읽기(UI Automation) 준비 확인")
    args = ap.parse_args(argv)
    _utf8_streams()

    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    if args.check_uia:
        from .browser_tabs import _client

        U, uia = _client()
        print(f"UI Automation OK: {type(uia).__name__}, TabItem={U.UIA_TabItemControlTypeId}")
        return 0

    if sys.platform != "win32":
        print("snip-to-chat은 Windows 전용이에요", file=sys.stderr)
        return 2

    from .config import load_settings

    settings = load_settings()

    if args.selftest:
        _setup_logging("selftest")
        from . import win32
        from .selftest import run_selftest

        dpi = win32.set_dpi_awareness()
        code = run_selftest(settings, dpi)
        if _stdin_is_console():
            try:
                input("\nEnter를 누르면 닫혀요...")
            except EOFError:
                pass
        return code

    mode = "mcp" if args.mcp or (not args.standalone and not _stdin_is_console()) else "standalone"
    _setup_logging(mode)
    log = logging.getLogger(APP_NAME)

    from . import win32
    from .diag import Diagnostics

    real_stdout = None
    if mode == "mcp":
        real_stdout = sys.stdout.buffer
        sys.stdout = sys.stderr  # 실수로 print해도 MCP 메시지를 깨지 않게
        hidden = win32.hide_console_window()
    else:
        hidden = False

    if mode == "standalone" and not win32.try_lead_now():
        # 시험 모드는 단축키를 못 맡으면 쓸모가 없으니 바로 알리고 끝낸다
        # (MCP 모드는 Claude가 띄운 것이라 끝내지 않고, 대기하다가 이어받는다)
        log.warning("이미 실행 중이라 시험 모드를 끝냄")
        print(f"{APP_NAME}이 이미 실행 중이에요 (Claude에 설치한 것이나 다른 시험 창).")
        print("그쪽을 끄고 다시 실행하세요.")
        if _stdin_is_console():
            try:
                input("Enter를 누르면 닫혀요...")
            except EOFError:
                pass
        return 3

    dpi = win32.set_dpi_awareness()
    diag = Diagnostics(mode)
    diag.set("settings_problems", list(settings.problems))
    diag.set("env", {"dpi_awareness": dpi, "console_hidden": hidden, "auto_paste": settings.auto_paste})
    log.info("시작: %s 모드, 단축키 %s / %s", mode, settings.select_hotkey.text, settings.active_hotkey.text)

    if mode == "standalone":
        print(f"{APP_NAME} {__version__} — 단축키 대기 중 (MCP 없이 시험 모드)")
        print(f"  선택 화면: {settings.select_hotkey.text}")
        print(f"  활성 창 바로 찍기: {settings.active_hotkey.text}")
        for p in settings.problems:
            print(f"  설정 문제: {p}")
        print("이 창을 닫으면 종료돼요.")

    from .app import App

    return App(settings, mode, diag, stdout=real_stdout).run()


if __name__ == "__main__":
    sys.exit(main())
