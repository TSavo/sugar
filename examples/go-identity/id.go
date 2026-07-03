// Package sample is a Go library that DECLARES a Sugar boundary on one of
// its functions, the way Rust native annotations and Java authors do.
// The `//sugar:sugar(...)` doc-comment directive is the Go authoring idiom
// (analogous to `//go:generate` / `//go:build`). Running the authoring surface
// (`sugar mint` with the go-bind / go-contracts plugins) lifts ONLY the
// declared function and emits its contract -- the DECLARATION drives emission.
package sample

// Id is the boundary the author declares. The `identity` concept is realized
// in Go as `return x`; the lifted contract `post = result == x` discharges
// through the verifier spine AND the same `identity` concept materializes back
// into Go via sugar-realize-go-core. One function, both directions: the
// closed loop.
//
//sugar:sugar(concept="identity", library="builtin", version="1")
func Id(x int) int {
	return x
}

// Unannotated carries NO //sugar declaration, so the authoring surface does
// NOT lift it: the author did not ask for a contract here. (The bare `go`
// verify surface would still lift it; the authoring surface is declaration-
// gated.)
func Unannotated(y int) int {
	return y + 1
}
