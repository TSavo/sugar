// SPDX-License-Identifier: Apache-2.0
//
// Typed proof-graph helpers. A .proof catalog is constructed in exactly one
// direction:
//
//   atoms -> bodies -> mementos -> graph -> catalog CID maps
//
// Callers do not assemble `{cid -> bytes}` maps. They construct typed mementos;
// this module derives, validates, and lowers the graph at the serialization edge.

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::sync::Arc;

use serde_json::Value as Json;
use sugar_canonicalizer::{blake3_512_of, encode_jcs, Value};

use crate::sign::{ed25519_pubkey_string, ed25519_sign_string, Ed25519Seed};

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

    pub fn as_str(&self) -> &str {
        &self.0
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

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct MementoCid(String);

impl MementoCid {
    fn new(cid: String) -> Self {
        assert!(
            cid.starts_with("blake3-512:"),
            "memento CID must be a blake3-512 CID, got `{cid}`"
        );
        Self(cid)
    }

    fn from_bytes(bytes: &[u8]) -> Self {
        Self::new(blake3_512_of(bytes))
    }

    /// Fallible constructor: returns `Ok` only when `cid` carries the
    /// `blake3-512:` tag. Used by typed-member parsing to surface a typed
    /// error instead of panicking.
    pub(crate) fn try_parse(cid: String) -> Result<Self, String> {
        if cid.starts_with("blake3-512:") {
            Ok(Self(cid))
        } else {
            Err(cid)
        }
    }

    fn from_json_field(bytes: &[u8], pointer: &str, type_name: &str) -> Self {
        let value: Json = serde_json::from_slice(bytes)
            .unwrap_or_else(|err| panic!("{type_name} bytes must be canonical JSON: {err}"));
        let cid = value
            .pointer(pointer)
            .and_then(Json::as_str)
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| panic!("{type_name} must carry non-empty `{pointer}`"))
            .to_string();
        Self::new(cid)
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
    match value {
        Json::Null => Value::null(),
        Json::Bool(v) => Value::boolean(*v),
        Json::Number(n) => {
            if let Some(i) = n.as_i64() {
                Value::integer(i128::from(i))
            } else if let Some(u) = n.as_u64() {
                Value::integer(i128::from(u))
            } else if let Some(f) = n.as_f64() {
                Value::integer(f as i128)
            } else {
                Value::integer(0)
            }
        }
        Json::String(s) => Value::string(s.clone()),
        Json::Array(items) => Value::array(items.iter().map(json_to_canonical_value).collect()),
        Json::Object(map) => Value::object(
            map.iter()
                .map(|(key, value)| (key.clone(), json_to_canonical_value(value)))
                .collect::<Vec<_>>(),
        ),
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

    fn from_header_cid(bytes: Vec<u8>, type_name: &str) -> Self {
        Self::new(
            MementoCid::from_json_field(&bytes, "/header/cid", type_name),
            bytes,
        )
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

macro_rules! header_cid_memento {
    ($name:ident, [$($kind:literal),+ $(,)?]) => {
        #[derive(Clone, Debug)]
        pub struct $name {
            record: MemberRecord,
        }

        impl $name {
            pub fn new(bytes: Vec<u8>) -> Self {
                validate_memento_kind(&bytes, stringify!($name), &[$($kind),+]);
                Self {
                    record: MemberRecord::from_header_cid(bytes, stringify!($name)),
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

header_cid_memento!(ProofRunMemento, ["proof-run"]);
header_cid_memento!(StageReceiptMemento, ["stage-receipt"]);

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
        let name = name.into();
        let header_preimage = Value::object([
            ("kind", Value::string("contract")),
            ("name", Value::string(name.clone())),
            ("bodyCid", Value::string(body.cid().as_str())),
        ]);
        let header_cid = blake3_512_of(encode_jcs(&header_preimage).as_bytes());
        let header = Value::object([
            ("schemaVersion", Value::string("2")),
            ("kind", Value::string("contract")),
            ("cid", Value::string(header_cid)),
            ("name", Value::string(name.clone())),
            ("contractName", Value::string(name.clone())),
            ("bodyCid", Value::string(body.cid().as_str())),
        ]);
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
    pub fn kind(&self) -> Option<String> {
        let v: Json = serde_json::from_slice(self.bytes).ok()?;
        v.pointer("/header/kind")
            .or_else(|| v.pointer("/envelope/header/kind"))
            .or_else(|| v.pointer("/evidence/kind"))
            .and_then(Json::as_str)
            .map(str::to_string)
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
pub fn member_kind(envelope: &Json) -> Option<&str> {
    envelope
        .pointer("/header/kind")
        .or_else(|| envelope.pointer("/envelope/header/kind"))
        .or_else(|| envelope.pointer("/evidence/kind"))
        .and_then(Json::as_str)
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
                // Gracefully reject unsupported hash-tag prefixes rather than
                // panicking inside `MementoCid::new`. This ensures callers can
                // surface a typed error instead of an unwind.
                if !cid.starts_with("blake3-512:") {
                    return Err(Other(format!(
                        "member {cid}: unsupported hash tag; requires `blake3-512:` prefix"
                    )));
                }
                let raw = val
                    .as_bstr()
                    .ok_or_else(|| Other(format!("member {cid} is not a byte string")))?;
                graph.insert_member(MemberRecord::new(
                    MementoCid::new(cid.clone()),
                    raw.to_vec(),
                ));
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
            .filter(|v| v.kind().as_deref() == Some("bridge"))
    }

    /// Typed iterator over implication members only.
    pub fn implications(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind().as_deref() == Some("implication"))
    }

    /// Typed iterator over source-memento members only.
    pub fn sources(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind().as_deref() == Some("source-memento"))
    }

    /// Typed iterator over witness-memento members only.
    pub fn witnesses(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind().as_deref() == Some("witness-memento"))
    }

    /// Typed iterator over plan-memento members only.
    pub fn plans(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind().as_deref() == Some("plan-memento"))
    }

    /// Typed iterator over effect-site-annotation members only.
    pub fn effect_site_annotations(&self) -> impl Iterator<Item = MemberView<'_>> + '_ {
        self.members_view()
            .filter(|v| v.kind().as_deref() == Some("effect-site-annotation"))
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

    fn canonical_bytes(value: Json) -> Vec<u8> {
        encode_jcs(&json_to_canonical_value(&value)).into_bytes()
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
        let proof_run = ProofRunMemento::new(run.clone());
        assert_eq!(proof_run.cid().as_str(), "blake3-512:run");

        let mut graph = ProofGraph::new();
        graph.push_source(source_memento);
        graph.push_proof_run(proof_run);
        assert_eq!(
            graph.members_map().get(&blake3_512_of(&source)),
            Some(&source)
        );
        assert_eq!(graph.members_map().get("blake3-512:run"), Some(&run));
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
        assert_eq!(views[0].kind().as_deref(), Some("contract"));
        assert_eq!(views[0].body_cid().as_deref(), Some(body.cid().as_str()));
        assert_eq!(views[0].cid().as_str(), contract.cid().as_str());
    }
}
