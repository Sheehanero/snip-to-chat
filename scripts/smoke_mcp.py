"""빌드한 실행 파일을 Claude 데스크톱처럼 띄워 MCP 연결을 시험한다.

1) initialize → tools/list → diagnostics → list_windows 가 정상 응답하는지
2) 두 개를 동시에 띄워도 단축키·아이콘은 하나만 맡는지 (실제 PC에서 Claude가 2개를 띄움)
3) 맡던 쪽의 stdin을 닫으면(=그 연결이 끝나면) 스스로 꺼지고, 남은 쪽이 이어받는지
4) 남은 쪽도 stdin을 닫으면 꺼지는지

사용: python scripts/smoke_mcp.py <snip-to-chat.exe 경로>
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time


class Server:
    def __init__(self, exe: str, tag: str):
        self.tag = tag
        self.p = subprocess.Popen([exe, "--mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.lines: queue.Queue = queue.Queue()
        self.err: list[bytes] = []
        self.next_id = 1
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=lambda: self.err.extend(self.p.stderr), daemon=True).start()

    def _read(self):
        for raw in self.p.stdout:
            self.lines.put(raw)
        self.lines.put(None)

    def send(self, obj):
        self.p.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        self.p.stdin.flush()

    def call(self, method, params=None, timeout=30.0):
        rid = self.next_id
        self.next_id += 1
        self.send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = self.lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if raw is None:
                raise RuntimeError(f"[{self.tag}] 서버가 응답 전에 종료됨")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"[{self.tag}] stdout에 JSON이 아닌 줄: {raw[:200]!r}")
            if msg.get("id") == rid:
                return msg
        raise TimeoutError(f"[{self.tag}] {method} 응답 없음")

    def init(self):
        r = self.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                     "clientInfo": {"name": "smoke", "version": "0"}})
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return r["result"]

    def diag(self) -> dict:
        r = self.call("tools/call", {"name": "diagnostics", "arguments": {}})["result"]
        if r.get("isError"):
            raise RuntimeError(f"[{self.tag}] diagnostics 오류")
        return json.loads(r["content"][1]["text"])

    def close(self, timeout=15) -> tuple[int | None, float]:
        t0 = time.time()
        self.p.stdin.close()
        try:
            return self.p.wait(timeout=timeout), time.time() - t0
        except subprocess.TimeoutExpired:
            self.p.kill()
            return None, time.time() - t0

    def stderr_tail(self, n=10) -> str:
        return "\n".join(b"".join(self.err).decode("utf-8", "replace").strip().splitlines()[-n:])


def is_lead(d: dict) -> bool:
    return d.get("role") == "담당"


def wait_lead(s: Server, timeout=6.0) -> dict:
    deadline = time.time() + timeout
    d = s.diag()
    while time.time() < deadline and not is_lead(d):
        time.sleep(0.5)
        d = s.diag()
    return d


def main(exe: str) -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    failures: list[str] = []
    a = b = None
    try:
        # 1) 연결
        a = Server(exe, "A")
        info = a.init()
        print(f"initialize OK: {info['serverInfo']['name']} {info['serverInfo']['version']} / 프로토콜 {info['protocolVersion']}")
        names = [t["name"] for t in a.call("tools/list")["result"]["tools"]]
        print(f"tools/list OK: {names}")
        for need in ("list_windows", "capture_window", "get_recent_captures", "diagnostics"):
            if need not in names:
                failures.append(f"도구 없음: {need}")
        lw = a.call("tools/call", {"name": "list_windows", "arguments": {}})["result"]
        if lw.get("isError"):
            failures.append("list_windows가 오류를 돌려줌")

        da = wait_lead(a)
        r = a.call("tools/call", {"name": "diagnostics", "arguments": {}})["result"]
        print("diagnostics(A):\n" + r["content"][0]["text"])
        if not is_lead(da):
            failures.append("하나만 떠 있는데 담당이 아님")
        if not all(h.get("registered") for h in da.get("hotkeys", {}).values()) or len(da.get("hotkeys", {})) != 2:
            failures.append(f"단축키 등록 안 됨: {da.get('hotkeys')}")

        # 2) 두 번째를 띄움 → 대기여야 함 (단축키 등록 시도도 안 해야 함)
        b = Server(exe, "B")
        b.init()
        time.sleep(2.0)
        db = b.diag()
        print(f"두 번째(B) 역할: {db.get('role')} · 단축키 정보: {db.get('hotkeys')} · 아이콘: {db.get('tray')}")
        if is_lead(db):
            failures.append("두 번째도 담당이 됨 (아이콘·단축키가 둘)")
        if db.get("hotkeys"):
            failures.append("대기 중인데 단축키 등록을 시도함")

        # 3) A 연결이 끝나면 A는 꺼지고 B가 이어받아야 함
        code, secs = a.close()
        print(f"A: stdin 닫은 뒤 {secs:.1f}초 만에 종료 (코드 {code})")
        if code != 0:
            failures.append(f"A 종료 코드 {code}")
        db = wait_lead(b)
        print(f"B 역할(이어받기 후): {db.get('role')} · 단축키: {db.get('hotkeys')}")
        if not is_lead(db):
            failures.append("A가 꺼졌는데 B가 이어받지 않음")
        elif not all(h.get("registered") for h in db.get("hotkeys", {}).values()):
            failures.append(f"B가 이어받았지만 단축키 등록 실패: {db.get('hotkeys')}")

        # 4) B도 끝
        code, secs = b.close()
        print(f"B: stdin 닫은 뒤 {secs:.1f}초 만에 종료 (코드 {code})")
        if code != 0:
            failures.append(f"B 종료 코드 {code}")
    except Exception as e:
        failures.append(f"통신 실패: {e}")
    finally:
        for s in (a, b):
            if s is not None and s.p.poll() is None:
                s.p.kill()

    for s in (a, b):
        if s is not None and s.err:
            print(f"--- stderr {s.tag} (마지막 10줄)")
            print(s.stderr_tail())

    if failures:
        print("\n실패:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nMCP 연결 시험 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
