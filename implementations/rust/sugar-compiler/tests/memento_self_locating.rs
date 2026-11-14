// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3809: SourceMemento is already self-locating (file + function_name + span + CIDs).
//
// Collapsed MementoPath / SourceMementoAtPath (#3942–#3947).
//
// Asserts the locus display is derived on demand from the memento alone.
//
// No kit is driven here: the one whole-tree walk is mint's
// (`fold_enumerate_source_tree`, source_files -> universe; #7757). The typed
// `Kit::source_files` / `Kit::source_file` accessors this file once drove had
// no production caller and are deleted.

use libsugar::core::SourceMemento;
use sugar_compiler::tree::memento_locus_display;

#[test]
fn memento_locus_display_on_demand() {
    use libsugar::core::SrcSpan;

    let file_only = SourceMemento {
        file: "a.py".into(),
        function_name: String::new(),
        span: SrcSpan {
            start_line: 0,
            start_col: 0,
            end_line: 0,
            end_col: 0,
        },
        param_names: vec![],
        source_cid: String::new(),
        template_cid: String::new(),
    };
    assert_eq!(memento_locus_display(&file_only), "a.py");

    let with_fn = SourceMemento {
        file: "a.py".into(),
        function_name: "f".into(),
        span: SrcSpan {
            start_line: 2,
            start_col: 4,
            end_line: 2,
            end_col: 20,
        },
        param_names: vec![],
        source_cid: "blake3-512:cc".into(),
        template_cid: "blake3-512:dd".into(),
    };
    let d = memento_locus_display(&with_fn);
    assert!(d.starts_with("a.py[f"), "got {d}");
    assert!(d.contains("2:4-2:20"), "got {d}");
    eprintln!("RECEIPT locus display = {d}");
}
