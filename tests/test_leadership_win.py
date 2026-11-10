"""단축키·아이콘 담당 고르기 시험 (Windows 전용).

Claude가 서버를 여러 개 띄워도 하나만 맡고, 맡던 쪽이 꺼지면 다음 것이 이어받는지 본다.
"""

import subprocess
import sys
import threading
import time
import uuid

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows 전용")


def _name():
    return f"Local\\snip-to-chat-test-{uuid.uuid4().hex}"


def test_only_one_leads_then_next_takes_over():
    from snip_to_chat.win32 import Leadership

    name = _name()
    led = []
    a = Leadership(lambda: led.append("a"), name=name)
    b = Leadership(lambda: led.append("b"), name=name)
    a.start()
    time.sleep(0.3)
    b.start()
    time.sleep(1.5)
    assert led == ["a"] and a.is_leader and not b.is_leader  # 둘 다 떠 있어도 하나만

    a.stop()
    a.join(timeout=3)
    deadline = time.time() + 3
    while time.time() < deadline and "b" not in led:
        time.sleep(0.05)
    assert led == ["a", "b"] and b.is_leader  # 맡던 쪽이 끝나면 이어받음
    b.stop()
    b.join(timeout=3)


def test_takes_over_when_leader_process_dies():
    from snip_to_chat.win32 import Leadership, try_lead_now

    name = _name()
    holder = subprocess.Popen(
        [sys.executable, "-c",
         "import sys, time, ctypes; from ctypes import wintypes as wt;"
         "k=ctypes.WinDLL('kernel32'); k.CreateMutexW.restype=wt.HANDLE;"
         "k.CreateMutexW.argtypes=[ctypes.c_void_p, wt.BOOL, wt.LPCWSTR];"
         "h=k.CreateMutexW(None, False, sys.argv[1]); k.WaitForSingleObject(wt.HANDLE(h), 0xFFFFFFFF);"
         "print('held', flush=True); time.sleep(60)", name],
        stdout=subprocess.PIPE,
    )
    try:
        assert holder.stdout.readline().strip() == b"held"
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("now", try_lead_now(name)))
        t.start()
        t.join()
        assert result["now"] is False  # 다른 프로세스가 맡고 있으면 시험 모드는 못 맡는다

        led = threading.Event()
        b = Leadership(led.set, name=name)
        b.start()
        time.sleep(1.0)
        assert not led.is_set()
        holder.kill()  # 맡던 프로세스가 갑자기 꺼짐 (뮤텍스가 버려짐)
        assert led.wait(3) and b.is_leader
        b.stop()
        b.join(timeout=3)
    finally:
        holder.kill()
