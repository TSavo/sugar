// SPDX-License-Identifier: Apache-2.0
//
// Typed proof-graph helpers. A .proof catalog is constructed in exactly one
// direction:
//
//   atoms -> bodies -> mementos -> graph -> catalog CID maps
//
// Callers do not assemble `{cid -> bytes}` maps. They construct typed mementos;
// this module derives, validates, and lowers the graph at the serialization edge.

use std::borrow::Borrow;
use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fmt;
use std::ops::Deref;
use std::sync::Arc;

use serde::{Serialize, Serializer};
use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, CanonicalizerError, Value};

use crate::sign::{
    ed25519_pubkey_string, ed25519_sign_string, ed25519_verify_string, Ed25519Seed, Signature,
};
use crate::typed_member::{MemberError, MemberKind};

#[derive(Debug, thiserror::Error)]
pub enum PlanMemberBytesError {
    #[error("plan member bytes not JSON: {0}")]
    InvalidJson(serde_json::Error),
    #[error("plan member kind is not `plan-memento`")]
    WrongKind,
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct AtomCid(String);

impl AtomCid {
    fn from_bytes(bytes: &[u8]) -> Self {
        Self(blake3_512_of(bytes))
    }

    /// Wrap a raw string as an AtomCid without hash validation.
    /// Used by typed-member parsing where the CID came off the wire.
    pub(crate) fn from_raw(s: impl Into<String>) -> Self {
        Self(s.into())
    }

    pub fn try_parse(cid: String) -> Result<Self, String> {
        if is_blake3_512_cid(&cid) {
            Ok(Self(cid))
        } else {
            Err(cid)
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for AtomCid {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl Borrow<str> for AtomCid {
    fn borrow(&self) -> &str {
        self.as_str()
    }
}

impl Deref for AtomCid {
    type Target = str;

    fn deref(&self) -> &Self::Target {
        self.as_str()
    }
}

impl fmt::Display for AtomCid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct ContractBodyCid(String);

impl ContractBodyCid {
    fn from_bytes(bytes: &[u8]) -> Self {
        Self(blake3_512_of(bytes))
    }

    /// Wrap a raw string as a ContractBodyCid without hash validation.
    /// Used by typed-member parsing where the CID came off the wire.
    pub(crate) fn from_raw(s: impl Into<String>) -> Self {
        Self(s.into())
    }

    pub fn try_parse(cid: String) -> Result<Self, String> {
        if is_blake3_512_cid(&cid) {
            Ok(Self(cid))
        } else {
            Err(cid)
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for ContractBodyCid {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl Borrow<str> for ContractBodyCid {
    fn borrow(&self) -> &str {
        self.as_str()
    }
}

impl Deref for ContractBodyCid {
    type Target = str;

    fn deref(&self) -> &Self::Target {
        self.as_str()
    }
}

impl fmt::Display for ContractBodyCid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct MementoCid(String);

impl MementoCid {
    fn new(cid: String) -> Self {
        assert!(
            is_blake3_512_cid(&cid),
            "memento CID must be a blake3-512 CID with 128 hex characters, got `{cid}`"
        );
        Self(cid)
    }

    fn from_bytes(bytes: &[u8]) -> Self {
        Self::new(blake3_512_of(bytes))
    }

    /// Fallible constructor: returns `Ok` only when `cid` carries the
    /// `blake3-512:` tag plus a 128-hex-character digest. Used by typed-member
    /// parsing to surface a typed error instead of panicking.
    pub fn try_parse(cid: String) -> Result<Self, String> {
        if is_blake3_512_cid(&cid) {
            Ok(Self(cid))
        } else {
            Err(cid)
        }
    }

    fn from_layered_envelope(bytes: &[u8], type_name: &str) -> Self {
        let value: Json = serde_json::from_slice(bytes)
            .unwrap_or_else(|err| panic!("{type_name} bytes must be canonical JSON: {err}"));
        let envelope = value
            .get("envelope")
            .unwrap_or_else(|| panic!("{type_name} must be a layered memento with `envelope`"));
        let canonical = json_to_canonical_value(envelope);
        Self::new(blake3_512_of(encode_jcs(&canonical).as_bytes()))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl AsRef<str> for MementoCid {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl Borrow<str> for MementoCid {
    fn borrow(&self) -> &str {
        self.as_str()
    }
}

impl Deref for MementoCid {
    type Target = str;

    fn deref(&self) -> &Self::Target {
        self.as_str()
    }
}

impl fmt::Display for MementoCid {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

macro_rules! serialize_cid_as_str {
    ($ty:ty) => {
        impl Serialize for $ty {
            fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
            where
                S: Serializer,
            {
                serializer.serialize_str(self.as_str())
            }
        }
    };
}

serialize_cid_as_str!(AtomCid);
serialize_cid_as_str!(ContractBodyCid);
serialize_cid_as_str!(MementoCid);

fn is_blake3_512_cid(cid: &str) -> bool {
    sugar_canonicalizer::is_blake3_512_cid(cid)
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct ContractMementoRef {
    cid: MementoCid,
}

impl ContractMementoRef {
    pub fn new(cid: impl Into<String>) -> Self {
        Self {
            cid: MementoCid::new(cid.into()),
        }
    }

    pub fn cid(&self) -> &MementoCid {
        &self.cid
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct AuthorityMementoRef {
    cid: MementoCid,
}

impl AuthorityMementoRef {
    pub fn new(cid: impl Into<String>) -> Self {
        Self {
            cid: MementoCid::new(cid.into()),
        }
    }

    pub fn as_str(&self) -> &str {
        self.cid.as_str()
    }
}

fn json_to_canonical_value(value: &Json) -> Arc<Value> {
    json_to_canonical_value_at(value, "$").unwrap_or_else(|err| panic!("{err}"))
}

fn json_to_canonical_value_at(value: &Json, path: &str) -> Result<Arc<Value>, CanonicalizerError> {
    match value {
        Json::Null => Ok(Value::null()),
        Json::Bool(v) => Ok(Value::boolean(*v)),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                Ok(Value::integer(i128::from(i)))
            } else if let Some(u) = n.as_u64() {
                Ok(Value::integer(i128::from(u)))
            } else {
                Err(CanonicalizerError::Other(format!(
                    "non-integer JSON number at {path}: {n}"
                )))
            }
        }
        Json::String(s) => Ok(Value::string(s.clone())),
        Json::Array(items) => {
            let mut out = Vec::with_capacity(items.len());
            for (idx, item) in items.iter().enumerate() {
                out.push(json_to_canonical_value_at(
                    item,
                    &canonical_array_path(path, idx),
                )?);
            }
            Ok(Value::array(out))
        }
        Json::Object(map) => {
            let mut out = Vec::with_capacity(map.len());
            for (key, value) in map {
                out.push((
                    key.clone(),
                    json_to_canonical_value_at(value, &canonical_object_path(path, key))?,
                ));
            }
            Ok(Value::object(out))
        }
    }
}

fn canonical_array_path(parent: &str, idx: usize) -> String {
    format!("{parent}[{idx}]")
}

fn canonical_object_path(parent: &str, key: &str) -> String {
    if !key.is_empty() && key.chars().all(|c| c == '_' || c.is_ascii_alphanumeric()) {
        format!("{parent}.{key}")
    } else {
        let quoted = serde_json::to_string(key).expect("JSON string key serialization");
        format!("{parent}[{quoted}]")
    }
}

#[derive(Clone, Debug)]
pub struct FlatAtom {
    value: Arc<Value>,
    bytes: Vec<u8>,
    cid: AtomCid,
}

impl FlatAtom {
    pub fn new(value: Arc<Value>) -> Self {
        let bytes = encode_jcs(&value).into_bytes();
        let cid = AtomCid::from_bytes(&bytes);
        Self { value, bytes, cid }
    }

    pub fn result_eq_int(value: i64) -> Self {
        Self::new(Value::object([
            ("kind", Value::string("atomic")),
            ("name", Value::string("=")),
            (
                "args",
                Value::array(vec![
                    Value::object([
                        ("kind", Value::string("var")),
                        ("name", Value::string("result")),
                    ]),
                    Value::object([
                        ("kind", Value::string("const")),
                        ("value", Value::integer(i128::from(value))),
                    ]),
                ]),
            ),
        ]))
    }

    pub fn empty_metadata() -> Self {
        Self::new(Value::object(Vec::<(&str, Arc<Value>)>::new()))
    }

    pub fn cid(&self) -> &AtomCid {
        &self.cid
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn value(&self) -> &Arc<Value> {
        &self.value
    }
}

#[derive(Clone, Debug)]
pub struct AtomMemento {
    atom: FlatAtom,
}

impl AtomMemento {
    pub fn new(atom: &FlatAtom) -> Self {
        Self { atom: atom.clone() }
    }

    pub fn atom(&self) -> &FlatAtom {
        &self.atom
    }

    pub fn value(&self) -> Arc<Value> {
        Value::object([
            ("kind", Value::string("atom-memento")),
            ("atomCid", Value::string(self.atom.cid().as_str())),
        ])
    }
}

#[derive(Clone, Debug)]
pub struct ContractBody {
    atoms: Vec<AtomMemento>,
    bytes: Vec<u8>,
    cid: ContractBodyCid,
}

impl ContractBody {
    pub fn new(post: &AtomMemento) -> Self {
        Self::from_slots(vec![("post", post)])
    }

    pub fn new_inv(inv: &AtomMemento) -> Self {
        Self::from_slots(vec![("inv", inv)])
    }

    pub fn from_slots(slots: Vec<(&str, &AtomMemento)>) -> Self {
        assert!(
            !slots.is_empty(),
            "contract body must point at at least one formula atom"
        );
        let body_slots = slots
            .iter()
            .map(|(slot, atom)| ((*slot).to_string(), atom.value()))
            .collect::<Vec<_>>();
        let value = Value::object([
            (
                "header",
                Value::object([
                    ("kind", Value::string("contract-body")),
                    ("schemaVersion", Value::string("1")),
                ]),
            ),
            ("body", Value::object(body_slots)),
        ]);
        let bytes = encode_jcs(&value).into_bytes();
        let cid = ContractBodyCid::from_bytes(&bytes);
        Self {
            atoms: slots.iter().map(|(_, atom)| (*atom).clone()).collect(),
            bytes,
            cid,
        }
    }

    pub fn cid(&self) -> &ContractBodyCid {
        &self.cid
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub fn atoms(&self) -> impl Iterator<Item = &FlatAtom> {
        self.atoms.iter().map(AtomMemento::atom)
    }
}

#[derive(Clone, Debug)]
struct MemberRecord {
    cid: MementoCid,
    bytes: Vec<u8>,
}

impl MemberRecord {
    fn new(cid: MementoCid, bytes: Vec<u8>) -> Self {
        Self { cid, bytes }
    }

    fn from_whole_bytes(bytes: Vec<u8>, type_name: &str, expected_kinds: &[&str]) -> Self {
        validate_memento_kind(&bytes, type_name, expected_kinds);
        Self::new(MementoCid::from_bytes(&bytes), bytes)
    }

    fn from_layered_envelope(bytes: Vec<u8>, type_name: &str) -> Self {
        Self::new(MementoCid::from_layered_envelope(&bytes, type_name), bytes)
    }
}

macro_rules! whole_byte_memento {
    ($name:ident, [$($kind:literal),+ $(,)?]) => {
        #[derive(Clone, Debug)]
        pub struct $name {
            record: MemberRecord,
        }

        impl $name {
            pub fn new(bytes: Vec<u8>) -> Self {
                Self {
                    record: MemberRecord::from_whole_bytes(
                        bytes,
                        stringify!($name),
                        &[$($kind),+],
                    ),
                }
            }

            pub fn cid(&self) -> &MementoCid {
                &self.record.cid
            }

            pub fn bytes(&self) -> &[u8] {
                &self.record.bytes
            }
        }
    };
}

fn validate_memento_kind(bytes: &[u8], type_name: &str, expected_kinds: &[&str]) {
    let value: Json = serde_json::from_slice(bytes)
        .unwrap_or_else(|err| panic!("{type_name} bytes must be JSON: {err}"));
    let kind = value
        .pointer("/header/kind")
        .or_else(|| value.pointer("/envelope/header/kind"))
        .or_else(|| value.pointer("/evidence/kind"))
        .and_then(Json::as_str)
        .unwrap_or_else(|| panic!("{type_name} must carry a memento kind"));
    assert!(
        expected_kinds.iter().any(|expected| *expected == kind),
        "{type_name} expected kind {:?}, got `{kind}`",
        expected_kinds
    );
}

macro_rules! layered_memento {
    ($name:ident, [$($kind:literal),+ $(,)?]) => {
        #[derive(Clone, Debug)]
        pub struct $name {
            record: MemberRecord,
        }

        impl $name {
            pub fn new(bytes: Vec<u8>) -> Self {
                validate_memento_kind(&bytes, stringify!($name), &[$($kind),+]);
                Self {
                    record: MemberRecord::from_layered_envelope(bytes, stringify!($name)),
                }
            }

            pub fn cid(&self) -> &MementoCid {
                &self.record.cid
            }

            pub fn bytes(&self) -> &[u8] {
                &self.record.bytes
            }
        }
    };
}

layered_memento!(AuthorityMemento, ["authority"]);
layered_memento!(BridgeMemento, ["bridge"]);
layered_memento!(ClaimContractMemento, ["contract"]);
layered_memento!(EffectSiteAnnotationMemento, ["effect-site-annotation"]);
layered_memento!(ImplicationMemento, ["implication"]);
layered_memento!(ProofRunMemento, ["proof-run"]);
layered_memento!(StageReceiptMemento, ["stage-receipt"]);
layered_memento!(WitnessClaimMemento, ["witness"]);

impl From<&ClaimContractMemento> for ContractMementoRef {
    fn from(memento: &ClaimContractMemento) -> Self {
        Self {
            cid: memento.cid().clone(),
        }
    }
}

impl From<&AuthorityMemento> for AuthorityMementoRef {
    fn from(memento: &AuthorityMemento) -> Self {
        Self {
            cid: memento.cid().clone(),
        }
    }
}

whole_byte_memento!(LibrarySugarBindingMemento, ["library-sugar-binding-entry"]);
whole_byte_memento!(AssertionSurfaceMemento, ["assertion-surface-memento"]);
whole_byte_memento!(FactoryWalkMemento, ["factory-walk-memento"]);
whole_byte_memento!(PlanMemento, ["plan-memento"]);
whole_byte_memento!(SourceMemento, ["source-memento"]);
whole_byte_memento!(WitnessMemento, ["witness-memento"]);

#[derive(Clone, Debug)]
pub struct ContractMemento {
    name: String,
    body: ContractBody,
    metadata: AtomMemento,
    record: MemberRecord,
}

impl ContractMemento {
    pub fn new(name: impl Into<String>, body: &ContractBody, signer_seed: Ed25519Seed) -> Self {
        Self::new_at(name, body, signer_seed, "2026-04-30T00:00:00.000Z")
    }

    pub fn new_at(
        name: impl Into<String>,
        body: &ContractBody,
        signer_seed: Ed25519Seed,
        declared_at: &str,
    ) -> Self {
        Self::new_with_metadata_at(
            name,
            body,
            &AtomMemento::new(&FlatAtom::empty_metadata()),
            signer_seed,
            declared_at,
        )
    }

    pub fn new_with_metadata_at(
        name: impl Into<String>,
        body: &ContractBody,
        metadata: &AtomMemento,
        signer_seed: Ed25519Seed,
        declared_at: &str,
    ) -> Self {
        Self::new_with_metadata_and_header_fields_at(
            name,
            body,
            metadata,
            signer_seed,
            declared_at,
            Vec::new(),
        )
    }

    pub fn new_obligation_with_metadata_at(
        name: impl Into<String>,
        body: &ContractBody,
        metadata: &AtomMemento,
        signer_seed: Ed25519Seed,
        declared_at: &str,
    ) -> Self {
        Self::new_with_metadata_and_header_fields_at(
            name,
            body,
            metadata,
            signer_seed,
            declared_at,
            vec![(
                "invVerification".to_string(),
                Value::string("obligation".to_string()),
            )],
        )
    }

    fn new_with_metadata_and_header_fields_at(
        name: impl Into<String>,
        body: &ContractBody,
        metadata: &AtomMemento,
        signer_seed: Ed25519Seed,
        declared_at: &str,
        extra_header_fields: Vec<(String, Arc<Value>)>,
    ) -> Self {
        let name = name.into();
        let mut header_preimage_fields: Vec<(String, Arc<Value>)> = vec![
            ("kind".into(), Value::string("contract")),
            ("name".into(), Value::string(name.clone())),
            ("bodyCid".into(), Value::string(body.cid().as_str())),
        ];
        header_preimage_fields.extend(extra_header_fields.iter().cloned());
        let header_preimage = Value::object(header_preimage_fields);
        let header_cid = blake3_512_of(encode_jcs(&header_preimage).as_bytes());
        let mut header_fields: Vec<(String, Arc<Value>)> = vec![
            ("schemaVersion".into(), Value::string("2")),
            ("kind".into(), Value::string("contract")),
            ("cid".into(), Value::string(header_cid)),
            ("name".into(), Value::string(name.clone())),
            ("contractName".into(), Value::string(name.clone())),
            ("bodyCid".into(), Value::string(body.cid().as_str())),
        ];
        header_fields.extend(extra_header_fields);
        let header = Value::object(header_fields);
        let signing_message =
            Value::object([("header", header.clone()), ("metadata", metadata.value())]);
        let signature = ed25519_sign_string(&signer_seed, encode_jcs(&signing_message).as_bytes());
        let envelope = Value::object([
            ("signer", Value::string(ed25519_pubkey_string(&signer_seed))),
            ("declaredAt", Value::string(declared_at.to_string())),
            ("signature", Value::string(signature)),
        ]);
        let value = Value::object([
            ("envelope", envelope.clone()),
            ("header", header),
            ("metadata", metadata.value()),
        ]);
        let bytes = encode_jcs(&value).into_bytes();
        let cid = MementoCid::new(blake3_512_of(encode_jcs(&envelope).as_bytes()));
        Self {
            name,
            body: body.clone(),
            metadata: metadata.clone(),
            record: MemberRecord::new(cid, bytes),
        }
    }

    pub fn name(&self) -> &str {
        &self.name
    }

    pub fn body(&self) -> &ContractBody {
        &self.body
    }

    pub fn metadata(&self) -> &AtomMemento {
        &self.metadata
    }

    pub fn cid(&self) -> &MementoCid {
        &self.record.cid
    }

    pub fn bytes(&self) -> &[u8] {
        &self.record.bytes
    }
}

impl From<&ContractMemento> for ContractMementoRef {
    fn from(memento: &ContractMemento) -> Self {
        Self {
            cid: memento.cid().clone(),
        }
    }
}

/// A contract behavior read out of the graph: its name, the body CID it
/// resolves to, and its own member CID. The behavior IS `body_cid` -- a rename
/// keeps it, a body change moves it.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ContractEntry {
    pub cid: String,
    pub name: String,
    pub body_cid: String,
}

/// The envelope identity a graph needs to become a signed `.proof`: everything
/// a catalog carries that is NOT graph content. `read` recovers these from the
/// bytes; `write` requires them because the bare graph does not hold them.
#[derive(Clone, Debug)]
pub struct ProofIdentity {
    pub name: String,
    pub version: String,
    pub binary_cid: Option<String>,
    pub metadata: Option<BTreeMap<String, String>>,
    pub signer_cid: String,
    pub signer_seed: Ed25519Seed,
    pub declared_at: String,
}

/// A typed, read-only view of a member memento. The graph resolves the kind and
/// body pointer out of the member bytes so consumers read members out loud
/// without hand-parsing the catalog.
pub struct MemberView<'a> {
    cid: &'a MementoCid,
    bytes: &'a [u8],
}

impl<'a> MemberView<'a> {
    pub fn cid(&self) -> &MementoCid {
        self.cid
    }

    /// Raw member bytes (JCS-JSON), for verbatim rendering.
    pub fn bytes(&self) -> &[u8] {
        self.bytes
    }

    /// The member's kind discriminator. Covers all envelope shapes:
    ///
    /// * v1.2 layered: `header.kind`
    /// * lean header/body: `header.kind`
    /// * v1.1 flat: `evidence.kind`
    pub fn kind(&self) -> Option<MemberKind> {
        let v: Json = serde_json::from_slice(self.bytes).ok()?;
        raw_member_kind(&v).and_then(|kind| kind.parse().ok())
    }

    /// The body CID this member points at, if it carries one (contracts).
    pub fn body_cid(&self) -> Option<String> {
        let v: Json = serde_json::from_slice(self.bytes).ok()?;
        v.pointer("/header/bodyCid")
            .and_then(Json::as_str)
            .map(str::to_string)
    }

    /// Look up a string-valued kind-specific field from the body or header,
    /// regardless of memento shape. Mirrors `memento_body_field` from the
    /// verifier so consumers need no envelope-shape knowledge:
    ///
    /// * v1.2 layered (`envelope` present): `header.<name>`, then
    ///   `metadata.<name>`, then `envelope.header.<name>`.
    /// * lean header/body (no `envelope`, but `header` or `body` present):
    ///   `header.<name>`, then `body.<name>`, then `metadata.<name>`.
    /// * v1.1 flat: `evidence.body.<name>`.
    ///
    /// Returns `None` when the field is absent or its value is not a string.
    pub fn field(&self, name: &str) -> Option<String> {
        let v: Json = serde_json::from_slice(self.bytes).ok()?;
        let found = if v.get("envelope").is_some() {
            v.pointer("/header")
                .and_then(|h| h.get(name))
                .or_else(|| v.pointer("/metadata").and_then(|m| m.get(name)))
                .or_else(|| v.pointer("/envelope/header").and_then(|h| h.get(name)))
                .or_else(|| v.pointer("/envelope/metadata").and_then(|m| m.get(name)))
        } else if v.get("header").is_some() || v.get("body").is_some() {
            v.pointer("/header")
                .and_then(|h| h.get(name))
                .or_else(|| v.pointer("/body").and_then(|b| b.get(name)))
                .or_else(|| v.pointer("/metadata").and_then(|m| m.get(name)))
        } else {
            v.pointer("/evidence/body").and_then(|b| b.get(name))
        };
        found.and_then(Json::as_str).map(str::to_string)
    }

    /// The member's content as JSON, for structured rendering.
    pub fn json(&self) -> Json {
        serde_json::from_slice(self.bytes).unwrap_or(Json::Null)
    }
}

/// Shape-agnostic kind of a member envelope. The api owner's reader for sites
/// that hold a raw member `Json` without a graph/CID context (e.g. the verifier
/// reading pool members) -- so consumers read kind through the api instead of
/// hand pointer-fishing `/header/kind`.
fn raw_member_kind(envelope: &Json) -> Option<&str> {
    envelope
        .pointer("/header/kind")
        .or_else(|| envelope.pointer("/envelope/header/kind"))
        .or_else(|| envelope.pointer("/evidence/kind"))
        .and_then(Json::as_str)
}

/// Shape-agnostic typed kind of a member envelope. Unknown kinds are loud at
/// the parse boundary so downstream code cannot silently string-match around
/// an unsupported member shape.
pub fn member_kind(envelope: &Json) -> Result<MemberKind, MemberError> {
    let kind = raw_member_kind(envelope).ok_or(MemberError::MissingKind)?;
    kind.parse()
}

/// Shape-agnostic body object of a member envelope (the container of
/// kind-specific fields), regardless of v1.1 flat / v1.2 layered / lean shape.
pub fn member_body(envelope: &Json) -> Option<&Json> {
    if envelope.get("envelope").is_some() {
        envelope
            .get("header")
            .or_else(|| envelope.pointer("/envelope/header"))
    } else if envelope.get("header").is_some() || envelope.get("body").is_some() {
        envelope.get("body").or_else(|| envelope.get("header"))
    } else {
        envelope.pointer("/evidence/body")
    }
}

/// Shape-agnostic lookup of a named body-tier field on a member envelope,
/// mirroring how members are minted: header, then metadata/body, then the v1.1
/// flat `evidence.body`. The api owner's reader for pool-less field reads.
pub fn member_field<'a>(envelope: &'a Json, name: &str) -> Option<&'a Json> {
    if envelope.get("envelope").is_some() {
        envelope
            .pointer("/header")
            .and_then(|h| h.get(name))
            .or_else(|| envelope.pointer("/metadata").and_then(|m| m.get(name)))
            .or_else(|| {
                envelope
                    .pointer("/envelope/header")
                    .and_then(|h| h.get(name))
            })
            .or_else(|| {
                envelope
                    .pointer("/envelope/metadata")
                    .and_then(|m| m.get(name))
            })
    } else if envelope.get("header").is_some() || envelope.get("body").is_some() {
        envelope
            .pointer("/header")
            .and_then(|h| h.get(name))
            .or_else(|| envelope.pointer("/body").and_then(|b| b.get(name)))
            .or_else(|| envelope.pointer("/metadata").and_then(|m| m.get(name)))
    } else {
        envelope.pointer("/evidence/body").and_then(|b| b.get(name))
    }
}

/// Owned verifier-pool storage for an anchored member.
///
/// This consumes the raw member envelope shape at the proof-envelope boundary
/// and retains only the normalized member kind, body object, and first-match
/// field map needed by downstream verifier accessors.
#[derive(Clone, Debug)]
pub struct StoredMember {
    cid: MementoCid,
    kind: MemberKind,
    body: Option<Json>,
    fields: BTreeMap<String, Json>,
}

impl StoredMember {
    pub fn from_envelope(cid: MementoCid, envelope: &Json) -> Result<Self, MemberError> {
        let kind = member_kind(envelope)?;
        let body = member_body(envelope).cloned();
        let mut fields = BTreeMap::new();
        for layer in member_field_layers(envelope) {
            for (name, value) in layer {
                fields.entry(name.clone()).or_insert_with(|| value.clone());
            }
        }
        Ok(Self {
            cid,
            kind,
            body,
            fields,
        })
    }

    pub fn cid(&self) -> &MementoCid {
        &self.cid
    }

    pub fn kind(&self) -> MemberKind {
        self.kind
    }

    pub fn body(&self) -> Option<&Json> {
        self.body.as_ref()
    }

    pub fn field(&self, name: &str) -> Option<&Json> {
        self.fields.get(name)
    }
}

fn member_field_layers(envelope: &Json) -> Vec<&serde_json::Map<String, Json>> {
    let mut layers = Vec::new();
    if envelope.get("envelope").is_some() {
        if let Some(layer) = envelope.pointer("/header").and_then(Json::as_object) {
            layers.push(layer);
        }
        if let Some(layer) = envelope.pointer("/metadata").and_then(Json::as_object) {
            layers.push(layer);
        }
        if let Some(layer) = envelope
            .pointer("/envelope/header")
            .and_then(Json::as_object)
        {
            layers.push(layer);
        }
        if let Some(layer) = envelope
            .pointer("/envelope/metadata")
            .and_then(Json::as_object)
        {
            layers.push(layer);
        }
    } else if envelope.get("header").is_some() || envelope.get("body").is_some() {
        if let Some(layer) = envelope.pointer("/header").and_then(Json::as_object) {
            layers.push(layer);
        }
        if let Some(layer) = envelope.pointer("/body").and_then(Json::as_object) {
            layers.push(layer);
        }
        if let Some(layer) = envelope.pointer("/metadata").and_then(Json::as_object) {
            layers.push(layer);
        }
    } else if let Some(layer) = envelope.pointer("/evidence/body").and_then(Json::as_object) {
        layers.push(layer);
    }
    layers
}

/// Shape-agnostic signer of a member envelope. v1.2 layered: `/envelope/signer`;
/// v1.1 flat: top-level `signer`. The api owner's reader so consumers stop
/// hand-fishing the envelope's provenance.
pub fn member_signer(envelope: &Json) -> Option<&Json> {
    envelope
        .pointer("/envelope/signer")
        .or_else(|| envelope.get("signer"))
}

/// Shape-agnostic signature of a member envelope. v1.2 layered:
/// `/envelope/signature`; v1.1 flat: `producerSignature` (or `signature`).
pub fn member_signature(envelope: &Json) -> Option<&Json> {
    envelope
        .pointer("/envelope/signature")
        .or_else(|| envelope.get("producerSignature"))
        .or_else(|| envelope.get("signature"))
}

/// Recompute a member envelope's content identity from the bytes-decoded JSON.
///
/// This is the verifier-side identity rule for every member shape:
///
/// * v1.2 layered members are identified by `blake3_512(JCS(envelope))`.
/// * v1.1 flat members strip the self-declared `cid` and `producerSignature`
///   labels before canonicalization, so those attacker-chosen fields cannot
///   define the member key.
pub fn recompute_member_cid(envelope: &Json) -> String {
    if let Some(envelope_value) = envelope.get("envelope") {
        let canonical = encode_jcs(
            &json_to_canonical_value_at(envelope_value, "$.envelope")
                .unwrap_or_else(|err| panic!("{err}")),
        );
        return blake3_512_of(canonical.as_bytes());
    }

    let mut stripped = envelope.clone();
    if let Json::Object(map) = &mut stripped {
        map.shift_remove("cid");
        map.shift_remove("producerSignature");
    }
    let canonical = encode_jcs(&json_to_canonical_value(&stripped));
    blake3_512_of(canonical.as_bytes())
}

/// A member envelope that has earned its pool key at ingress.
///
/// This is the one construction door for verifier pool insertion: the caller
/// supplies the catalog key and decoded member envelope, and the constructor
/// re-derives the member CID and verifies any carried member signature before
/// handing the value to downstream indexes.
#[derive(Clone, Debug)]
pub struct AnchoredMember {
    cid: MementoCid,
    envelope: Json,
}

impl AnchoredMember {
    pub fn new(cid: MementoCid, envelope: Json) -> Result<Self, String> {
        let derived = MementoCid::try_parse(recompute_member_cid(&envelope))
            .expect("computed member CID must parse");
        if derived != cid {
            return Err(format!("rule 2: member {cid} derives to {derived}"));
        }
        if member_signature(&envelope).is_some() {
            verify_member_signature(&envelope).map_err(|error| format!("member {cid}: {error}"))?;
        }
        Ok(Self { cid, envelope })
    }

    pub fn cid(&self) -> &MementoCid {
        &self.cid
    }

    pub fn envelope(&self) -> &Json {
        &self.envelope
    }

    pub fn into_parts(self) -> (MementoCid, Json) {
        (self.cid, self.envelope)
    }

    pub fn into_stored_member(self) -> Result<(MementoCid, StoredMember), MemberError> {
        let stored = StoredMember::from_envelope(self.cid.clone(), &self.envelope)?;
        Ok((self.cid, stored))
    }
}

pub fn verify_member_signature(envelope: &Json) -> Result<(), String> {
    if let Some(layered_envelope) = envelope.get("envelope") {
        let signer = layered_envelope
            .get("signer")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "layered envelope signer missing".to_string())?;
        let signature = layered_envelope
            .get("signature")
            .and_then(|v| v.as_str())
            .ok_or_else(|| "layered envelope signature missing".to_string())?;
        let signature = Signature::try_parse(signature.to_string())
            .map_err(|err| format!("layered envelope invalid Ed25519 signature format: {err}"))?;
        let header = envelope
            .get("header")
            .ok_or_else(|| "layered envelope header missing".to_string())?;
        let metadata = envelope
            .get("metadata")
            .ok_or_else(|| "layered envelope metadata missing".to_string())?;
        let signing_header = layered_signature_header(envelope, header)?;
        let signing_value = Json::Object(
            [
                ("header".to_string(), signing_header),
                ("metadata".to_string(), metadata.clone()),
            ]
            .into_iter()
            .collect(),
        );
        let signing_canonical = encode_jcs(&json_to_canonical_value(&signing_value));
        if ed25519_verify_string(signer, &signature, signing_canonical.as_bytes()) {
            return Ok(());
        }
        return Err("layered envelope signature does not verify".to_string());
    }

    let Some(sig) = envelope.get("producerSignature").and_then(|v| v.as_str()) else {
        return Err("legacy envelope producerSignature missing".to_string());
    };
    let sig = Signature::try_parse(sig.to_string())
        .map_err(|err| format!("legacy envelope invalid Ed25519 signature format: {err}"))?;
    let Some(pubkey) = member_signer(envelope).and_then(|v| v.as_str()) else {
        return Err("legacy envelope signer missing".to_string());
    };
    let mut unsigned = envelope.clone();
    if let Json::Object(map) = &mut unsigned {
        map.shift_remove("cid");
        map.shift_remove("producerSignature");
    }
    let signing_canonical = encode_jcs(&json_to_canonical_value(&unsigned));
    if ed25519_verify_string(pubkey, &sig, signing_canonical.as_bytes()) {
        Ok(())
    } else {
        Err("legacy envelope producerSignature does not verify".to_string())
    }
}

fn layered_signature_header(envelope: &Json, header: &Json) -> Result<Json, String> {
    let mut signing_header = header.clone();
    // Proof-run and stage-receipt producers store the member identity in
    // `header.cid`; their signed preimage uses the derived header-content CID
    // to avoid a signature/CID fixed point.
    match member_kind(envelope) {
        Ok(MemberKind::ProofRun | MemberKind::StageReceipt) => {
            let cid = layered_header_content_cid(header)?;
            let Json::Object(map) = &mut signing_header else {
                return Err("layered envelope header is not an object".to_string());
            };
            map.insert("cid".to_string(), Json::String(cid));
        }
        Ok(MemberKind::AliasingMemento)
        | Ok(MemberKind::AssertionSurfaceMemento)
        | Ok(MemberKind::Authority)
        | Ok(MemberKind::Bridge)
        | Ok(MemberKind::ClosureBinding)
        | Ok(MemberKind::Contract)
        | Ok(MemberKind::EffectSiteAnnotation)
        | Ok(MemberKind::FactoryWalkMemento)
        | Ok(MemberKind::Implication)
        | Ok(MemberKind::LibrarySugarBindingEntry)
        | Ok(MemberKind::LoopInvariant)
        | Ok(MemberKind::PinInvariant)
        | Ok(MemberKind::PlanMemento)
        | Ok(MemberKind::SourceMemento)
        | Ok(MemberKind::TryBranch)
        | Ok(MemberKind::Witness)
        | Ok(MemberKind::WitnessMemento)
        | Err(_) => {}
    }
    Ok(signing_header)
}

fn layered_header_content_cid(header: &Json) -> Result<String, String> {
    let mut preimage = header.clone();
    let Json::Object(map) = &mut preimage else {
        return Err("layered envelope header is not an object".to_string());
    };
    map.shift_remove("cid");
    let canonical = encode_jcs(&json_to_canonical_value(&preimage));
    Ok(blake3_512_of(canonical.as_bytes()))
}

/// A `.proof` catalog read through the api: the envelope identity + metadata
/// that are NOT graph content, plus the reconstructed `ProofGraph`. Consumers
/// that need catalog-level fields (signer, declaredAt, metadata) read them here
/// instead of decoding the CBOR catalog by hand.
#[derive(Clone, Debug)]
pub struct ProofCatalog {
    pub name: String,
    pub version: String,
    pub signer: String,
    pub declared_at: String,
    pub metadata: BTreeMap<String, String>,
    pub graph: ProofGraph,
}

impl ProofCatalog {
    pub fn read(bytes: &[u8]) -> Result<ProofCatalog, crate::ProofEnvelopeError> {
        use crate::cbor_decode::{decode, CborValue};
        use crate::ProofEnvelopeError::Other;
        let catalog = decode(bytes).map_err(|e| Other(format!("CBOR decode catalog: {e:?}")))?;
        let map = catalog
            .as_map()
            .ok_or_else(|| Other("catalog root is not a CBOR map".into()))?;
        let tstr = |key: &str| {
            map.get(key)
                .and_then(CborValue::as_tstr)
                .unwrap_or("")
                .to_string()
        };
        let metadata = map
            .get("metadata")
            .and_then(CborValue::as_map)
            .map(|m| {
                m.iter()
                    .filter_map(|(k, v)| v.as_tstr().map(|s| (k.clone(), s.to_string())))
                    .collect()
            })
            .unwrap_or_default();
        Ok(ProofCatalog {
            name: tstr("name"),
            version: tstr("version"),
            signer: tstr("signer"),
            declared_at: tstr("declaredAt"),
            metadata,
            graph: ProofGraph::read(bytes)?,
        })
    }
}

#[derive(Clone, Debug)]
pub struct ProofGraph {
    atoms: BTreeMap<String, FlatAtom>,
    bodies: BTreeMap<String, ContractBody>,
    members: BTreeMap<String, MemberRecord>,
    /// Lazy typed-member cache. Populated on first access per member CID.
    /// `RefCell` for interior mutability; `Arc` so callers can hold the
    /// parsed `Member` without borrowing `self`.
    typed_cache: RefCell<BTreeMap<String, Arc<crate::typed_member::Member>>>,
}

impl ProofGraph {
    pub fn new() -> Self {
        Self {
            atoms: BTreeMap::new(),
            bodies: BTreeMap::new(),
            members: BTreeMap::new(),
            typed_cache: RefCell::new(BTreeMap::new()),
        }
    }

    pub fn empty() -> Self {
        Self::new()
    }

    /// Read a `.proof` catalog back into a strongly typed graph: the inverse
    /// of the `atoms -> bodies -> mementos -> catalog` construction. Atoms and
    /// bodies are reconstructed by recomputation (their CIDs are re-derived and
    /// checked against the catalog keys), and members are restored as typed
    /// records. Each member resolves its body by CID lookup against the graph;
    /// nothing is inlined. Source/witness leaves are never in the catalog --
    /// those resolve through kit-driven oracles, off this graph.
    pub fn read(bytes: &[u8]) -> Result<ProofGraph, crate::ProofEnvelopeError> {
        use crate::cbor_decode::{decode, CborValue};
        use crate::ProofEnvelopeError::Other;

        let catalog = decode(bytes).map_err(|e| Other(format!("CBOR decode catalog: {e:?}")))?;
        let map = catalog
            .as_map()
            .ok_or_else(|| Other("catalog root is not a CBOR map".into()))?;

        let mut graph = ProofGraph::new();

        // 1. Atoms: the data leaves. The content-addressed hash is lossless over
        //    the store, so we restore by recomputation -- re-derive each FlatAtom
        //    from its bytes and check the CID matches the catalog key.
        if let Some(atoms) = map.get("atoms").and_then(CborValue::as_map) {
            for (cid, val) in atoms {
                let raw = val
                    .as_bstr()
                    .ok_or_else(|| Other(format!("atom {cid} is not a byte string")))?;
                let json: Json = serde_json::from_slice(raw)
                    .map_err(|e| Other(format!("atom {cid} bytes not JSON: {e}")))?;
                let atom = FlatAtom::new(json_to_canonical_value(&json));
                if atom.cid().as_str() != cid {
                    return Err(Other(format!(
                        "atom CID mismatch: catalog key {cid} != recomputed {}",
                        atom.cid().as_str()
                    )));
                }
                graph.atoms.insert(cid.clone(), atom);
            }
        }

        // 2. Bodies: relationships, by CID only. A body holds atom-memento
        //    references, never inline atom data -- resolve each atomCid out of
        //    the atoms map and rebuild from slots, then recompute the CID.
        if let Some(bodies) = map.get("body").and_then(CborValue::as_map) {
            for (cid, val) in bodies {
                let raw = val
                    .as_bstr()
                    .ok_or_else(|| Other(format!("body {cid} is not a byte string")))?;
                let json: Json = serde_json::from_slice(raw)
                    .map_err(|e| Other(format!("body {cid} bytes not JSON: {e}")))?;
                let slots = json
                    .get("body")
                    .and_then(Json::as_object)
                    .ok_or_else(|| Other(format!("body {cid} has no `body` object")))?;
                let mut atom_mementos: Vec<(String, AtomMemento)> = Vec::with_capacity(slots.len());
                for (slot, slot_val) in slots {
                    let atom_cid = slot_val
                        .get("atomCid")
                        .and_then(Json::as_str)
                        .ok_or_else(|| Other(format!("body {cid} slot {slot} missing atomCid")))?;
                    let atom = graph.atoms.get(atom_cid).ok_or_else(|| {
                        Other(format!("body {cid} references unknown atom {atom_cid}"))
                    })?;
                    atom_mementos.push((slot.clone(), AtomMemento::new(atom)));
                }
                let body = ContractBody::from_slots(
                    atom_mementos.iter().map(|(s, m)| (s.as_str(), m)).collect(),
                );
                if body.cid().as_str() != cid {
                    return Err(Other(format!(
                        "body CID mismatch: catalog key {cid} != recomputed {}",
                        body.cid().as_str()
                    )));
                }
                graph.bodies.insert(cid.clone(), body);
            }
        }

        // 3. Members: signed mementos, kept as records. Each resolves its body
        //    lazily by CID lookup when asked (see `contract_body_of`); source and
        //    witness leaves are never stored here -- those resolve off-graph
        //    through kit-driven oracles.
        if let Some(members) = map.get("members").and_then(CborValue::as_map) {
            for (cid, val) in members {
                let memento_cid = MementoCid::try_parse(cid.clone()).map_err(|raw| {
                    Other(format!(
                        "member {raw}: invalid memento CID; requires `blake3-512:` plus 128 hex characters"
                    ))
                })?;
                let raw = val
                    .as_bstr()
                    .ok_or_else(|| Other(format!("member {cid} is not a byte string")))?;
                graph.insert_member(MemberRecord::new(memento_cid, raw.to_vec()));
            }
        }

        Ok(graph)
    }

    /// Resolve a contract member's body by following its `bodyCid` into the
    /// graph's body map. The member stores the reference, never the body.
    pub fn contract_body_of(&self, member: &MementoCid) -> Option<&ContractBody> {
        let record = self.members.get(member.as_str())?;
        let value: Json = serde_json::from_slice(&record.bytes).ok()?;
        let body_cid = value.pointer("/header/bodyCid").and_then(Json::as_str)?;
        self.bodies.get(body_cid)
    }

    /// Resolve a named body slot (`"inv"`, `"pre"`, `"post"`) for the
    /// contract identified by `member` and return its formula as JSON.
    ///
    /// Graph walk: `member` → `/header/bodyCid` → body bytes
    ///   → `body.<slot>.atomCid` → atom bytes → formula JSON.
    ///
    /// Returns `None` when the member has no body pointer, the body is absent,
    /// the slot does not exist in the body, or the atom bytes are not valid JSON.
    pub fn contract_slot_json(&self, member: &MementoCid, slot: &str) -> Option<Json> {
        let body = self.contract_body_of(member)?;
        let body_json: Json = serde_json::from_slice(body.bytes()).ok()?;
        let atom_cid = body_json
            .get("body")
            .and_then(|b| b.get(slot))
            .and_then(|s| s.get("atomCid"))
            .and_then(Json::as_str)?;
        let atom = self.atoms.get(atom_cid)?;
        serde_json::from_slice(atom.bytes()).ok()
    }

    /// Read every contract behavior out of the graph: `(name -> bodyCid)`,
    /// resolved lazily from each contract member's typed header. This is what a
    /// behavior diff compares -- nothing is hand-parsed by the caller.
    pub fn contracts(&self) -> Vec<ContractEntry> {
        self.members
            .iter()
            .filter_map(|(cid, record)| {
                let v: Json = serde_json::from_slice(&record.bytes).ok()?;
                let body_cid = v.pointer("/header/bodyCid").and_then(Json::as_str)?;
                let name = v
                    .pointer("/header/name")
                    .or_else(|| v.pointer("/header/contractName"))
                    .and_then(Json::as_str)?;
                Some(ContractEntry {
                    cid: cid.clone(),
                    name: name.to_string(),
                    body_cid: body_cid.to_string(),
                })
            })
            .collect()
    }

    /// View every member typed -- the inverse direction of `read`'s member
    /// reconstruction, handed to callers so they never parse member bytes.
    pub fn members_view(&self) -> impl Iterator<Item = MemberView<'_>> {
        self.members.values().map(|record| MemberView {
            cid: &record.cid,
            bytes: record.bytes.as_slice(),
        })
    }

    /// Parse and return a typed `Member` for the given CID, memoizing the
    /// result so each member is parsed at most once. Returns `None` when the
    /// CID is not in this graph.
    pub fn typed_member(
        &self,
        cid: &MementoCid,
    ) -> Option<Result<Arc<crate::typed_member::Member>, crate::typed_member::MemberError>> {
        // Fast path: already parsed.
        {
            let cache = self.typed_cache.borrow();
            if let Some(m) = cache.get(cid.as_str()) {
                return Some(Ok(m.clone()));
            }
        }
        // Slow path: parse and cache.
        let record = self.members.get(cid.as_str())?;
        let result = crate::typed_member::Member::parse(&record.bytes);
        match result {
            Ok(m) => {
                let m = Arc::new(m);
                self.typed_cache
                    .borrow_mut()
                    .insert(cid.as_str().to_string(), m.clone());
                Some(Ok(m))
            }
            Err(e) => Some(Err(e)),
        }
    }

    /// Iterate over all members, parsing each lazily and memoizing. Yields
    /// `(CID, Result<Arc<Member>>)` in BTreeMap key order.
    pub fn typed_members_iter(
        &self,
    ) -> impl Iterator<
        Item = (
            MementoCid,
            Result<Arc<crate::typed_member::Member>, crate::typed_member::MemberError>,
        ),
    > + '_ {
        self.members.keys().map(move |cid_str| {
            let cid = MementoCid::new(cid_str.clone());
            let result = self.typed_member(&cid).unwrap_or_else(|| {
                Err(crate::typed_member::MemberError::UnknownCid(
                    cid_str.clone(),
                ))
            });
            (cid, result)
        })
    }

    /// Typed iterator over bridge members only.
    pub fn bridges(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::Bridge))
    }

    /// Typed iterator over implication members only.
    pub fn implications(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::Implication))
    }

    /// Typed iterator over source-memento members only.
    pub fn sources(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::SourceMemento))
    }

    /// Typed iterator over witness-memento members only.
    pub fn witnesses(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::WitnessMemento))
    }

    /// Typed iterator over plan-memento members only.
    pub fn plans(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::PlanMemento))
    }

    /// Typed iterator over effect-site-annotation members only.
    pub fn effect_site_annotations(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind() == Some(MemberKind::EffectSiteAnnotation))
    }

    /// Write this graph to a signed `.proof` envelope -- the inverse of `read`.
    /// The graph carries the content; `identity` carries the envelope fields
    /// (name/version/signer/declaredAt) that are not graph content.
    pub fn write(&self, identity: &ProofIdentity) -> crate::ProofEnvelopeOutput {
        crate::build_proof_envelope(&crate::ProofEnvelopeInput {
            name: identity.name.clone(),
            version: identity.version.clone(),
            binary_cid: identity.binary_cid.clone(),
            metadata: identity.metadata.clone(),
            graph: self.clone(),
            signer_cid: identity.signer_cid.clone(),
            signer_seed: identity.signer_seed,
            declared_at: identity.declared_at.clone(),
        })
    }

    pub fn register_atom(&mut self, atom: FlatAtom) -> AtomMemento {
        self.atoms
            .insert(atom.cid().as_str().to_string(), atom.clone());
        AtomMemento::new(&atom)
    }

    pub fn register_body(&mut self, body: ContractBody) -> ContractBody {
        for atom in body.atoms() {
            assert!(
                self.atoms.contains_key(atom.cid().as_str()),
                "contract body {} references unregistered atom {}; register the atom before the body",
                body.cid().as_str(),
                atom.cid().as_str()
            );
        }
        self.bodies
            .insert(body.cid().as_str().to_string(), body.clone());
        body
    }

    pub fn register_contract(&mut self, contract: ContractMemento) {
        assert!(
            self.bodies.contains_key(contract.body().cid().as_str()),
            "contract `{}` references unregistered body {}; register the body before the contract",
            contract.name(),
            contract.body().cid().as_str()
        );
        let metadata_atom = contract.metadata().atom();
        assert!(
            self.atoms.contains_key(metadata_atom.cid().as_str()),
            "contract `{}` references unregistered metadata atom {}; register metadata before the contract",
            contract.name(),
            metadata_atom.cid().as_str()
        );
        self.insert_member(contract.record);
    }

    pub fn with_atom(mut self, atom: FlatAtom) -> (Self, AtomMemento) {
        let memento = self.register_atom(atom);
        (self, memento)
    }

    pub fn with_body(mut self, body: ContractBody) -> (Self, ContractBody) {
        let body = self.register_body(body);
        (self, body)
    }

    pub fn with_contract(mut self, contract: ContractMemento) -> Self {
        self.register_contract(contract);
        self
    }

    pub fn push_authority(&mut self, memento: AuthorityMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_bridge(&mut self, memento: BridgeMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_claim_contract(&mut self, memento: ClaimContractMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_effect_site_annotation(&mut self, memento: EffectSiteAnnotationMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_implication(&mut self, memento: ImplicationMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_assertion_surface(&mut self, memento: AssertionSurfaceMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_factory_walk(&mut self, memento: FactoryWalkMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_library_sugar_binding(&mut self, memento: LibrarySugarBindingMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_plan(&mut self, memento: PlanMemento) {
        self.insert_member(memento.record);
    }

    /// Insert a raw plan-memento member without exposing member-envelope
    /// discriminator parsing to callers. This is the non-panicking sibling of
    /// `PlanMemento::new` for replay paths that need to refuse malformed
    /// artifacts instead of aborting.
    pub fn push_plan_member_bytes(&mut self, bytes: Vec<u8>) -> Result<(), PlanMemberBytesError> {
        let value: Json =
            serde_json::from_slice(&bytes).map_err(PlanMemberBytesError::InvalidJson)?;
        if raw_member_kind(&value).and_then(|kind| kind.parse().ok())
            != Some(MemberKind::PlanMemento)
        {
            return Err(PlanMemberBytesError::WrongKind);
        }
        self.insert_member(MemberRecord::new(MementoCid::from_bytes(&bytes), bytes));
        Ok(())
    }

    pub fn push_proof_run(&mut self, memento: ProofRunMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_source(&mut self, memento: SourceMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_stage_receipt(&mut self, memento: StageReceiptMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_witness(&mut self, memento: WitnessMemento) {
        self.insert_member(memento.record);
    }

    pub fn push_witness_claim(&mut self, memento: WitnessClaimMemento) {
        self.insert_member(memento.record);
    }

    pub fn atoms(&self) -> impl Iterator<Item = &FlatAtom> {
        self.atoms.values()
    }

    pub fn bodies(&self) -> impl Iterator<Item = &ContractBody> {
        self.bodies.values()
    }

    pub fn members(&self) -> impl Iterator<Item = (&MementoCid, &[u8])> {
        self.members
            .values()
            .map(|record| (&record.cid, record.bytes.as_slice()))
    }

    pub(crate) fn atoms_map(&self) -> BTreeMap<String, Vec<u8>> {
        self.atoms
            .iter()
            .map(|(cid, atom)| (cid.clone(), atom.bytes().to_vec()))
            .collect()
    }

    pub(crate) fn body_map(&self) -> BTreeMap<String, Vec<u8>> {
        self.bodies
            .iter()
            .map(|(cid, body)| (cid.clone(), body.bytes().to_vec()))
            .collect()
    }

    pub(crate) fn members_map(&self) -> BTreeMap<String, Vec<u8>> {
        self.members
            .iter()
            .map(|(cid, member)| (cid.clone(), member.bytes.clone()))
            .collect()
    }

    fn insert_member(&mut self, record: MemberRecord) {
        self.members.insert(record.cid.as_str().to_string(), record);
    }
}

impl Default for ProofGraph {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cbor::{cbor_encode_bstr, cbor_encode_map_head, cbor_encode_tstr};

    fn catalog_with_member_key(cid: &str) -> Vec<u8> {
        let mut out = Vec::new();
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, "members");
        cbor_encode_map_head(&mut out, 1);
        cbor_encode_tstr(&mut out, cid);
        cbor_encode_bstr(&mut out, br#"{"header":{"kind":"witness-memento"}}"#);
        out
    }

    fn contract_member_json() -> (MementoCid, Json) {
        let atom = FlatAtom::result_eq_int(1);
        let atom = AtomMemento::new(&atom);
        let body = ContractBody::new(&atom);
        let contract = ContractMemento::new("crate::f", &body, [0x11; 32]);
        let envelope: Json = serde_json::from_slice(contract.bytes()).expect("contract JSON");
        (contract.cid().clone(), envelope)
    }

    fn canonical_bytes(value: Json) -> Vec<u8> {
        encode_jcs(&json_to_canonical_value(&value)).into_bytes()
    }

    fn layered_envelope_cid(bytes: &[u8]) -> String {
        let value: Json = serde_json::from_slice(bytes).expect("layered member JSON");
        let envelope = value.get("envelope").expect("layered envelope");
        blake3_512_of(encode_jcs(&json_to_canonical_value(envelope)).as_bytes())
    }

    #[test]
    fn proof_graph_json_canonicalization_refuses_non_integer_number_with_path() {
        let value = serde_json::json!({
            "envelope": {
                "body": {
                    "value": 1.5
                }
            }
        });

        let panic = std::panic::catch_unwind(|| {
            let _ = recompute_member_cid(&value);
        })
        .expect_err("proof-envelope canonicalization must refuse non-integer JSON numbers");
        let msg = panic
            .downcast_ref::<String>()
            .cloned()
            .or_else(|| {
                panic
                    .downcast_ref::<&'static str>()
                    .map(|s| (*s).to_string())
            })
            .unwrap_or_else(|| "<non-string panic>".to_string());
        assert!(msg.contains("non-integer JSON number"), "{msg}");
        assert!(msg.contains("$.envelope.body.value"), "{msg}");
    }

    #[test]
    fn graph_requires_atom_before_body_and_body_before_contract() {
        let atom = FlatAtom::result_eq_int(7);
        let atom_memento = AtomMemento::new(&atom);
        let body = ContractBody::new(&atom_memento);
        let contract = ContractMemento::new("crate::f", &body, [0x42; 32]);

        let body_before_atom = std::panic::catch_unwind({
            let body = body.clone();
            move || {
                let mut graph = ProofGraph::new();
                graph.register_body(body);
            }
        });
        assert!(body_before_atom.is_err());

        let contract_before_body = std::panic::catch_unwind({
            let atom = atom.clone();
            let contract = contract.clone();
            move || {
                let mut graph = ProofGraph::new();
                graph.register_atom(atom);
                graph.register_contract(contract);
            }
        });
        assert!(contract_before_body.is_err());
    }

    #[test]
    fn proof_graph_lowers_registered_atoms_bodies_and_contracts_to_catalog_maps() {
        let mut graph = ProofGraph::new();
        let atom = FlatAtom::result_eq_int(7);
        let post = graph.register_atom(atom.clone());
        let metadata_atom = FlatAtom::empty_metadata();
        let metadata = graph.register_atom(metadata_atom.clone());
        let body = graph.register_body(ContractBody::new(&post));
        let contract = ContractMemento::new_with_metadata_at(
            "crate::f",
            &body,
            &metadata,
            [0x42; 32],
            "2026-04-30T00:00:00.000Z",
        );
        graph.register_contract(contract.clone());

        assert_eq!(
            graph.atoms_map().get(atom.cid().as_str()),
            Some(&atom.bytes().to_vec())
        );
        assert_eq!(
            graph.atoms_map().get(metadata_atom.cid().as_str()),
            Some(&metadata_atom.bytes().to_vec())
        );
        assert_eq!(
            graph.body_map().get(body.cid().as_str()),
            Some(&body.bytes().to_vec())
        );
        assert_eq!(
            graph.members_map().get(contract.cid().as_str()),
            Some(&contract.bytes().to_vec())
        );
    }

    #[test]
    fn typed_wrappers_derive_member_identity_without_raw_cid_callers() {
        let source = canonical_bytes(serde_json::json!({
            "body": {"kind": "source-memento", "source_cid": "blake3-512:source"},
            "header": {"kind": "source-memento", "sourceCid": "blake3-512:source"},
            "schemaVersion": "1"
        }));
        let source_memento = SourceMemento::new(source.clone());
        assert_eq!(source_memento.cid().as_str(), blake3_512_of(&source));

        let run = canonical_bytes(serde_json::json!({
            "envelope": {"declaredAt": "2026-06-01T00:00:00Z", "signature": "sig", "signer": "signer"},
            "header": {"cid": "blake3-512:run", "kind": "proof-run"},
            "metadata": {}
        }));
        let run_cid = layered_envelope_cid(&run);
        let proof_run = ProofRunMemento::new(run.clone());
        assert_eq!(proof_run.cid().as_str(), run_cid);

        let mut graph = ProofGraph::new();
        graph.push_source(source_memento);
        graph.push_proof_run(proof_run);
        assert_eq!(
            graph.members_map().get(&blake3_512_of(&source)),
            Some(&source)
        );
        assert_eq!(graph.members_map().get(&run_cid), Some(&run));
    }

    #[test]
    fn contract_edges_use_typed_memento_refs_not_raw_cid_strings() {
        let post_atom = FlatAtom::result_eq_int(7);
        let post = AtomMemento::new(&post_atom);
        let body = ContractBody::new(&post);
        let contract = ContractMemento::new("crate::f", &body, [0x42; 32]);

        let reference = ContractMementoRef::from(&contract);
        assert_eq!(reference.cid(), contract.cid());

        let malformed = std::panic::catch_unwind(|| ContractMementoRef::new("not-a-cid"));
        assert!(
            malformed.is_err(),
            "typed memento refs must reject untagged raw strings at construction"
        );
    }

    #[test]
    fn read_refuses_member_key_with_bad_prefix() {
        let err = ProofGraph::read(&catalog_with_member_key("sha512:aaaaaaaa"))
            .expect_err("member key with wrong prefix must refuse");

        assert!(
            err.to_string().contains("sha512:aaaaaaaa"),
            "error should name the bad member CID: {err}"
        );
    }

    #[test]
    fn read_refuses_member_key_with_bad_hex() {
        let err = ProofGraph::read(&catalog_with_member_key(&format!(
            "blake3-512:{}g",
            "a".repeat(127)
        )))
        .expect_err("member key with non-hex digest must refuse");

        assert!(
            err.to_string().contains("blake3-512:"),
            "error should name the bad member CID: {err}"
        );
    }

    #[test]
    fn anchored_member_refuses_wrong_cid() {
        let (_cid, envelope) = contract_member_json();
        let wrong = MementoCid::try_parse(format!("blake3-512:{}", "9".repeat(128)))
            .expect("synthetic CID parses");

        let err =
            AnchoredMember::new(wrong.clone(), envelope).expect_err("wrong member CID must refuse");

        assert!(
            err.to_string().contains(wrong.as_str()) && err.to_string().contains("derives to"),
            "error should name the wrong CID and derived CID: {err}"
        );
    }

    #[test]
    fn anchored_member_refuses_tampered_payload() {
        let (cid, mut envelope) = contract_member_json();
        let contract_name = envelope
            .pointer_mut("/header/contractName")
            .expect("contractName exists");
        *contract_name = Json::String("crate::tampered".to_string());
        envelope
            .pointer("/header/contractName")
            .and_then(Json::as_str)
            .expect("contractName exists");

        let err = AnchoredMember::new(cid.clone(), envelope)
            .expect_err("tampered member payload must refuse");

        assert!(
            err.to_string().contains(cid.as_str()) && err.to_string().contains("signature"),
            "error should name the original CID and signature refusal: {err}"
        );
    }

    #[test]
    fn anchored_member_refuses_bad_signature_even_when_cid_matches() {
        let (_cid, mut envelope) = contract_member_json();
        let signature = envelope
            .pointer_mut("/envelope/signature")
            .expect("signature exists");
        let bad_signature = format!("{}A", signature.as_str().expect("signature is string"));
        *signature = Json::String(bad_signature);
        let tampered_cid = MementoCid::try_parse(recompute_member_cid(&envelope))
            .expect("recomputed tampered CID parses");

        let err = AnchoredMember::new(tampered_cid, envelope)
            .expect_err("bad member signature must refuse");

        assert!(
            err.to_string().contains("signature"),
            "error should name signature verification: {err}"
        );
    }

    #[test]
    fn anchored_member_refuses_prefix_only_signature_shape_even_when_cid_matches() {
        let (_cid, mut envelope) = contract_member_json();
        *envelope
            .pointer_mut("/envelope/signature")
            .expect("signature exists") = Json::String("ed25519:AAAA".to_string());
        let tampered_cid = MementoCid::try_parse(recompute_member_cid(&envelope))
            .expect("recomputed tampered CID parses");

        let err = AnchoredMember::new(tampered_cid, envelope)
            .expect_err("prefix-only signature shape must refuse at parse");

        assert!(
            err.to_string().contains("invalid Ed25519 signature format")
                && err.to_string().contains("64-byte Ed25519 signature"),
            "error should name signature shape, not only failed verification: {err}"
        );
    }

    #[test]
    fn read_reconstructs_atoms_bodies_and_resolves_contract_body() {
        use crate::{build_proof_envelope, ProofEnvelopeInput};

        // Write a catalog by construction: atom -> body -> contract.
        let mut graph = ProofGraph::new();
        let atom = FlatAtom::result_eq_int(7);
        let post = graph.register_atom(atom.clone());
        let metadata_atom = FlatAtom::empty_metadata();
        let metadata = graph.register_atom(metadata_atom.clone());
        let body = graph.register_body(ContractBody::new(&post));
        let contract = ContractMemento::new_with_metadata_at(
            "crate::f",
            &body,
            &metadata,
            [0x42; 32],
            "2026-04-30T00:00:00.000Z",
        );
        graph.register_contract(contract.clone());

        let out = build_proof_envelope(&ProofEnvelopeInput {
            name: "@x/y".into(),
            version: "0.0.1".into(),
            binary_cid: None,
            metadata: None,
            graph,
            signer_cid: "blake3-512:bb".into(),
            signer_seed: [0x11; 32],
            declared_at: "2026-04-30T00:00:00.000Z".into(),
        });

        // Read the catalog back into a strongly typed graph.
        let read = ProofGraph::read(&out.bytes).expect("read catalog");

        // Atoms reconstructed as typed FlatAtoms, by recomputation.
        let mut got: Vec<String> = read.atoms().map(|a| a.cid().as_str().to_string()).collect();
        got.sort();
        let mut want = vec![
            atom.cid().as_str().to_string(),
            metadata_atom.cid().as_str().to_string(),
        ];
        want.sort();
        assert_eq!(got, want, "read graph reconstructs the atom leaves");

        // Body reconstructed; it carries the relationship by CID, resolving its
        // atom out of the atoms map -- never inlining atom data.
        let read_body = read.bodies().next().expect("one reconstructed body");
        assert_eq!(
            read_body.cid().as_str(),
            body.cid().as_str(),
            "body CID round-trips"
        );
        let body_atoms: Vec<String> = read_body
            .atoms()
            .map(|a| a.cid().as_str().to_string())
            .collect();
        assert_eq!(
            body_atoms,
            vec![atom.cid().as_str().to_string()],
            "body resolves its atom by CID"
        );

        // Contract member resolves its body by bodyCid lookup.
        let resolved = read
            .contract_body_of(contract.cid())
            .expect("contract resolves its body");
        assert_eq!(
            resolved.cid().as_str(),
            body.cid().as_str(),
            "contract -> body by lookup"
        );

        // Contracts read out of the graph as (name -> bodyCid): the behavior
        // table a diff compares.
        let contracts = read.contracts();
        assert_eq!(contracts.len(), 1, "one contract behavior in the graph");
        assert_eq!(contracts[0].name.as_str(), "crate::f");
        assert_eq!(contracts[0].body_cid.as_str(), body.cid().as_str());
        assert_eq!(contracts[0].cid.as_str(), contract.cid().as_str());
    }

    #[test]
    fn write_is_the_inverse_of_read_and_members_view_is_typed() {
        let mut graph = ProofGraph::new();
        let post = graph.register_atom(FlatAtom::result_eq_int(7));
        let metadata = graph.register_atom(FlatAtom::empty_metadata());
        let body = graph.register_body(ContractBody::new(&post));
        let contract = ContractMemento::new_with_metadata_at(
            "crate::f",
            &body,
            &metadata,
            [0x42; 32],
            "2026-04-30T00:00:00.000Z",
        );
        graph.register_contract(contract.clone());

        // write by method (the symmetric pair with read), not the free fn.
        let out = graph.write(&ProofIdentity {
            name: "@x/y".to_string(),
            version: "0.0.1".to_string(),
            binary_cid: None,
            metadata: None,
            signer_cid: "blake3-512:bb".to_string(),
            signer_seed: [0x11; 32],
            declared_at: "2026-04-30T00:00:00.000Z".to_string(),
        });
        let read = ProofGraph::read(&out.bytes).expect("read what write produced");

        // write∘read is identity over the behavior.
        let contracts = read.contracts();
        assert_eq!(contracts.len(), 1);
        assert_eq!(contracts[0].name.as_str(), "crate::f");
        assert_eq!(contracts[0].body_cid.as_str(), body.cid().as_str());

        // members are viewable typed -- kind + bodyCid -- with no caller parse.
        let views: Vec<_> = read.members_view().collect();
        assert_eq!(views.len(), 1);
        assert_eq!(views[0].kind(), Some(MemberKind::Contract));
        assert_eq!(views[0].body_cid().as_deref(), Some(body.cid().as_str()));
        assert_eq!(views[0].cid().as_str(), contract.cid().as_str());
    }
}
