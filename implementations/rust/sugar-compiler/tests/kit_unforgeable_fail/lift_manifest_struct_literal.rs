// `LiftManifest` fields are private (#3855): the only public builder is
// `LiftManifest::resolved(...)`. A struct-literal construction must fail to
// compile from a separate crate (trybuild), so casual field assignment cannot
// mint a manifest. Deliberately omits `method` too, so the compiler also
// reports the missing private field — there is no partial-forgery path.
fn main() {
    let _manifest = sugar_compiler::kit::LiftManifest {
        surface: "forged".to_string(),
        name: "forged".to_string(),
        dialect: libsugar::core::Dialect::Rust,
        command: vec!["/bin/false".to_string()],
        working_dir: None,
    };
}
