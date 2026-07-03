# Go authoring surface: a Go library DECLARES a boundary and GETS a contract

This is the Go peer of the rust/java authoring surface. A Go library author
marks a function with the `//sugar:` doc-comment directive (the idiomatic Go
authoring marker, in the family of
`//go:generate` / `//go:build`), and that DECLARATION drives contract emission.

It closes the loop the verify-side and realize-side examples opened: one
function, `Id`, declares a boundary, GETS a contract, and that same contract
both **discharges through the verifier spine** and **materializes back into Go**
via `sugar-realize-go-core`.

## The declaration

```go
//sugar:sugar(concept="identity", library="builtin", version="1")
func Id(x int) int { return x }
```

`Unannotated` (no directive) is NOT lifted by the authoring surface: the author
did not ask for a contract there.

## The authoring surface (`.sugar/config.toml`)

Three `[[plugins]]`, mirroring rust's lift/realize split:

- `go-bind` (`layer = "library-bindings"`) emits the
  `library-sugar-binding-entry` DECLARATION catalog for each annotated function.
- `go-contracts` (`emit = "ir-document"`) emits the body-derived
  function-contracts + harvested callsites, gated on the declaration.
- `go-realize` (`kind = "realize"`) materializes the same concept back into
  native Go sugar through the Go kit.

The lift surfaces resolve to `sugar-lift-go-verify`, which emits different
IR per surface (so a function is not minted twice). The realize surface resolves
to `sugar-realize-go-core`.

## The closed loop

1. **Declare**: author writes `//sugar:sugar(concept="identity")` on `Id`.
2. **Get a contract**: `sugar mint` lifts ONLY `Id` (declaration-gated),
   emits its binding-entry + function-contract `post = result == x`, and
   auto-writes the `Id -> targetContractCid` bridge.
3. **Verify**: `sugar verify` reduces the harvested `Id(3) == 3` through the
   body `x` -> `3 == 3` -> z3 discharges -> signed witness, exit 0.
4. **Materialize**: `sugar-realize-go-core` realizes the same `identity`
   concept back into Go: `func Id(x int) int { return x }`, which `go build`s.

## Run it

```sh
cd implementations/go
go build -o /tmp/sugar-lift-go-verify ./cmd/sugar-lift-go-verify
cd sugar-realize-go-core && go build -o /tmp/sugar-realize-go ./cmd/sugar-realize-go
# point the manifests' command[0] at the built binaries (or put them on PATH), then:
sugar mint   --project examples/go-identity --out examples/go-identity --no-attest
sugar verify --project examples/go-identity --emit-witnesses /tmp/go-id-witnesses
```

The gating tests
(`sugar-cli/tests/cmd_authoring_surface_go.rs` for declare->contract->verify,
and `sugar-cli/tests/go_realize_materialize.rs` for materialize) reproduce
the loop.
