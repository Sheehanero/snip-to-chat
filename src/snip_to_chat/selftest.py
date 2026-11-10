"""자체 점검 (--selftest). Claude에 설치하기 전에 이 PC에서 확인 항목을 미리 본다."""

from __future__ import annotations

import json
import os
import struct
import time

from . import __version__, win32
from .config import Settings
from .storage import CaptureStore, resolve_capture_dir

BROWSERS = {"chrome.exe", "msedge.exe", "whale.exe", "firefox.exe"}
DOCS = {"hwp.exe", "acrord32.exe", "acrobat.exe", "winword.exe", "excel.exe", "powerpnt.exe"}


def _p(line: str = ""):
    print(line, flush=True)


def run_selftest(settings: Settings, dpi: str) -> int:
    report: dict = {"version": __version__, "dpi_awareness": dpi, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    _p(f"snip-to-chat {__version__} 자체 점검")
    _p("=" * 60)

    # 0. 기본 환경
    bits = struct.calcsize("P") * 8
    input_size = win32.input_struct_size()
    expected = 40 if bits == 64 else 28
    report["input_struct"] = {"bits": bits, "size": input_size, "ok": input_size == expected}
    _p(f"[환경] {bits}비트 · DPI 인식 {dpi} · 키 입력 구조체 {'정상' if input_size == expected else '이상'}")
    for p in settings.problems:
        _p(f"  설정 문제: {p}")
    try:
        mons = win32.list_monitors()
        report["monitors"] = [[m.left, m.top, m.right, m.bottom] for m in mons]
        _p(f"[모니터] {len(mons)}대: " + " / ".join(f"{m.width}×{m.height} 위치({m.left},{m.top})" for m in mons))
    except Exception as e:
        report["monitors"] = {"error": str(e)}
        _p(f"[모니터] 확인 실패: {e}")

    # 1. 단축키 등록
    _p("")
    _p("[1] 단축키 등록")
    report["hotkeys"] = {}
    for name, hk in (("선택 화면", settings.select_hotkey), ("활성 창", settings.active_hotkey)):
        ok, why = win32.try_register(hk)
        report["hotkeys"][name] = {"spec": hk.text, "ok": ok, "reason": why}
        _p(f"  {name} {hk.text}: {'OK' if ok else '실패'} ({why})")

    # 2. Claude 창
    _p("")
    _p("[2] Claude 데스크톱 창")
    claude = win32.find_claude_window(exclude_pid=os.getpid())
    report["claude_window"] = claude.to_dict() if claude else None
    _p(f"  {'찾음: ' + claude.label + ' (hwnd ' + str(claude.hwnd) + ')' if claude else '못 찾음 — Claude 데스크톱을 켜고 다시 해보세요'}")

    # 3. 창 캡처
    _p("")
    _p("[3] 창 캡처 (가려진 창도 내용이 찍히는지, 검게 나오지 않는지)")
    store = CaptureStore(resolve_capture_dir(settings.capture_dir_override))
    # Claude 창은 붙여넣을 곳이지 찍을 대상이 아니라서 판정에서 뺀다
    # (Claude 창은 PrintWindow가 빈 화면을 돌려줘 화면 잘라내기로 대체되는 것이 정상)
    windows = [w for w in win32.list_windows(exclude_pid=os.getpid()) if w.exe != "claude.exe"]
    targets = [w for w in windows if w.exe in BROWSERS] + [w for w in windows if w.exe in DOCS]
    others = [w for w in windows if w not in targets][:3]
    results = []
    for w in targets + others:
        t0 = time.perf_counter()
        try:
            res = win32.capture_window(w.hwnd)
            ms = round((time.perf_counter() - t0) * 1000)
            saved = store.save(res.image, "selftest")
            verdict = "대체됨(빈 화면)" if res.blank_fallback else "OK"
            results.append(
                {"window": w.label, "exe": w.exe, "method": res.method, "blank_fallback": res.blank_fallback,
                 "size": list(res.image.size), "ms": ms, "saved": str(saved.path) if saved.path else None}
            )
            _p(f"  {verdict:<12} {w.label[:44]:<44} {res.method} {res.image.width}×{res.image.height} {ms}ms")
        except Exception as e:
            results.append({"window": w.label, "exe": w.exe, "error": str(e)})
            _p(f"  {'오류':<12} {w.label[:44]:<44} {e}")
    if not results:
        _p("  찍을 창이 없어요 — 크롬·엣지·한글 창을 몇 개 띄워두고 다시 해보세요")
    report["captures"] = results

    # 4. 클립보드
    _p("")
    _p("[4] 클립보드 이미지 넣기 (지금 클립보드 내용이 시험 이미지로 바뀌어요)")
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        root.update_idletasks()
        owner = int(root.wm_frame(), 16)
        from PIL import Image

        win32.set_clipboard_image(Image.new("RGB", (64, 48), (55, 138, 221)), owner)
        fmts = win32.clipboard_has_image()
        root.destroy()
        report["clipboard"] = {"ok": all(fmts.values()), **fmts}
        _p(f"  CF_DIB {'OK' if fmts['CF_DIB'] else '없음'} · PNG {'OK' if fmts['PNG'] else '없음'}")
    except Exception as e:
        report["clipboard"] = {"ok": False, "error": str(e)}
        _p(f"  실패: {e}")

    # 5. 저장 폴더
    _p("")
    _p("[5] 저장 폴더")
    report["storage"] = {"dir": str(store.directory), "safe": store.safe, "reason": store.reason}
    _p(f"  {store.directory}")
    _p(f"  {'안전 (git 저장소 밖)' if store.safe else '저장 안 함: ' + store.reason}")

    # 보고서 저장 (캡처 폴더 옆, git 저장소 밖일 때만)
    _p("")
    if store.safe:
        out = store.directory.parent / "selftest-report.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _p(f"보고서: {out}")
    ok = (
        all(h["ok"] for h in report["hotkeys"].values())
        and report.get("clipboard", {}).get("ok")
        and not any(r.get("error") or r.get("blank_fallback") for r in results)
    )
    _p("=" * 60)
    _p("전부 통과" if ok else "확인이 필요한 항목이 있어요 (위 표시 참고)")
    return 0 if ok else 1
