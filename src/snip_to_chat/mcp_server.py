"""MCP 서버 (stdio, JSON-RPC 2.0, 줄 단위).

도구만 제공하는 최소 서버라 공식 SDK 없이 직접 처리한다.
stdout은 MCP 메시지 전용이다. 로그는 절대 stdout에 쓰지 않는다.
"""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable

log = logging.getLogger(__name__)

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

FALLBACK_PROTOCOL = "2025-06-18"


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[dict], list[dict]]  # 인자 → content 블록 목록


def text(s: str) -> dict:
    return {"type": "text", "text": s}


class ToolFailure(Exception):
    """도구 실행은 됐지만 결과가 실패일 때 (isError: true로 돌려준다)."""


class McpServer:
    def __init__(self, name: str, version: str, tools: list[Tool], instructions: str = ""):
        self.name = name
        self.version = version
        self.tools = {t.name: t for t in tools}
        self.instructions = instructions
        self.initialized = False

    # ---- 메시지 하나 처리 ----
    def handle(self, msg: Any) -> Any:
        if isinstance(msg, list):  # 예전 버전의 일괄 요청
            if not msg:
                return _error(None, INVALID_REQUEST, "빈 일괄 요청")
            out = [r for r in (self.handle(m) for m in msg) if r is not None]
            return out or None
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return _error(_id_of(msg), INVALID_REQUEST, "JSON-RPC 2.0 요청이 아니에요")

        # 메시지 종류: 요청(method+id) · 알림(method만) · 응답(result 또는 error)
        if "method" not in msg and ("result" in msg or "error" in msg):
            return None  # 클라이언트가 보낸 응답. 이 서버는 요청을 보내지 않으므로 무시
        method = msg.get("method")
        is_notification = "id" not in msg
        if not isinstance(method, str):
            if is_notification:
                return None
            return _error(msg.get("id"), INVALID_REQUEST, "method가 없어요")

        if is_notification:
            if method == "notifications/initialized":
                self.initialized = True
            return None

        req_id = msg["id"]
        params = msg.get("params") or {}
        if not isinstance(params, dict):
            return _error(req_id, INVALID_PARAMS, "params는 객체여야 해요")
        try:
            if method == "initialize":
                return _result(req_id, self._initialize(params))
            if method == "ping":
                return _result(req_id, {})
            if method == "tools/list":
                return _result(req_id, {"tools": [self._describe(t) for t in self.tools.values()]})
            if method == "tools/call":
                return self._call(req_id, params)
            return _error(req_id, METHOD_NOT_FOUND, f"지원하지 않는 메서드: {method}")
        except Exception as e:  # 마지막 방어선
            log.error("요청 처리 실패: %s\n%s", e, traceback.format_exc())
            return _error(req_id, INTERNAL_ERROR, f"내부 오류: {e}")

    def _initialize(self, params: dict) -> dict:
        requested = params.get("protocolVersion")
        version = requested if isinstance(requested, str) and requested else FALLBACK_PROTOCOL
        result = {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": self.name, "version": self.version},
        }
        if self.instructions:
            result["instructions"] = self.instructions
        return result

    @staticmethod
    def _describe(t: Tool) -> dict:
        return {"name": t.name, "description": t.description, "inputSchema": t.input_schema}

    def _call(self, req_id: Any, params: dict) -> dict:
        name = params.get("name")
        tool = self.tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return _error(req_id, INVALID_PARAMS, f"알 수 없는 도구: {name}")
        args = params.get("arguments") or {}
        if not isinstance(args, dict):
            return _error(req_id, INVALID_PARAMS, "arguments는 객체여야 해요")
        missing = [k for k in tool.input_schema.get("required", []) if k not in args]
        if missing:
            return _error(req_id, INVALID_PARAMS, f"필수 인자 누락: {', '.join(missing)}")
        try:
            content = tool.handler(args)
            return _result(req_id, {"content": content, "isError": False})
        except ToolFailure as e:
            return _result(req_id, {"content": [text(str(e))], "isError": True})
        except Exception as e:
            log.error("도구 %s 실패: %s\n%s", name, e, traceback.format_exc())
            return _result(req_id, {"content": [text(f"{name} 실행 중 오류: {e}")], "isError": True})

    # ---- stdio 루프 ----
    def serve(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        """stdin이 닫히면(=Claude 앱이 종료되면) 돌아온다."""
        for raw in stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as e:
                self._write(stdout, _error(None, PARSE_ERROR, f"JSON 해석 실패: {e}"))
                continue
            reply = self.handle(msg)
            if reply is not None:
                self._write(stdout, reply)

    @staticmethod
    def _write(stdout: BinaryIO, obj: Any) -> None:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        stdout.write(data + b"\n")
        stdout.flush()


def _id_of(msg: Any) -> Any:
    return msg.get("id") if isinstance(msg, dict) else None


def _result(req_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
