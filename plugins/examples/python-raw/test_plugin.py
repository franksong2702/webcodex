"""Offline protocol checks. Run: python -B -m unittest discover -s <this directory> -v"""

import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import unittest

import plugin

SCRIPT = Path(__file__).with_name("plugin.py")
TIMEOUT = 10


def child_environment():
    environment = dict(os.environ)
    # The flush check must not accidentally inherit unbuffered Python output.
    environment.pop("PYTHONUNBUFFERED", None)
    # Protocol encoding must work even with a non-UTF-8 console configuration.
    environment["PYTHONIOENCODING"] = "ascii"
    return environment


def request(method="tools/list", request_id=1, **params):
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def frame(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8") + b"\n"


def echo(text="hello", request_id=2):
    return request("tools/call", request_id, name="echo", arguments={"text": text})


class ProtocolTests(unittest.TestCase):
    def run_wire(self, data):
        # communicate drains both pipes and closes stdin after these exact bytes.
        with subprocess.Popen(
            [sys.executable, "-B", str(SCRIPT)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=child_environment(),
        ) as process:
            try:
                output, error = process.communicate(data, timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                self.fail("plugin did not finish before the absolute deadline")
        self.assertEqual(process.returncode, 0, error)
        self.assertEqual(error, b"")
        if output:
            self.assertTrue(output.endswith(b"\n"))
        responses = []
        for line in output.splitlines():
            self.assertLessEqual(len(line), plugin.MAX_OUTPUT_BYTES)
            value = json.loads(line.decode("utf-8"))
            self.assertEqual(value["jsonrpc"], "2.0")
            self.assertIn("id", value)
            self.assertNotEqual("result" in value, "error" in value)
            responses.append(value)
        return responses

    def assert_echo(self, response, text="hello", request_id=2):
        self.assertEqual(response, {
            "jsonrpc": "2.0", "id": request_id,
            "result": {
                "content": [{"type": "text", "text": text}],
                "structuredContent": {"text": text}, "isError": False,
            },
        })

    def assert_recovers(self, bad_frame, code, request_id=None):
        responses = self.run_wire(bad_frame + frame(echo()))
        self.assertEqual(len(responses), 2)
        error, good = responses
        self.assertEqual(error["id"], request_id)
        self.assertEqual(error["error"]["code"], code)
        self.assertLess(len(error["error"]["message"]), 80)
        self.assert_echo(good)

    def test_initialize_list_call_and_repeat_in_one_process(self):
        responses = self.run_wire(
            frame(request("initialize", protocolVersion=plugin.PROTOCOL_VERSION))
            + frame(request(request_id="catalog")) + frame(echo()) + frame(echo("again", 3))
        )
        self.assertEqual(len(responses), 4)
        self.assertEqual(responses[0]["result"], {"protocolVersion": "webcodex-plugin-v1"})
        self.assertEqual(responses[1]["id"], "catalog")
        tools = responses[1]["result"]["tools"]
        self.assertEqual(len(tools), 1)
        tool = tools[0]
        self.assertEqual(tool["name"], "echo")
        for key in ("inputSchema", "outputSchema"):
            self.assertEqual(tool[key], {
                "type": "object", "properties": {
                    "text": {"type": "string", "minLength": 1, "maxLength": 4096},
                }, "required": ["text"], "additionalProperties": False,
            })
        self.assertEqual(tool["annotations"], {
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": False,
        })
        self.assert_echo(responses[2])
        self.assert_echo(responses[3], "again", 3)

    def test_string_and_id_round_trips(self):
        texts = ["x", "x" * 4096, "中文😀" * 1365, 'quote " slash \\ tab\t newline\n', "\0" * 4096]
        ids = [0, -1, 1.5, "", "中文😀", "id\n\t"]
        messages = [echo(text, index) for index, text in enumerate(texts)]
        messages += [echo("id", value) for value in ids]
        responses = self.run_wire(b"".join(frame(message) for message in messages))
        self.assertEqual(len(responses), len(messages))
        for message, response in zip(messages, responses):
            self.assert_echo(response, message["params"]["arguments"]["text"], message["id"])

    def test_invalid_arguments_recover(self):
        for arguments in [{}, {"text": ""}, {"text": "x" * 4097}, {"text": 1},
                          {"text": True}, {"text": None}, {"text": []},
                          {"text": {}}, {"text": "ok", "extra": 1}]:
            with self.subTest(arguments_type=str(arguments)[:80]):
                self.assert_recovers(frame(request("tools/call", name="echo", arguments=arguments)), -32602, 1)

    def test_method_and_params_errors_recover(self):
        cases = [
            (request("initialize"), -32602),
            (request("initialize", protocolVersion="other"), -32602),
            (request("unknown"), -32601),
            (request("tools/call", name="missing", arguments={}), -32602),
            (request("tools/call", name="echo"), -32602),
            (request("tools/call", name=3, arguments={}), -32602),
            (request("tools/call", name="echo", arguments=[]), -32602),
        ]
        for method in ("initialize", "tools/list", "tools/call"):
            for params in (None, [], "", 1, True):
                value = request(method)
                value["params"] = params
                cases.append((value, -32602))
        for value, code in cases:
            with self.subTest(value=value):
                self.assert_recovers(frame(value), code, 1)

    def test_list_allows_absent_params_without_new_initialize_gate(self):
        value = request()
        del value["params"]
        self.assertEqual(len(self.run_wire(frame(value))[0]["result"]["tools"]), 1)

    def test_invalid_requests_recover(self):
        values = [None, True, 1, "text", [], [request()], {},
                  {**request(), "jsonrpc": "1.0"}]
        values += [{**request(), "id": value} for value in (None, True, [], {})]
        notification = request()
        del notification["id"]
        values.append(notification)
        for value in values:
            with self.subTest(value=value):
                self.assert_recovers(frame(value), -32600)
        for method in (None, "", [], 1):
            self.assert_recovers(frame({**request(), "method": method}), -32600, 1)

    def test_malformed_json_utf8_and_numbers_recover(self):
        frames = [b"\n", b"{\n", b"{}{}\n", b"\xff\n"]
        for number in (b"NaN", b"Infinity", b"-Infinity", b"1e9999", b"9" * 5000):
            frames.append(b'{"jsonrpc":"2.0","id":' + number + b',"method":"tools/list"}\n')
        for value in frames:
            with self.subTest(prefix=value[:40]):
                self.assert_recovers(value, -32700)

    def test_json_structure_bounds_recover_without_parser_recursion_assumptions(self):
        deep = None
        for _ in range(plugin.MAX_JSON_DEPTH + 1):
            deep = [deep]
        too_deep = request()
        too_deep["params"] = {"extra": deep}
        self.assert_recovers(frame(too_deep), -32700)

        too_wide = request()
        too_wide["params"] = {"extra": [None] * plugin.MAX_JSON_NODES}
        self.assertLessEqual(len(frame(too_wide)) - 1, plugin.MAX_INPUT_BYTES)
        self.assert_recovers(frame(too_wide), -32700)

    def test_unpaired_surrogates_are_not_echoed(self):
        self.assert_recovers(b'{"jsonrpc":"2.0","id":"\\ud800","method":"tools/list"}\n', -32600)
        value = json.dumps(echo("\ud800"), ensure_ascii=True).encode() + b"\n"
        self.assert_recovers(value, -32602, 2)

    def test_input_limit_lf_crlf_and_recovery(self):
        base = frame(request()).rstrip(b"\n")
        for ending in (b"\n", b"\r\n"):
            for size in (plugin.MAX_INPUT_BYTES - 1, plugin.MAX_INPUT_BYTES):
                data = base + b" " * (size - len(base)) + ending
                self.assertIn("result", self.run_wire(data)[0])
            for size in (plugin.MAX_INPUT_BYTES + 1, plugin.MAX_INPUT_BYTES * 3):
                data = base + b" " * (size - len(base)) + ending
                self.assert_recovers(data, -32600)

    def test_unicode_id_and_escaped_output_stay_bounded(self):
        value = echo("\0" * 4096, "😀" * 9000)
        data = frame(value)
        self.assertLessEqual(len(data) - 1, plugin.MAX_INPUT_BYTES)
        self.assert_echo(self.run_wire(data)[0], "\0" * 4096, "😀" * 9000)

    def test_eof_and_unterminated_frames(self):
        self.assertEqual(self.run_wire(b""), [])
        for data in (frame(echo())[:-1], b"{", b"x" * (plugin.MAX_INPUT_BYTES * 3)):
            with self.subTest(size=len(data)):
                responses = self.run_wire(data)
                self.assertEqual(len(responses), 1)
                self.assertEqual(responses[0]["error"]["code"], -32600)

    def test_interactive_flush_and_split_utf8_without_closing_stdin(self):
        deadline = time.monotonic() + TIMEOUT
        process = subprocess.Popen(
            [sys.executable, "-B", str(SCRIPT)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=child_environment(),
        )
        lines = queue.Queue()
        diagnostics = []

        def drain_stdout():
            while line := process.stdout.readline(plugin.MAX_OUTPUT_BYTES + 2):
                lines.put(line)

        def drain_stderr():
            diagnostics.append(process.stderr.read())

        readers = [threading.Thread(target=drain_stdout), threading.Thread(target=drain_stderr)]
        for reader in readers:
            reader.start()
        try:
            for value in [request("initialize", protocolVersion=plugin.PROTOCOL_VERSION), request(), echo("中文😀")]:
                data = frame(value)
                # Explicit writes split a UTF-8 sequence; no sleep/readiness guess.
                split = data.index("😀".encode()) + 1 if b"\xf0" in data else 1
                for chunk in (data[:split], data[split:]):
                    process.stdin.write(chunk)
                    process.stdin.flush()
                line = lines.get(timeout=max(0, deadline - time.monotonic()))
                self.assertTrue(line.endswith(b"\n"))
                response = json.loads(line)
                self.assertEqual(response["id"], value["id"])
                self.assertIn("result", response)
            self.assert_echo(response, "中文😀")
            self.assertIsNone(process.poll())
            process.stdin.close()
            self.assertEqual(process.wait(timeout=max(0, deadline - time.monotonic())), 0)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=TIMEOUT)
            for reader in readers:
                reader.join(timeout=TIMEOUT)
            for pipe in (process.stdin, process.stdout, process.stderr):
                pipe.close()
        self.assertEqual(diagnostics, [b""])
        self.assertTrue(lines.empty())


class BoundsTests(unittest.TestCase):
    def test_reads_are_bounded_even_when_discarding(self):
        class BoundedInput(io.BytesIO):
            def readline(self, size=-1):
                if not 0 < size <= plugin.MAX_INPUT_BYTES + 2:
                    raise AssertionError("unbounded read")
                return super().readline(size)

        output = io.BytesIO()
        plugin.serve(BoundedInput(b"x" * (plugin.MAX_INPUT_BYTES * 4) + b"\n" + frame(echo())), output)
        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(responses), 2)
        self.assertEqual(responses[0]["error"]["code"], -32600)
        self.assertEqual(responses[1]["result"]["structuredContent"], {"text": "hello"})

    def test_output_guard_does_not_reflect_oversized_response(self):
        output = io.BytesIO()
        plugin.write_response(output, plugin.rpc_result("x" * plugin.MAX_OUTPUT_BYTES, {}))
        self.assertLess(len(output.getvalue()), 200)
        self.assertEqual(json.loads(output.getvalue())["id"], None)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], -32600)


if __name__ == "__main__":
    unittest.main()
