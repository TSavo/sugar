// SPDX-License-Identifier: Apache-2.0
//
// Value tree for the JCS canonical-encoder input. Mirrors the C++
// `sugar::canonicalizer::Value` shape: scalars + array + object
// (object preserves insertion order; JCS sorts at emit time).

use std::sync::Arc;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ValueKind {
    Null,
    Bool,
    Integer,
    String,
    Array,
    Object,
}

#[derive(Debug, Clone)]
pub enum Value {
    Null,
    Bool(bool),
    // Integer carrier is i128: a wide Rust literal (u64::MAX, u128 within
    // i128 range, large isize) is an EXACT mathematical-Int constant. JCS
    // emits plain decimal digits (`to_string`), so any i128 canonicalizes
    // exactly and a small value's bytes are byte-identical to the former
    // i64 form (CID conserved).
    Integer(i128),
    String(String),
    Array(Vec<Arc<Value>>),
    Object(Vec<(String, Arc<Value>)>),
}

impl Value {
    pub fn kind(&self) -> ValueKind {
        match self {
            Value::Null => ValueKind::Null,
            Value::Bool(_) => ValueKind::Bool,
            Value::Integer(_) => ValueKind::Integer,
            Value::String(_) => ValueKind::String,
            Value::Array(_) => ValueKind::Array,
            Value::Object(_) => ValueKind::Object,
        }
    }

    pub fn null() -> Arc<Value> {
        Arc::new(Value::Null)
    }
    pub fn boolean(b: bool) -> Arc<Value> {
        Arc::new(Value::Bool(b))
    }
    pub fn integer(n: i128) -> Arc<Value> {
        Arc::new(Value::Integer(n))
    }
    pub fn string<S: Into<String>>(s: S) -> Arc<Value> {
        Arc::new(Value::String(s.into()))
    }
    pub fn array(items: Vec<Arc<Value>>) -> Arc<Value> {
        Arc::new(Value::Array(items))
    }
    pub fn object<I, K>(entries: I) -> Arc<Value>
    where
        I: IntoIterator<Item = (K, Arc<Value>)>,
        K: Into<String>,
    {
        let v: Vec<(String, Arc<Value>)> =
            entries.into_iter().map(|(k, v)| (k.into(), v)).collect();
        Arc::new(Value::Object(v))
    }
}
