// SPDX-License-Identifier: Apache-2.0
//
// Typed proof-graph helpers. A .proof catalog is constructed in exactly one
// direction:
//
//   atoms -> bodies -> mementos -> graph -> catalog CID maps
//
// Callers do not assemble `{cid -> bytes}` maps. They construct typed mementos;
// this module derives, validates, and lowers the graph at the serialization edge.

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

#[derive(Clone, Debug)]
pub struct ProofGraph {
    atoms: BTreeMap<String, FlatAtom>,
    bodies: BTreeMap<String, ContractBody>,
    members: BTreeMap<String, MemberRecord>,
}

impl ProofGraph {
    pub fn new() -> Self {
        Self {
            atoms: BTreeMap::new(),
            bodies: BTreeMap::new(),
            members: BTreeMap::new(),
        }
    }

    pub fn empty() -> Self {
        Self::new()
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
}
