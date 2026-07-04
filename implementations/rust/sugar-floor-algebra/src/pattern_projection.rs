// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Pattern destructuring projection claims.
//
// `sugar-walk` owns the Rust `syn::Pat` walk, but projection construction
// belongs in the algebra representation. These helpers are the catalog-claim
// seam for #3197: callers lower the RHS `IrTerm` into `Rc<Term>`, ask the
// algebra to build the projection, then raise back to the existing wire shape.

use std::rc::Rc;

use sugar_ir_symbolic::{make_var, num, Term};

pub fn tuple_projection(receiver: Rc<Term>, index: usize) -> Rc<Term> {
    projection_with_marker("tuple_proj", receiver, format!(".{index}"))
}

pub fn tuple_struct_projection(receiver: Rc<Term>, index: usize) -> Rc<Term> {
    projection_with_marker("tuple_struct_proj", receiver, format!(".{index}"))
}

pub fn field_projection(receiver: Rc<Term>, field_name: &str) -> Rc<Term> {
    projection_with_marker("field", receiver, format!(".{field_name}"))
}

pub fn index_projection(receiver: Rc<Term>, index: usize) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: "index".to_string(),
        args: vec![
            receiver,
            num(i128::try_from(index).expect("pattern index fits ProofIR Int")),
        ],
    })
}

fn projection_with_marker(name: &str, receiver: Rc<Term>, marker: String) -> Rc<Term> {
    Rc::new(Term::Ctor {
        name: name.to_string(),
        args: vec![receiver, make_var(marker)],
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn root() -> Rc<Term> {
        make_var("root")
    }

    #[test]
    fn tuple_projection_uses_wire_compatible_marker_arg() {
        let projected = tuple_projection(root(), 2);
        let Term::Ctor { name, args } = projected.as_ref() else {
            panic!("tuple projection must be a ctor");
        };
        assert_eq!(name, "tuple_proj");
        assert_eq!(args.len(), 2);
        assert!(matches!(args[1].as_ref(), Term::Var { name } if name == ".2"));
    }

    #[test]
    fn field_projection_uses_existing_field_ctor_shape() {
        let projected = field_projection(root(), "x");
        let Term::Ctor { name, args } = projected.as_ref() else {
            panic!("field projection must be a ctor");
        };
        assert_eq!(name, "field");
        assert_eq!(args.len(), 2);
        assert!(matches!(args[1].as_ref(), Term::Var { name } if name == ".x"));
    }

    #[test]
    fn index_projection_uses_int_index_arg() {
        let projected = index_projection(root(), 3);
        let Term::Ctor { name, args } = projected.as_ref() else {
            panic!("index projection must be a ctor");
        };
        assert_eq!(name, "index");
        assert_eq!(args.len(), 2);
        assert!(matches!(args[1].as_ref(), Term::Const { .. }));
    }
}
