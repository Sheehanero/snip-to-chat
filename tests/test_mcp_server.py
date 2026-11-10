import io
import json

from snip_to_chat.mcp_server import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    McpServer,
    Tool,
    ToolFailure,
    text,
)


def make_server():
    def echo(args):
        return [text(f"hi {args['name']}")]

    def boom(args):
        raise RuntimeError("터짐")

    def fail(args):
        raise ToolFailure("Claude 창을 못 찾았어요")

    tools = [
        Tool("echo", "인사", {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}, echo),
        Tool("boom", "예외", {"type": "object", "properties": {}}, boom),
        Tool("fail", "실패", {"type": "object", "properties": {}}, fail),
    ]
    return McpServer("snip-to-chat", "0.1.0", tools, instructions="안내")


def run(lines):
    srv = make_server()
    out = io.BytesIO()
    payload = "".join(l if isinstance(l, str) else json.dumps(l, ensure_ascii=False) + "\n" for l in lines)
    srv.serve(io.BytesIO(payload.encode("utf-8")), out)
    return [json.loads(x) for x in out.getvalue().decode("utf-8").splitlines()], srv


def test_handshake_and_list():
    replies, srv = run(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        ]
    )
    assert len(replies) == 2  # 알림에는 답하지 않는다
    init = replies[0]["result"]
    assert init["protocolVersion"] == "2025-11-25"
    assert init["capabilities"]["tools"] == {"listChanged": False}
    assert init["serverInfo"]["name"] == "snip-to-chat"
    names = [t["name"] for t in replies[1]["result"]["tools"]]
    assert names == ["echo", "boom", "fail"]
    assert srv.initialized


def test_unicode_round_trip_and_string_ids():
    replies, _ = run([{"jsonrpc": "2.0", "id": "abc", "method": "tools/call", "params": {"name": "echo", "arguments": {"name": "제주"}}}])
    r = replies[0]
    assert r["id"] == "abc"
    assert r["result"]["content"][0]["text"] == "hi 제주"
    assert r["result"]["isError"] is False


def test_tool_exception_becomes_iserror_not_crash():
    replies, _ = run(
        [
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "boom"}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "fail"}},
            {"jsonrpc": "2.0", "id": 3, "method": "ping"},
        ]
    )
    assert replies[0]["result"]["isError"] is True and "터짐" in replies[0]["result"]["content"][0]["text"]
    assert replies[1]["result"]["isError"] is True
    assert replies[2]["result"] == {}  # 실패 뒤에도 서버가 계속 동작


def test_protocol_errors():
    replies, _ = run(
        [
            "this is not json\n",
            "\n",  # 빈 줄은 무시
            {"jsonrpc": "2.0", "id": 1, "method": "resources/list"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "nope"}},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "echo", "arguments": {}}},
            {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "echo", "arguments": "x"}},
            {"jsonrpc": "2.0", "id": 5, "result": {}},  # 클라이언트의 응답 메시지 → 무시
        ]
    )
    codes = [r["error"]["code"] for r in replies]
    assert codes == [PARSE_ERROR, METHOD_NOT_FOUND, INVALID_PARAMS, INVALID_PARAMS, INVALID_PARAMS]
    assert replies[0]["id"] is None


def test_missing_protocol_version_gets_fallback():
    replies, _ = run([{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}])
    assert replies[0]["result"]["protocolVersion"]


def test_output_is_one_line_per_message():
    srv = make_server()
    out = io.BytesIO()
    msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo", "arguments": {"name": "a\nb"}}}
    srv.serve(io.BytesIO((json.dumps(msg) + "\n").encode()), out)
    lines = out.getvalue().split(b"\n")
    assert lines[-1] == b"" and len(lines) == 2  # 메시지 안의 줄바꿈은 이스케이프되어 한 줄
