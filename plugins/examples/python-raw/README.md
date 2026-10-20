# Python raw-protocol Native Tool Plugin

A small, standard-library-only example of `webcodex-plugin-v1`: one JSON-RPC
request/response per UTF-8 line on stdin/stdout. This is a WebCodex Native Tool
Plugin, not an MCP server or a Python SDK. It has no TypeScript SDK dependency.

The only tool, `echo`, accepts exactly `{"text": "hello"}` with 1–4096 Unicode
characters and returns text content plus `structuredContent: {"text": "hello"}`.
It performs no filesystem, subprocess, or network operations. Its schemas and
read-only/idempotent annotations demonstrate the authoring boundary.

## Run and test

Python 3.12 is the tested baseline. There is no build or dependency installation
step. From the repository root, using your installed Python executable:

```text
python -B plugins/examples/python-raw/plugin.py
python -B -m unittest discover -s plugins/examples/python-raw -v
```

`python` may be named `python3` on your system. The process reads until stdin EOF;
it emits no banner. Send these lines in order for a direct protocol smoke:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"webcodex-plugin-v1"}}
{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"echo","arguments":{"text":"hello"}}}
```

The last response is:

```json
{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"hello"}],"structuredContent":{"text":"hello"},"isError":false}}
```

Each response is flushed immediately, without waiting for stdin to close. The
tests exercise both complete transcripts and an interactive subprocess, including
invalid input followed by a successful call. They need no Runner, credentials,
network, or third-party test packages.

For contributors with the repository Rust toolchain, the separate Runner smoke
starts this script through the real PluginManager in an isolated temporary
directory. It does not connect to a running Server or reload any provider.
Set the test-only executable path explicitly, then run just that ignored test:

```bash
export WEBCODEX_TEST_PYTHON="$(python3 -c 'import sys; print(sys.executable)')"
cargo test --locked -p webcodex-runner --features runner-real-process-tests webcodex_runner::plugin::tests::python_raw_plugin_admission_and_call -- --exact --ignored --test-threads=1
```

In PowerShell, set the variable with
`$env:WEBCODEX_TEST_PYTHON = python -c "import sys; print(sys.executable)"`, then
run the same Cargo command. An absent or invalid interpreter fails explicitly.
This smoke is opt-in and is not run by ordinary CI. Its test name keeps it
outside the general `runner_real_process` lifecycle filter. Ordinary Cargo
tests and that lifecycle group do not require this example's Python interpreter
configuration.

## Bounds and errors

The example limits each input JSON frame to **64 KiB** and each serialized output
frame to **128 KiB**, excluding the LF or CRLF line ending. These are local example
limits, not replacements for Runner limits. Reads always have a size bound. An
oversized input produces one fixed error; the remaining bytes up to LF/EOF are
discarded in bounded chunks before the next request is read. The Runner owns
transport deadlines, including a sender that never finishes a line.

Invalid JSON/UTF-8, JSON deeper than 16 levels or exceeding 4,096 parsed nodes,
and non-finite numbers produce `-32700`; invalid requests/framing produce
`-32600`; unknown methods produce
`-32601`; invalid parameters and unknown tools produce `-32602`. Error messages
do not include request bodies. Valid string or numeric request IDs are preserved;
invalid/unrecoverable IDs use `null`. A defensive output-limit failure also uses
`null` so an oversized ID cannot make the error itself exceed the limit.

Empty stdin exits successfully. An unterminated final frame receives one error
and then exits successfully. Unpaired Unicode surrogates are not accepted in IDs
or echo text. Notifications, batches, streaming, and protocol extensions are not
supported. As in the existing authoring runtime, there is no additional local
initialization state machine. stdout is protocol-only; transport diagnostics use
stderr, and a broken transport exits with failure rather than pretending to have
delivered a response.

## Configure a Runner manually

On the selected Runner host, manually add a provider to its startup-bound
`runner.toml`. Replace every absolute-path placeholder with an existing path:

```toml
[[plugins.providers]]
id = "python-raw"
name = "Python Raw Example"
command = "/absolute/path/to/python3"
args = ["-B", "/absolute/path/to/webcodex/plugins/examples/python-raw/plugin.py"]
cwd = "/absolute/path/to/webcodex/plugins/examples/python-raw"
timeout_secs = 10
```

On Windows, TOML literal strings avoid backslash escaping, including spaces:

```toml
command = 'C:\Python312\python.exe'
args = ['-B', 'C:\path with spaces\webcodex\plugins\examples\python-raw\plugin.py']
cwd = 'C:\path with spaces\webcodex\plugins\examples\python-raw'
```

The Windows lines replace the corresponding fields in the provider block; they
are not a second complete provider. The example never edits configuration,
installs anything, creates credentials, or reloads providers.

## Author loop and authority

With an existing authorized token file, run these commands manually against the
exact Runner selected by the operator:

```text
webcodex plugin check --runner <runner> --plugin python-raw --token-file <token-file>
webcodex plugin reload --runner <runner> --token-file <token-file>
webcodex plugin list --runner <runner> --plugin python-raw --token-file <token-file>
webcodex plugin describe --runner <runner> --plugin python-raw --tool echo --token-file <token-file>
```

`check` starts and disposes a candidate without replacing the active providers;
continue only after it reports `ready=true`. `reload` rereads the Runner's config
and atomically replaces the **entire provider set**. There is no `reload --plugin`.
Old bindings become invalid after replacement; obtain a fresh binding via the
canonical `plugin_tool` describe → call flow. There is no `webcodex plugin call`
CLI command. Pass `{"text":"hello"}` as arguments when invoking `echo`.

Check/reload require `plugin:manage`, list/describe require `plugin:inspect`, and
invocation requires `plugin:invoke`. `--oauth-local-plugins` does not grant
management authority. Use existing credentials; this example does not mint or
upgrade them. See [Plugin operations](../../../docs/PLUGINS.md).

**Rust/Runner remains authoritative** for schema/profile admission, permissions,
exact bindings, payload/result validation, deadlines, process-tree lifecycle, and
uncertain effects. Python only declares this tool, validates its arguments, and
frames its known deterministic result. See the
[architecture boundary](../../../docs/architecture/native-tool-plugins.md).
