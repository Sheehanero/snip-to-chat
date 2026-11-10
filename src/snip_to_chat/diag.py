"""진단 상태 기록. 확인 항목 4개를 판단할 근거를 모은다.

diagnostics 도구와 --selftest가 이 내용을 보여준다.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque
from typing import Any

from . import __version__


class Diagnostics:
    def __init__(self, mode: str):
        self._lock = threading.Lock()
        self.started_at = time.time()
        self.data: dict[str, Any] = {
            "version": __version__,
            "mode": mode,
            "pid": os.getpid(),
            "hotkeys": {},
            "hotkey_thread_alive": False,
            "hotkey_events": 0,
            "last_hotkey_at": None,
            "activation": None,
            "captures": {"count": 0, "blank_fallbacks": 0, "last": None},
            "storage": None,
            "settings_problems": [],
            "env": {},
        }
        self.errors: deque[str] = deque(maxlen=20)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self.data[key] = value

    def update(self, key: str, **values: Any) -> None:
        with self._lock:
            cur = self.data.get(key)
            if not isinstance(cur, dict):
                cur = {}
            cur.update(values)
            self.data[key] = cur

    def hotkey(self, name: str, **values: Any) -> None:
        with self._lock:
            self.data["hotkeys"].setdefault(name, {}).update(values)

    def hotkey_fired(self) -> None:
        with self._lock:
            self.data["hotkey_events"] += 1
            self.data["last_hotkey_at"] = _stamp()

    def capture(self, kind: str, method: str, size: tuple[int, int], blank_fallback: bool) -> None:
        with self._lock:
            c = self.data["captures"]
            c["count"] += 1
            if blank_fallback:
                c["blank_fallbacks"] += 1
            c["last"] = {
                "kind": kind,
                "method": method,
                "size": list(size),
                "blank_fallback": blank_fallback,
                "at": _stamp(),
            }

    def error(self, message: str) -> None:
        with self._lock:
            self.errors.append(f"{_stamp()} {message}")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snap = {k: (dict(v) if isinstance(v, dict) else v) for k, v in self.data.items()}
            snap["uptime_seconds"] = round(time.time() - self.started_at)
            snap["recent_errors"] = list(self.errors)
            return snap


def _stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def summarize(snap: dict[str, Any]) -> str:
    """사람이 읽는 한국어 요약."""
    lines = [f"snip-to-chat {snap.get('version')} · 모드 {snap.get('mode')} · PID {snap.get('pid')}"]
    up = snap.get("uptime_seconds", 0)
    lines.append(f"실행 시간: {up // 3600}시간 {(up % 3600) // 60}분 {up % 60}초")

    lines.append("")
    lines.append("[1] 단축키 감시")
    lines.append(f"  감시 스레드: {'살아 있음' if snap.get('hotkey_thread_alive') else '멈춤'}")
    for name, info in (snap.get("hotkeys") or {}).items():
        state = "등록됨" if info.get("registered") else f"등록 실패 ({info.get('error', '?')})"
        lines.append(f"  {name}: {info.get('spec')} → {state}")
    lines.append(f"  눌린 횟수: {snap.get('hotkey_events')} (마지막: {snap.get('last_hotkey_at') or '없음'})")

    lines.append("")
    lines.append("[2] Claude 창 앞으로 가져오기·붙여넣기")
    act = snap.get("activation")
    if not act:
        lines.append("  아직 시도 안 함")
    else:
        lines.append(
            f"  마지막 시도 {act.get('at')}: Claude 창 {'찾음' if act.get('claude_found') else '못 찾음'}, "
            f"앞으로 가져오기 {'성공(' + str(act.get('method')) + ')' if act.get('activated') else '실패'}, "
            f"붙여넣은 장수 {act.get('pasted', 0)}"
        )
        if act.get("note"):
            lines.append(f"  참고: {act['note']}")

    lines.append("")
    lines.append("[3] 창 캡처 품질")
    cap = snap.get("captures") or {}
    lines.append(f"  캡처 {cap.get('count', 0)}건 중 빈 화면이라 화면 잘라내기로 대체한 것 {cap.get('blank_fallbacks', 0)}건")
    last = cap.get("last")
    if last:
        lines.append(
            f"  마지막: {last.get('kind')} · 방식 {last.get('method')} · {last.get('size')} · {last.get('at')}"
        )

    lines.append("")
    lines.append("[4] 저장 폴더")
    st = snap.get("storage") or {}
    lines.append(f"  {st.get('dir')} → {'안전' if st.get('safe') else '저장 안 함'} ({st.get('reason')})")

    probs = snap.get("settings_problems") or []
    if probs:
        lines.append("")
        lines.append("설정 문제:")
        lines.extend(f"  - {p}" for p in probs)
    errs = snap.get("recent_errors") or []
    if errs:
        lines.append("")
        lines.append("최근 오류:")
        lines.extend(f"  - {e}" for e in errs[-8:])
    return "\n".join(lines)
