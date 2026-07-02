// SPDX-License-Identifier: Apache-2.0
//
// Charon LLBC ingest layer (#383). This module reads the JSON output
// of `charon rustc --no-dedup-serialized-ast`, navigates the structured
// LLBC body of a target function, and exposes the bits the lifter
// needs:
//
//   - the function name (from item_meta.name path elements)
//   - the local table (arg_count + per-local source name + type)
//   - the body block (statements with kind tags)
//
// We deliberately use `serde_json::Value` for navigation rather than
// mirroring Charon's full schema as typed Rust structs. Charon's
// schema is large (hundreds of variants across types/expressions/
// statements) and frequently extended; a typed mirror would either be
// brittle (versioned per Charon release) or massive (mirroring every
// variant we don't care about). The lifter only needs a small set of
// patterns — Switch::If + Abort, Assign + Use/BinaryOp/UnaryOp, the
// Local indices on Place::Local — so we walk the JSON dynamically and
// keep the schema dependency surface narrow.
//
// Per #368, this is the MIR-layer companion to the AST walk
// (sugar-walk's surface-AST pipeline). Both layers emit
// FunctionContractMemento objects to the same substrate; a single
// content_cid identifies the same logical contract across layers.

use std::path::Path;

use serde_json::Value;
use thiserror::Error;

#[derive(Debug, Error)]
pub enum LlbcError {
    #[error("LLBC file read failed: {0}")]
    Io(#[from] std::io::Error),
    #[error("LLBC JSON parse failed: {0}")]
    Json(#[from] serde_json::Error),
    #[error("LLBC schema mismatch at {path}: {detail}")]
    Schema { path: String, detail: String },
    #[error("function not found: {0}")]
    FunctionNotFound(String),
}

/// A loaded Charon CrateData. Wraps the raw JSON; navigation is via
/// the methods on this type and `LlbcFunction`.
#[derive(Debug, Clone)]
pub struct LlbcCrate {
    raw: Value,
}

impl LlbcCrate {
    pub fn from_path(path: impl AsRef<Path>) -> Result<Self, LlbcError> {
        let bytes = std::fs::read(path.as_ref())?;
        Self::from_slice(&bytes)
    }

    pub fn from_slice(bytes: &[u8]) -> Result<Self, LlbcError> {
        let raw: Value = serde_json::from_slice(bytes)?;
        Ok(Self { raw })
    }

    pub fn charon_version(&self) -> Option<&str> {
        self.raw.get("charon_version")?.as_str()
    }

    pub fn crate_name(&self) -> Option<&str> {
        self.raw.get("translated")?.get("crate_name")?.as_str()
    }

    /// The crate's type_decls array. Used by the LLBC lifter to resolve
    /// struct field names from `Field(Adt(id), idx)` projections. Returns
    /// `None` when the table is absent (e.g., test slices without types).
    pub fn type_decls_raw(&self) -> Option<&Value> {
        self.raw.get("translated")?.get("type_decls")
    }

    /// The `translated` sub-object of the CrateData. Used by callsite
    /// composition in `llbc_calls` to look up FunDecls by FunDeclId.
    pub fn raw_translated(&self) -> Option<&Value> {
        self.raw.get("translated")
    }

    /// Iterate all function declarations in the crate.
    pub fn fun_decls(&self) -> impl Iterator<Item = LlbcFunction<'_>> {
        self.raw
            .get("translated")
            .and_then(|t| t.get("fun_decls"))
            .and_then(|fns| fns.as_array())
            .into_iter()
            .flat_map(|arr| arr.iter())
            .map(|raw| LlbcFunction { raw })
    }

    /// Find a function by its trailing identifier in `item_meta.name`.
    /// Charon names are paths (e.g. `[Ident("test", 0), Ident("f", 0)]`);
    /// we match on the LAST `Ident` path element, which is the function
    /// name as written in source.
    pub fn function_by_name(&self, name: &str) -> Result<LlbcFunction<'_>, LlbcError> {
        self.fun_decls()
            .find(|f| f.fn_name().as_deref() == Some(name))
            .ok_or_else(|| LlbcError::FunctionNotFound(name.to_string()))
    }
}

/// One function declaration in the CrateData. Borrows from the parent
/// `LlbcCrate`'s JSON.
#[derive(Debug, Clone, Copy)]
pub struct LlbcFunction<'a> {
    raw: &'a Value,
}

impl<'a> LlbcFunction<'a> {
    /// Access the raw JSON for navigation to fields the typed
    /// accessors don't yet expose (generics, predicates, etc.).
    pub fn raw(&self) -> &'a Value {
        self.raw
    }

    /// The function's surface name (the last `Ident` element in the
    /// path). Returns None if the path is malformed.
    pub fn fn_name(&self) -> Option<String> {
        let elems = self.raw.get("item_meta")?.get("name")?.as_array()?;
        elems.iter().rev().find_map(|elem| {
            let ident = elem.get("Ident")?.as_array()?;
            let name = ident.first()?.as_str()?;
            Some(name.to_string())
        })
    }

    /// Number of input arguments (excludes the return local _0).
    pub fn arg_count(&self) -> Option<usize> {
        self.body_structured()?
            .get("locals")?
            .get("arg_count")?
            .as_u64()
            .map(|n| n as usize)
    }

    /// Iterate all locals in declaration order. Local 0 is the return,
    /// locals 1..=arg_count are formal parameters, the rest are temps.
    pub fn locals(&self) -> impl Iterator<Item = LlbcLocal<'a>> + use<'a> {
        self.body_structured()
            .and_then(|s| s.get("locals"))
            .and_then(|l| l.get("locals"))
            .and_then(|arr| arr.as_array())
            .into_iter()
            .flat_map(|arr| arr.iter())
            .map(|raw| LlbcLocal { raw })
    }

    /// The top-level body block's statements. Only available when the
    /// body is `Body::Structured` (LLBC). Returns an empty iterator
    /// for non-structured bodies (extern, intrinsic, trait method,
    /// etc.).
    pub fn statements(&self) -> impl Iterator<Item = LlbcStatement<'a>> + use<'a> {
        self.body_structured()
            .and_then(|s| s.get("body"))
            .and_then(|b| b.get("statements"))
            .and_then(|arr| arr.as_array())
            .into_iter()
            .flat_map(|arr| arr.iter())
            .map(|raw| LlbcStatement { raw })
    }

    /// Whether the function is declared `unsafe fn`. Reads
    /// `signature.is_unsafe` from the Charon JSON. Returns `false`
    /// when the field is absent (non-unsafe functions, or older Charon
    /// versions that don't emit the field).
    pub fn is_unsafe(&self) -> bool {
        match self
            .raw
            .get("signature")
            .and_then(|s| s.get("is_unsafe"))
            .and_then(|v| v.as_bool())
        {
            Some(is_unsafe) => is_unsafe,
            None => false,
        }
    }

    fn body_structured(&self) -> Option<&'a Value> {
        self.raw.get("body")?.get("Structured")
    }
}

/// One local declaration. Index 0 is the return local; 1..=arg_count
/// are formal parameters; the rest are temporaries introduced by
/// rustc's MIR lowering.
#[derive(Debug, Clone, Copy)]
pub struct LlbcLocal<'a> {
    raw: &'a Value,
}

impl<'a> LlbcLocal<'a> {
    pub fn index(&self) -> Option<u32> {
        self.raw.get("index")?.as_u64().map(|n| n as u32)
    }

    /// The local's surface name, if rustc preserved one. Formal
    /// parameters retain their source names (`x`, `y`, …); compiler-
    /// introduced temporaries are unnamed (None).
    pub fn name(&self) -> Option<&'a str> {
        self.raw.get("name")?.as_str()
    }

    /// The local's Charon type as raw JSON. The shape is always
    /// `{"Untagged": <ty>}` at the top level, matching Charon's
    /// `Ty` serialization. Use `sort_translate::ty_to_sort` to
    /// convert to a `Sort`.
    pub fn ty_raw(&self) -> Option<&'a Value> {
        self.raw.get("ty")
    }
}

/// One LLBC statement. The kind is the discriminator: a single-key
/// object (e.g. `{"Assign": [..]}`) for variants with payload, or a
/// bare string (e.g. `"Return"`) for unit variants.
#[derive(Debug, Clone, Copy)]
pub struct LlbcStatement<'a> {
    raw: &'a Value,
}

impl<'a> LlbcStatement<'a> {
    pub fn raw(&self) -> &'a Value {
        self.raw
    }

    pub fn kind(&self) -> Option<&'a Value> {
        self.raw.get("kind")
    }

    /// Discriminator for the statement's variant. `Some("Switch")` for
    /// `{"Switch": ..}`, `Some("Abort")` for `{"Abort": ..}`, etc. For
    /// unit variants serialized as a bare string (`"Return"`,
    /// `"Nop"`), returns the string.
    pub fn kind_tag(&self) -> Option<&'a str> {
        let kind = self.kind()?;
        if let Some(s) = kind.as_str() {
            return Some(s);
        }
        kind.as_object()?.keys().next().map(|k| k.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn fixture_path(name: &str) -> std::path::PathBuf {
        std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("tests")
            .join("fixtures")
            .join(name)
    }

    #[test]
    fn loads_clean_fixture_and_reads_charon_metadata() {
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        // Charon stamps a version in the JSON header; we don't
        // hard-code it (it bumps with Charon releases) but it must be
        // present and non-empty.
        let v = krate.charon_version().expect("charon_version present");
        assert!(!v.is_empty());
        assert_eq!(krate.crate_name(), Some("clean"));
    }

    #[test]
    fn finds_function_f_by_name() {
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        assert_eq!(f.fn_name().as_deref(), Some("f"));
        assert_eq!(f.arg_count(), Some(1));
    }

    #[test]
    fn formals_carry_source_names() {
        // Locals[0] is the return; locals[1] is the first formal,
        // which should be named "x" — Charon preserves source names
        // for formals.
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let locals: Vec<_> = f.locals().collect();
        assert!(locals.len() >= 2);
        assert_eq!(locals[0].index(), Some(0));
        assert_eq!(locals[0].name(), None, "return local has no source name");
        assert_eq!(locals[1].index(), Some(1));
        assert_eq!(
            locals[1].name(),
            Some("x"),
            "first formal carries its source name"
        );
    }

    #[test]
    fn body_statements_include_switch_and_abort() {
        // The if-panic pattern decomposes into:
        //   ... Assigns to compute the bool ...
        //   Switch::If(discr, then=[], else=continue)
        //   ... StorageDead ...
        //   Abort
        // We don't lift here; just verify the structural pattern is
        // visible in the parsed JSON.
        let krate = LlbcCrate::from_path(fixture_path("clean.llbc")).unwrap();
        let f = krate.function_by_name("f").unwrap();
        let kinds: Vec<&str> = f.statements().filter_map(|s| s.kind_tag()).collect();
        assert!(
            kinds.contains(&"Switch"),
            "expected Switch in body statements: {:?}",
            kinds
        );
        assert!(
            kinds.contains(&"Abort"),
            "expected Abort after Switch: {:?}",
            kinds
        );
    }
}
