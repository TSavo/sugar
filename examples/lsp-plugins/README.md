# Sugar LSP Language Plugins

Any language. Any binary. One RPC protocol. Red underlines in VS Code.

## How it works

1. You write a binary in **any language** that speaks NDJSON-over-stdio.
2. The binary handles three JSON-RPC methods: `initialize`, `parse`, `shutdown`.
3. You add one line to `.sugar/config.toml` pointing at your binary.
4. `sugar-lsp` spawns it, sends source files, gets back contract annotations, verifies them, and paints red underlines in the IDE.

That's it. No recompilation of the main LSP server. No Rust required. Your plugin can be written in Go, C#, C++, Zig, Python, JavaScript, OCaml: whatever parses your source language best.

## Plugin Protocol (`sugar-lsp-plugin/1`)

The main LSP server spawns your binary with `--rpc` appended, then speaks line-delimited JSON-RPC over stdin/stdout.

### 1. `initialize`

**Request:**
```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"client":{"name":"sugar-lsp","version":"0.1.0"},"protocol_version":"sugar-lsp-plugin/1"}}
```

**Response:**
```json
{"jsonrpc":"2.0","id":1,"result":{"name":"sugar-lsp-go","version":"0.1.0","capabilities":[]}}
```

### 2. `parse`

**Request:**
```json
{"jsonrpc":"2.0","id":2,"method":"parse","params":{"uri":"file:///project/src/lib.go","text":"package main\n..."}}
```

**Response:**
```json
{"jsonrpc":"2.0","id":2,"result":{"annotations":[
  {"function_name":"ParseInt","kind":"implement","target_cid":"bafy...js-parseInt-v24","range":{"start":{"line":5,"character":0},"end":{"line":10,"character":1}}},
  {"function_name":"ValidateEmail","kind":"contract","range":{"start":{"line":15,"character":0},"end":{"line":20,"character":1}}}
]}}
```

Annotation kinds:
- `"implement"`: function bound to a contract CID. Must include `target_cid`.
- `"contract"`: function declares its own contract.
- `"verify"`: function marked for verification.

### 3. `shutdown`

**Request:**
```json
{"jsonrpc":"2.0","id":3,"method":"shutdown"}
```

**Response:**
```json
{"jsonrpc":"2.0","id":3,"result":null}
```

After responding, the plugin should exit cleanly.

## Configuring a plugin

### Option A: Direct binary in `.sugar/config.toml`

```toml
[server]
backend = "sugar"

[[language]]
name = "go"
extensions = [".go"]
plugin = "sugar-lsp-go"
```

The plugin binary must be in `PATH`.

### Option B: Plugin manifest (supports args, working dir)

Create `.sugar/lsp/go/manifest.toml`:

```toml
name = "sugar-lsp-go"
command = ["sugar-lsp-go"]
# optional:
# working_dir = "./subproject"
```

Then reference by name in `.sugar/config.toml`:

```toml
[[language]]
name = "go"
extensions = [".go"]
plugin = "go"
```

Manifests are also searched in `~/.config/sugar/lsp/<name>/manifest.toml` for user-global plugins.

```toml
[[language]]
name = "rust"
extensions = [".rs"]
plugin = "rust"
```

The Rust entry is not special. It follows the same manifest-backed plugin route
as Go, C#, C++, Zig, or any third-party language helper.

## Examples in this directory

| Language | File | Build command |
|---|---|---|
| Rust | `rust/src/main.rs` | `cargo build --release` |
| Go | `go/main.go` | `go build -o sugar-lsp-go main.go` |
| C# | `csharp/Program.cs` | `dotnet publish -c Release` |
| C++ | `cpp/main.cpp` | `g++ -std=c++17 -o sugar-lsp-cpp main.cpp` |
| Zig | `zig/main.zig` | `zig build-exe main.zig -o sugar-lsp-zig` |

Each example is ~100-150 lines, zero dependencies (or minimal stdlib-only deps), and implements the full plugin protocol.

## Source annotation conventions per language

Plugins should detect whatever syntax makes sense for the host language. There is no mandated syntax: the plugin owns the surface. Common patterns:

**Go:**
```go
//sugar:implement bafy...js-parseInt-v24
func ParseInt(s string) int { ... }
```

**C#:**
```csharp
//sugar:implement bafy...js-parseInt-v24
public int ParseInt(string s) { ... }
```

**C++:**
```cpp
// sugar:implement bafy...js-parseInt-v24
int parse_int(const std::string& s) { ... }
```

**Zig:**
```zig
//sugar:implement bafy...js-parseInt-v24
fn parseInt(s: []const u8) i32 { ... }
```

**Rust plugin** (attributes are ordinary Rust syntax consumed by the plugin):
```rust
#[ensures(result == parse_int_spec(s))]
fn parse_int(s: &str) -> i32 { ... }
```

## Why this architecture?

- **Native parsers:** A Go plugin uses `go/ast`. A C# plugin uses Roslyn. A Python plugin uses `ast`. Each uses the best parser for its language.
- **No lock-in:** The main LSP server is just a coordinator. If you don't like it, write your own. The plugin protocol is the boundary.
- **Language communities own their plugins:** The Go team maintains the Go plugin. The Zig team maintains the Zig plugin. Sugar just verifies the IR.
- **Zero-downtime addition:** Add a new language without restarting the main LSP server. Just edit `config.toml` and reload the window.

## Minimal viable plugin

The smallest possible plugin, in Python:

```python
#!/usr/bin/env python3
import sys, json

if "--rpc" not in sys.argv:
    sys.exit("Usage: plugin.py --rpc")

for line in sys.stdin:
    req = json.loads(line)
    id = req.get("id")
    method = req.get("method", "")

    if method == "initialize":
        print(json.dumps({"jsonrpc": "2.0", "id": id, "result": {"name": "my-plugin", "version": "0.1.0"}}), flush=True)
    elif method == "parse":
        text = req["params"]["text"]
        annotations = []
        for i, line_text in enumerate(text.split("\n")):
            if "#sugar:implement" in line_text:
                cid = line_text.split()[-1]
                annotations.append({"function_name": "foo", "kind": "implement", "target_cid": cid, "range": {"start": {"line": i, "character": 0}, "end": {"line": i+1, "character": 0}}})
        print(json.dumps({"jsonrpc": "2.0", "id": id, "result": {"annotations": annotations}}), flush=True)
    elif method == "shutdown":
        print(json.dumps({"jsonrpc": "2.0", "id": id, "result": None}), flush=True)
        break
```

That's it. 25 lines. Add it to `config.toml` and you have contract tracking in VS Code for your language.
