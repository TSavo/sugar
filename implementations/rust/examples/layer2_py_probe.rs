// SPDX-License-Identifier: MIT OR Apache-2.0
//
// One-shot probe: prints the JCS-encoded canonical bytes and BLAKE3-512
// hash of the same shapes that the Python Layer 2 adapter mints, so the
// Python conformance test can pin them as literals.
//
// NOT a permanent part of the workspace. Used to bootstrap cross-language
// hash agreement for implementations/python/sugar-lift-py-tests.

use std::rc::Rc;

use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};
use sugar_ir_symbolic::serialize::formula_to_value;
use sugar_ir_symbolic::{
    and_, atomic_, connective_, eq, make_var, num, str_const, Formula, Int, Term,
};

fn pin(label: &str, f: &Rc<Formula>) {
    let v = formula_to_value(f);
    let s = encode_jcs(&v);
    println!("---- {label} ----");
    println!("JCS: {s}");
    println!("HASH: {}", blake3_512_of(s.as_bytes()));
}

fn main() {
    // 1) Pattern 1 bounded loop: forall x:Int. (x>=0 AND x<100) -> (x>=0)
    let var = make_var("x");
    let lower = atomic_("\u{2265}", vec![var.clone(), num(0)]);
    let upper = atomic_("<", vec![var.clone(), num(100)]);
    let antecedent = and_(vec![lower, upper]);
    let inner = atomic_("\u{2265}", vec![var.clone(), num(0)]);
    let body = connective_("implies", vec![antecedent, inner]);
    let q = Rc::new(Formula::Quantifier {
        kind: "forall".into(),
        name: "x".into(),
        sort: Int(),
        body,
    });
    pin("pattern1_squares_are_nonneg", &q);

    // 2) Plain eq atomic: parse_int("42") = 42
    let lhs = Rc::new(Term::Ctor {
        name: "parse_int".into(),
        args: vec![str_const("42")],
    });
    let f = eq(lhs, num(42));
    pin("eq_parse_int_42", &f);

    // 3) Unicode object key/value JCS sanity
    let v = Value::object([("name", Value::string("\u{2265}".to_string()))]);
    println!("---- unicode_name_jcs ----");
    println!("JCS: {}", encode_jcs(&v));

    // 4) Empty BLAKE3-512 for python binding parity check
    println!("---- empty_blake3_512 ----");
    println!("HASH: {}", blake3_512_of(b""));
}
