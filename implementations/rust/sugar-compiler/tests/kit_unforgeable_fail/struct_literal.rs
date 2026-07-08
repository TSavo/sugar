// `Kit`'s fields are private: a struct-literal construction must fail to
// compile even from within the same crate's test binary (a separate crate
// for trybuild purposes), because `manifest`/`registry`/`kit_name` are not
// `pub`.
fn main() {
    let _kit = sugar_compiler::kit::Kit {
        manifest: unimplemented!(),
        registry: unimplemented!(),
        kit_name: "forged".to_string(),
    };
}
