// SPDX-License-Identifier: MIT OR Apache-2.0

use sugar_ir_types::panic_freedom;

#[test]
fn panic_freedom_constants_are_the_bare_wire_tokens() {
    assert_eq!(panic_freedom::IS_OK, "is_ok");
    assert_eq!(panic_freedom::IS_ERR, "is_err");
    assert_eq!(panic_freedom::IS_SOME, "is_some");
    assert_eq!(panic_freedom::IS_NONE, "is_none");
    assert_eq!(panic_freedom::CF_GUARDED, "cf_guarded");
    assert_eq!(panic_freedom::CF_ITE, "cf_ite");
    assert_eq!(panic_freedom::METHOD_UNWRAP, "method:unwrap");
    assert_eq!(panic_freedom::METHOD_EXPECT, "method:expect");
    assert_eq!(panic_freedom::METHOD_UNWRAP_ERR, "method:unwrap_err");
    // The one cross-kit token still carrying concept: (Python emits it; bared in
    // the deferred Python pass).
    assert_eq!(
        panic_freedom::RUNTIME_FAILURE_SITE,
        "concept:panic-freedom.leaf.runtime-failure-site"
    );
}

#[test]
fn rust_panic_freedom_tokens_carry_no_concept_prefix() {
    // RUNTIME_FAILURE_SITE is intentionally excluded: it is the cross-kit Python
    // token, bared in lockstep during the deferred Python pass.
    for token in [
        panic_freedom::IS_OK,
        panic_freedom::IS_ERR,
        panic_freedom::IS_SOME,
        panic_freedom::IS_NONE,
        panic_freedom::CF_GUARDED,
        panic_freedom::CF_ITE,
        panic_freedom::METHOD_UNWRAP,
        panic_freedom::METHOD_EXPECT,
        panic_freedom::METHOD_UNWRAP_ERR,
    ] {
        assert!(
            !token.contains("concept:"),
            "rust panic-freedom token must not carry a concept: prefix: {token}"
        );
    }
}
