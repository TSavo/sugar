use std::fs;
use std::path::Path;

// Migration ratchet for the "body is SugarBody" inversion.
//
// A raw `Expr` may be kept by a sugar as provenance: token keys, source text for a
// refusal, literal fast-path discrimination, pattern metadata, closure syntax, or
// method/function identity. It is a crime when `desugar` re-opens the factory against
// that raw syntax to obtain the body/receiver/operand/branch it should already carry.
//
// Current offender families are intentionally audited by the ignored tests below until
// they are migrated:
// - alias/binding resolvers: bound_path, const_path, cell_refcell
// - composite receiver adaptors: chain, zip, flatten, kmerge, iter_next, len, is_empty,
//   size_hint
// - term receiver/adaptor families: option_predicate, option_adaptor, float_refinement,
//   inspect, range_accessor, range_construct
// - control/decomp bodies: literal_iterator_quantifier, match_node, tuple_decomp
// - indexing: index container/index bodies
//
// When this test is unignored, the only remaining factory calls inside `desugar` should
// be in explicit bridge modules that construct a fresh synthetic expression as the new
// source site, not in ordinary sugars operating against stale child syntax.

fn factory_call_needles() -> &'static [&'static str] {
    &[
        "build_term(",
        "build_composite(",
        "build_constraint(",
        "build_assertion_surface(",
        "build_tuple_producer(",
    ]
}

fn desugar_block_for_owner(relative_path: &str, owner: &str) -> Option<(usize, String)> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join(relative_path);
    let text = fs::read_to_string(path).expect("read sugar source");
    let mut current_owner = None::<String>;
    let mut in_desugar = false;
    let mut depth = 0i32;
    let mut block = String::new();
    let mut start_line = 0usize;

    for (idx, line) in text.lines().enumerate() {
        let trimmed = line.trim_start();
        if let Some(rest) = trimmed.strip_prefix("impl Sugar for ") {
            current_owner = Some(rest.split('{').next().unwrap_or(rest).trim().to_string());
        }
        if !in_desugar
            && current_owner.as_deref() == Some(owner)
            && line.contains("fn desugar(&self")
        {
            in_desugar = true;
            depth = 0;
            block.clear();
            start_line = idx + 1;
        }
        if in_desugar {
            block.push_str(line);
            block.push('\n');
            depth += line.matches('{').count() as i32;
            depth -= line.matches('}').count() as i32;
            if depth == 0 && block.contains('{') {
                return Some((start_line, block));
            }
        }
    }
    None
}

fn assert_desugar_owner_uses_sugar_body(relative_path: &str, owner: &str) {
    let (start_line, block) = desugar_block_for_owner(relative_path, owner)
        .unwrap_or_else(|| panic!("missing `impl Sugar for {owner}` desugar in {relative_path}"));
    let offending_lines: Vec<String> = block
        .lines()
        .enumerate()
        .filter(|(_, line)| {
            factory_call_needles()
                .iter()
                .any(|needle| line.contains(needle))
        })
        .map(|(idx, line)| format!("{}: {}", start_line + idx, line.trim()))
        .collect();
    assert!(
        offending_lines.is_empty(),
        "This mother fucker right here has some hanky shit going on and needs to be shot: {owner} in {relative_path}:{start_line}. Migrate this owner to SugarBody.\n{}",
        offending_lines.join("\n")
    );
}

macro_rules! side_door_floor {
    ($name:ident, $path:literal, $owner:literal) => {
        #[test]
        fn $name() {
            assert_desugar_owner_uses_sugar_body($path, $owner);
        }
    };
}

side_door_floor!(
    aggregate_decomp_desugar_uses_upstream_sugar_body,
    "src/sugar/aggregate_decomp.rs",
    "AggregateDecompSugar"
);
side_door_floor!(
    bound_path_desugar_uses_upstream_sugar_body,
    "src/sugar/bound_path.rs",
    "BoundPathSugar"
);
side_door_floor!(
    cell_refcell_desugar_uses_upstream_sugar_body,
    "src/sugar/cell_refcell.rs",
    "CellRefCellSugar"
);
side_door_floor!(
    call_desugar_uses_upstream_sugar_body,
    "src/sugar/call.rs",
    "CallSugar"
);
side_door_floor!(
    chain_desugar_uses_upstream_sugar_body,
    "src/sugar/chain.rs",
    "ChainSugar"
);
side_door_floor!(
    const_path_desugar_uses_upstream_sugar_body,
    "src/sugar/const_path.rs",
    "ConstSugar"
);
side_door_floor!(
    const_composite_desugar_uses_upstream_sugar_body,
    "src/sugar/const_path.rs",
    "ConstCompositeSugar"
);
side_door_floor!(
    constraint_relation_macro_desugar_uses_upstream_sugar_body,
    "src/sugar/constraint.rs",
    "RelationMacroSugar"
);
side_door_floor!(
    flatten_desugar_uses_upstream_sugar_body,
    "src/sugar/flatten.rs",
    "FlattenSugar"
);
side_door_floor!(
    float_refinement_desugar_uses_upstream_sugar_body,
    "src/sugar/float_refinement.rs",
    "FloatRefinementSugar"
);
side_door_floor!(
    for_replay_desugar_uses_upstream_sugar_body,
    "src/sugar/for_replay.rs",
    "ForReplaySugar"
);
side_door_floor!(
    index_desugar_uses_upstream_sugar_body,
    "src/sugar/index.rs",
    "IndexSugar"
);
side_door_floor!(
    inspect_desugar_uses_upstream_sugar_body,
    "src/sugar/inspect.rs",
    "ResultInspectSugar"
);
side_door_floor!(
    is_empty_desugar_uses_upstream_sugar_body,
    "src/sugar/is_empty.rs",
    "IsEmptySugar"
);
side_door_floor!(
    iter_next_desugar_uses_upstream_sugar_body,
    "src/sugar/iter_next.rs",
    "IterNextSugar"
);
side_door_floor!(
    kmerge_desugar_uses_upstream_sugar_body,
    "src/sugar/kmerge.rs",
    "KMergeSugar"
);
side_door_floor!(
    len_desugar_uses_upstream_sugar_body,
    "src/sugar/len.rs",
    "LenSugar"
);
side_door_floor!(
    literal_iterator_quantifier_desugar_uses_upstream_sugar_body,
    "src/sugar/literal_iterator_quantifier.rs",
    "LiteralIteratorQuantifierSugar"
);
side_door_floor!(
    macro_assertion_surface_desugar_uses_upstream_sugar_body,
    "src/sugar/macro_assertion_surface.rs",
    "MacroAssertionSurfaceSugar"
);
side_door_floor!(
    map_desugar_uses_upstream_sugar_body,
    "src/sugar/map.rs",
    "MapTermSugar"
);
side_door_floor!(
    match_node_desugar_uses_upstream_sugar_body,
    "src/sugar/match_node.rs",
    "MatchValueTermSugar"
);
side_door_floor!(
    option_adaptor_desugar_uses_upstream_sugar_body,
    "src/sugar/option_adaptor.rs",
    "OptionAdaptorSugar"
);
side_door_floor!(
    option_predicate_desugar_uses_upstream_sugar_body,
    "src/sugar/option_predicate.rs",
    "OptionPredicateSugar"
);
side_door_floor!(
    range_accessor_desugar_uses_upstream_sugar_body,
    "src/sugar/range_accessor.rs",
    "RangeAccessorSugar"
);
side_door_floor!(
    range_construct_desugar_uses_upstream_sugar_body,
    "src/sugar/range_construct.rs",
    "RangeConstructSugar"
);
side_door_floor!(
    slice_accessor_desugar_uses_upstream_sugar_body,
    "src/sugar/slice_accessor.rs",
    "SliceAccessorSugar"
);
side_door_floor!(
    size_hint_desugar_uses_upstream_sugar_body,
    "src/sugar/size_hint.rs",
    "SizeHintTupleProducer"
);
side_door_floor!(
    tuple_decomp_desugar_uses_upstream_sugar_body,
    "src/sugar/tuple_decomp.rs",
    "TupleDecompSugar"
);
side_door_floor!(
    zip_desugar_uses_upstream_sugar_body,
    "src/sugar/zip.rs",
    "ZipSugar"
);
