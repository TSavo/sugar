# std-core-string-predicates

This showcase closes the narrow std/core string-predicate gap named by the
main `std-core-showcase`: point-wise string, ASCII-char, literal iterator,
and bounded ASCII assertion-macro claims from Rust's own tests or doctest
source now lift as contract rows and verify through z3 string theory or the
corresponding arithmetic range checks for literal byte slices.

Claimed GOOD slice:

- `library/alloctests/tests/str.rs`: `test_starts_with`, `test_ends_with`,
  `test_contains`, `test_contains_char`, and the literal `str::len` row from
  `test_join_for_different_lengths_with_long_separator`.
- `library/coretests/tests/ascii.rs`: the literal `str::is_ascii` rows, the
  literal `chars().all/.any` and `bytes().is_ascii` rows from `test_is_ascii`,
  and bounded `assert_all!` / `assert_none!` ASCII class rows from the
  `test_is_ascii_*` functions.
- `library/core/src/char/methods.rs`: documented doctest point examples for
  `char::is_ascii`, `char::is_ascii_alphabetic`, and literal-bedrocked
  `char::is_alphabetic`.

The script also builds a BAD negative-control twin by contradicting one vendor
point assertion and one bounded `assert_all!` / `assert_none!` macro row. Those
BAD files are not vendor spec claims; they exist only to prove the lifted rows
are refused when z3 sees an UNSAT conjunction.

Conservative residuals:

- Unicode `char::is_alphabetic` lifts only when the char source bedrocks in
  written literals. Non-literal Unicode classification remains residual; z3
  string theory does not encode Rust's full Unicode `Alphabetic` table here.
- Non-literal receivers such as `let data = "..."; assert!(data.contains(...))`
  remain residual until the lifter tracks bindings.
- Iterator predicates that are not literal `chars()/bytes()` walks remain
  residual until the lifter tracks arbitrary sources and closure bodies.
- `assert_all!` / `assert_none!` with non-literal sources or unsupported
  predicate names remains residual. Other coretests custom assertion macros
  such as float, bit, range, chunk, and pattern helpers are not part of this
  exact literal-predicate slice.
