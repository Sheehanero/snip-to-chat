"""빌드한 실행 파일을 Claude 데스크톱처럼 띄워 MCP 연결을 시험한다.

1) initialize → tools/list → diagnostics → list_windows 가 정상 응답하는지
2) stdin을 닫으면(=Claude 앱 종료) 프로세스가 스스로 끝나는지

사용: python scripts/smoke_mcp.py <snip-to-chat.exe 경로>
"""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time


def main(exe: str) -> int:
    p = subprocess.Popen([exe, "--mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    lines: queue.Queue = queue.Queue()

    def reader():
        for raw in p.stdout:
            lines.put(raw)
        lines.put(None)

    threading.Thread(target=reader, daemon=True).start()
    err_buf: list[bytes] = []
    threading.Thread(target=lambda: err_buf.extend(p.stderr), daemon=True).start()

    def send(obj):
        p.stdin.write((json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8"))
        p.stdin.flush()

    def recv(expect_id, timeout=30.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                raw = lines.get(timeout=0.5)
            except queue.Empty:
                continue
            if raw is None:
                raise RuntimeError("서버가 응답 전에 종료됨")
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                raise RuntimeError(f"stdout에 JSON이 아닌 줄: {raw[:200]!r}")
            if msg.get("id") == expect_id:
                return msg
        raise TimeoutError(f"id {expect_id} 응답 없음")

    failures: list[str] = []
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}})
        r = recv(1)
        info = r["result"]["serverInfo"]
        print(f"initialize OK: {info['name']} {info['version']} / 프로토콜 {r['result']['protocolVersion']}")
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        names = [t["name"] for t in recv(2)["result"]["tools"]]
        print(f"tools/list OK: {names}")
        for need in ("list_windows", "capture_window", "get_recent_captures", "diagnostics"):
            if need not in names:
                failures.append(f"도구 없음: {need}")

        time.sleep(1.0)  # 단축키 스레드가 등록을 마칠 시간
        send({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "diagnostics", "arguments": {}}})
        d = recv(3)["result"]
        if d.get("isError"):
            failures.append("diagnostics가 오류를 돌려줌")
        print("diagnostics:\n" + d["content"][0]["text"])

        send({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "list_windows", "arguments": {}}})
        lw = recv(4)["result"]
        print(f"list_windows: isError={lw.get('isError')}")
        if lw.get("isError"):
            failures.append("list_windows가 오류를 돌려줌")
    except Exception as e:
        failures.append(f"통신 실패: {e}")

    # stdin을 닫으면 스스로 끝나야 한다 (Claude 앱이 꺼질 때 같이 꺼지는지)
    t0 = time.time()
    try:
        p.stdin.close()
        code = p.wait(timeout=15)
        print(f"stdin 닫은 뒤 {time.time() - t0:.1f}초 만에 종료 (코드 {code})")
        if code != 0:
            failures.append(f"종료 코드 {code}")
    except subprocess.TimeoutExpired:
        p.kill()
        failures.append("stdin을 닫아도 15초 안에 안 끝남")

    if err_buf:
        tail = b"".join(err_buf).decode("utf-8", "replace").strip().splitlines()[-15:]
        print("--- stderr (마지막 15줄)")
        print("\n".join(tail))

    if failures:
        print("\n실패:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("\nMCP 연결 시험 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
