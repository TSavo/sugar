# std/core Body-Guard Precondition Showcase

This showcase proves effects-free precondition seams from real Rust `core`
source. It harvests the already-proven Slice B mechanism across five direct
flat body guards in pinned `rust-src` 1.96.0. Producer methods are extracted
verbatim into minimal `impl` wrappers (not full-file symlinks), so ambient
std surface such as `is_digit → to_digit` does not mint extra claims.

The producer contracts are lifted from these real bodies:

```rust
pub const fn to_digit(self, radix: u32) -> Option<u32> {
    assert!(
        radix >= 2 && radix <= 36,
        "to_digit: invalid radix -- radix must be in the range 2 to 36 inclusive"
    );
    let value = if self > '9' && radix > 10 {
        const TO_UPPERCASE_MASK: u32 = !0b0010_0000;
        ((self as u32).wrapping_sub('A' as u32) & TO_UPPERCASE_MASK) + 10
    } else {
        (self as u32).wrapping_sub('0' as u32)
    };
    if value < radix { Some(value) } else { None }
}
```

```rust
pub const fn chunks(&self, chunk_size: usize) -> Chunks<'_, T> {
    assert!(chunk_size != 0, "chunk size must be non-zero");
    Chunks::new(self, chunk_size)
}
```

```rust
pub const fn chunks_exact(&self, chunk_size: usize) -> ChunksExact<'_, T> {
    assert!(chunk_size != 0, "chunk size must be non-zero");
    ChunksExact::new(self, chunk_size)
}
```

```rust
pub const fn rchunks(&self, chunk_size: usize) -> RChunks<'_, T> {
    assert!(chunk_size != 0, "chunk size must be non-zero");
    RChunks::new(self, chunk_size)
}
```

```rust
pub const fn rchunks_exact(&self, chunk_size: usize) -> RChunksExact<'_, T> {
    assert!(chunk_size != 0, "chunk size must be non-zero");
    RChunksExact::new(self, chunk_size)
}
```

The lifter treats each body guard as a flat FOL predicate over inputs. It does
not model panic, unwinding, abort, control flow, or effects. GOOD callers pass
`radix = 16` or `chunk_size = 2`; BAD callers pass `radix = 1` or
`chunk_size = 0`, so the implication verifier refuses those seams because the
caller cannot establish the callee precondition.

The witness axis reruns the matching vendor `#[should_panic]` tests:

- `coretests::char::test_to_digit_radix_too_low`
- `coretests::char::test_to_digit_radix_too_high`
- `alloctests::slice::test_chunks_iterator_0`
- `alloctests::slice::test_chunks_exact_iterator_0`
- `alloctests::slice::test_rchunks_iterator_0`
- `alloctests::slice::test_rchunks_exact_iterator_0`

Claimed: five std/core body-guard precondition seams, zero std source changes.

Not claimed: hidden `.expect()` panics, `assert_unsafe_precondition!`, match
arms, loop-carried guards, if-then-else strengthening, early-return reasoning,
or panic semantics.

Residuals:

- `slice::split_at` is skipped because the pinned body is `match
  self.split_at_checked(mid) { Some(pair) => pair, None => panic!("mid > len")
  }`, not a direct flat guard.
- `slice::split_at_unchecked` is skipped because its guard is
  `assert_unsafe_precondition!`, outside the already-proven Slice B surface.
- `slice::windows` is skipped because the panic is hidden behind
  `NonZero::new(size).expect("window size must be non-zero")`.
- `slice::array_windows` has a direct guard, but no matching pinned vendor
  `#[should_panic]` witness was found.
