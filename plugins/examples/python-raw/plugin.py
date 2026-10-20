#!/usr/bin/env python3
"""Minimal raw webcodex-plugin-v1 provider; Python standard library only."""

import json
import math
import sys

PROTOCOL_VERSION = "webcodex-plugin-v1"
# Example-local byte limits, excluding LF/CRLF. Runner admission remains authoritative.
MAX_INPUT_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 128 * 1024
MAX_TEXT_LENGTH = 4096
MAX_JSON_DEPTH = 16
MAX_JSON_NODES = 4096

TEXT_SCHEMA = {"type": "string", "minLength": 1, "maxLength": MAX_TEXT_LENGTH}
TOOL = {
    "name": "echo",
    "description": "Echo one string without accessing files, processes, or the network.",
    "inputSchema": {
        "type": "object",
        "properties": {"text": TEXT_SCHEMA},
        "required": ["text"],
        "additionalProperties": False,
    },
    "outputSchema": {
        "type": "object",
        "properties": {"text": TEXT_SCHEMA},
        "required": ["text"],
        "additionalProperties": False,
    },
    "annotations": {
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
}


def rpc_error(request_id, code, message):
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def rpc_result(request_id, result):
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def reject_constant(_value):
    raise ValueError("non-standard JSON number")


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite JSON number")
    return number


def valid_string(value):
    if not isinstance(value, str):
        return False
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def json_structure_within_bounds(value):
    """Apply deterministic structure bounds after decoding, independent of CPython recursion limits."""
    pending = [(value, 0)]
    nodes = 0
    while pending:
        current, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            return False
        nodes += 1
        if nodes > MAX_JSON_NODES:
            return False
        if isinstance(current, dict):
            pending.extend((child, depth + 1) for child in current.values())
        elif isinstance(current, list):
            pending.extend((child, depth + 1) for child in current)
    return True


def handle_frame(frame):
    try:
        request = json.loads(
            frame.decode("utf-8"), parse_constant=reject_constant, parse_float=finite_float
        )
    except (ValueError, RecursionError):
        return rpc_error(None, -32700, "parse error")
    if not json_structure_within_bounds(request):
        return rpc_error(None, -32700, "parse error")

    if not isinstance(request, dict) or request.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "invalid request")
    request_id = request.get("id")
    # bool is an int subclass in Python, but is not a JSON-RPC request ID.
    if not (valid_string(request_id) or type(request_id) in (int, float)):
        return rpc_error(None, -32600, "invalid request")
    method = request.get("method")
    if not isinstance(method, str) or not method:
        return rpc_error(request_id, -32600, "invalid request")

    params = request.get("params")
    if method == "initialize":
        if not isinstance(params, dict) or params.get("protocolVersion") != PROTOCOL_VERSION:
            return rpc_error(request_id, -32602, "unsupported protocol version")
        return rpc_result(request_id, {"protocolVersion": PROTOCOL_VERSION})
    if method == "tools/list":
        if "params" in request and not isinstance(params, dict):
            return rpc_error(request_id, -32602, "invalid params")
        return rpc_result(request_id, {"tools": [TOOL]})
    if method == "tools/call":
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            return rpc_error(request_id, -32602, "invalid params")
        if not isinstance(params.get("arguments"), dict):
            return rpc_error(request_id, -32602, "invalid params")
        if params["name"] != "echo":
            return rpc_error(request_id, -32602, "unknown tool")
        arguments = params["arguments"]
        text = arguments.get("text")
        if (
            set(arguments) != {"text"}
            or not valid_string(text)
            or not 1 <= len(text) <= MAX_TEXT_LENGTH
        ):
            return rpc_error(request_id, -32602, "invalid arguments")
        return rpc_result(request_id, {
            "content": [{"type": "text", "text": text}],
            "structuredContent": {"text": text},
            "isError": False,
        })
    return rpc_error(request_id, -32601, "method not found")


def write_response(output, response):
    encoded = json.dumps(response, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_OUTPUT_BYTES:
        # Do not reflect a potentially oversized ID into the fallback error.
        encoded = json.dumps(rpc_error(None, -32600, "response exceeds example limit")).encode("utf-8")
    output.write(encoded + b"\n")
    output.flush()


def serve(input_stream, output):
    while True:
        # Two spare bytes distinguish a full payload followed by CRLF from overflow.
        line = input_stream.readline(MAX_INPUT_BYTES + 2)
        if not line:
            return
        complete = line.endswith(b"\n")
        frame = line[:-1] if complete else line
        if complete and frame.endswith(b"\r"):
            frame = frame[:-1]
        if len(frame) > MAX_INPUT_BYTES:
            write_response(output, rpc_error(None, -32600, "input exceeds example limit"))
            # Discard only the rest of this frame, with bounded memory. The Runner
            # owns transport deadlines; this example adds no independent timeout.
            while line and not line.endswith(b"\n"):
                line = input_stream.readline(MAX_INPUT_BYTES + 2)
            continue
        if not complete:
            write_response(output, rpc_error(None, -32600, "unterminated frame"))
            return
        write_response(output, handle_frame(frame))


if __name__ == "__main__":
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer)
    except (OSError, ValueError):
        # A closed/broken transport cannot receive another protocol response.
        sys.stderr.write("python-raw: transport closed\n")
        sys.exit(1)
