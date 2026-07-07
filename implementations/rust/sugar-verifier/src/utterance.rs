// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Utterance verb layer (#3812): the typed protocol surface over the memento
// pool. A pool is a CONVERSATION -- a vendor speaks their universe, a
// consumer speaks their facts, and `solve` referees what was said. This
// module gives that conversation verbs:
//
//   speak_fact        -- a speaker asserts fact-carrying members (contracts)
//   speak_universe    -- a speaker publishes a whole envelope of testimony
//   speak_implication -- a speaker asserts implication members
//   solve             -- run the existing consistency machinery; the rows'
//                        client/vendor fact labels come FROM the attribution
//                        the verbs stamped, never from position heuristics
//
// Each verb takes ONE proof envelope's bytes (`ProofBytes`) plus a
// `Speaker`, loads it through the SAME envelope rules every other intake
// uses (CID trust root, signature checks -- nothing is relaxed), and stamps
// attribution (member CID -> Speaker) into the pool's `member_speaker` map.
// Attribution is IDEMPOTENT BY CID: re-speaking an already-spoken member is
// a no-op (first speaker wins), and the receipt says so explicitly.
//
// ONE construction: the attribution map lives in `MementoPool.member_speaker`
// and NOWHERE else. The verbs write it, `consistency.rs` partitions by it,
// `report.rs` projects it. There is no second copy for a caller to desync.

use std::collections::HashMap;
use std::path::Path;

use crate::consistency::{verify_consistency, ConsistencyResult};
use crate::load_all_proofs::{load_bytes_into_pool, ProofBytes};
use crate::solvers::{SolverHandle, SolverPlan, SolverSeat};
use crate::types::{LoadError, MemberKind, MementoCid, MementoPool, Speaker, SpeakerRole};
use sugar_ir_compiler::registry::Registry as CompilerRegistry;

/// Which verb an utterance came in through. Recorded on the receipt so a
/// caller (and a test) can discriminate the three intakes.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UtteranceKind {
    /// The speaker asserts facts: the envelope must carry at least one
    /// contract member (the fact carrier in this substrate).
    Fact,
    /// The speaker publishes their universe: the whole envelope, whatever
    /// member kinds it carries, sworn at once. No kind requirement -- a
    /// universe IS the envelope.
    Universe,
    /// The speaker asserts implications: the envelope must carry at least
    /// one implication member.
    Implication,
}

/// What one `speak_*` call did, member by member. The idempotency receipt:
/// a re-speak of the same envelope reports every member under
/// `members_already_spoken` and none under `members_spoken`.
#[derive(Debug, Clone)]
pub struct SpeakReceipt {
    pub kind: UtteranceKind,
    pub speaker: Speaker,
    /// Member CIDs this utterance newly attributed to `speaker`.
    pub members_spoken: Vec<MementoCid>,
    /// Member CIDs that were ALREADY attributed (to this or any earlier
    /// speaker) before this utterance: re-speak = no-op, first speaker wins.
    pub members_already_spoken: Vec<MementoCid>,
    /// Envelope-level load errors raised while decoding THIS utterance
    /// (surfaced, never swallowed; they are also appended to
    /// `pool.load_errors` like every other intake's errors).
    pub load_errors: Vec<LoadError>,
}

/// A refused utterance. The pool is left UNTOUCHED: refusal is atomic.
#[derive(Debug, Clone)]
pub struct UtteranceRefusal {
    pub kind: UtteranceKind,
    pub speaker: Speaker,
    pub reason: String,
    /// Load errors from the scratch decode that justified the refusal.
    pub load_errors: Vec<LoadError>,
}

impl std::fmt::Display for UtteranceRefusal {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "utterance refused ({:?} by {} [{:?}]): {}",
            self.kind, self.speaker.id, self.speaker.role, self.reason
        )
    }
}

impl std::error::Error for UtteranceRefusal {}

/// Speak fact-carrying members: refuses an envelope with no contract member.
pub fn speak_fact(
    pool: &mut MementoPool,
    speaker: &Speaker,
    proof: &ProofBytes,
) -> Result<SpeakReceipt, UtteranceRefusal> {
    speak(pool, speaker, proof, UtteranceKind::Fact)
}

/// Speak a whole envelope of testimony (the vendor's universe, typically).
pub fn speak_universe(
    pool: &mut MementoPool,
    speaker: &Speaker,
    proof: &ProofBytes,
) -> Result<SpeakReceipt, UtteranceRefusal> {
    speak(pool, speaker, proof, UtteranceKind::Universe)
}

/// Speak implication members: refuses an envelope with no implication member.
pub fn speak_implication(
    pool: &mut MementoPool,
    speaker: &Speaker,
    proof: &ProofBytes,
) -> Result<SpeakReceipt, UtteranceRefusal> {
    speak(pool, speaker, proof, UtteranceKind::Implication)
}

/// The one intake behind all three verbs.
///
/// Mechanism: decode the envelope into a SCRATCH pool first (same
/// `load_catalog_bytes` rules as every other intake, with `speaker` stamped
/// as each member's attribution), gate the verb's member-kind requirement on
/// what actually decoded, then `merge` the scratch into the caller's pool --
/// the SAME merge the runner uses for extra pools, so a spoken pool is
/// index-for-index the pool a direct load would have built. Refusal happens
/// before the merge, so a refused utterance leaves the caller's pool
/// untouched.
fn speak(
    pool: &mut MementoPool,
    speaker: &Speaker,
    proof: &ProofBytes,
    kind: UtteranceKind,
) -> Result<SpeakReceipt, UtteranceRefusal> {
    let mut scratch = MementoPool::default();
    load_bytes_into_pool(
        &proof.label,
        &proof.expected_cid,
        &proof.bytes,
        &mut scratch,
        speaker,
    );
    let load_errors = scratch.load_errors.clone();
    if scratch.mementos.is_empty() {
        return Err(UtteranceRefusal {
            kind,
            speaker: speaker.clone(),
            reason: if load_errors.is_empty() {
                "envelope decoded to zero members".to_string()
            } else {
                format!(
                    "envelope decoded to zero members ({} load error(s), first: {})",
                    load_errors.len(),
                    load_errors[0].reason
                )
            },
            load_errors,
        });
    }
    let required_kind = match kind {
        UtteranceKind::Fact => Some(MemberKind::Contract),
        UtteranceKind::Universe => None,
        UtteranceKind::Implication => Some(MemberKind::Implication),
    };
    if let Some(required) = required_kind {
        let carries = scratch.mementos.values().any(|m| m.kind() == required);
        if !carries {
            return Err(UtteranceRefusal {
                kind,
                speaker: speaker.clone(),
                reason: format!(
                    "envelope carries no `{}` member; {:?} utterances must carry at least one",
                    required.as_str(),
                    kind
                ),
                load_errors,
            });
        }
    }

    // Partition the envelope's members into newly-spoken vs already-spoken
    // BEFORE the merge (the merge's first-writer-wins policy is what makes
    // re-speak a no-op; this receipt just reports which side each member
    // landed on).
    let mut members_spoken = Vec::new();
    let mut members_already_spoken = Vec::new();
    for cid in scratch.mementos.keys() {
        if pool.member_speaker.contains_key(cid) {
            members_already_spoken.push(cid.clone());
        } else {
            members_spoken.push(cid.clone());
        }
    }
    pool.merge(scratch);

    Ok(SpeakReceipt {
        kind,
        speaker: speaker.clone(),
        members_spoken,
        members_already_spoken,
        load_errors,
    })
}

/// The attribution map one `solve` call labels its rows from: member CID ->
/// Speaker, exactly as the verbs (and every other intake) stamped it. A
/// projection accessor -- the map itself lives in the pool (ONE
/// construction), this is the typed read door.
pub fn attribution(pool: &MementoPool) -> &std::collections::BTreeMap<MementoCid, Speaker> {
    &pool.member_speaker
}

/// Referee the conversation: a THIN wrapper over `verify_consistency`. The
/// solver input is byte-identical to a plain `verify_consistency` call --
/// this wrapper adds NOTHING to the encoding. What the utterance layer
/// guarantees is where the row LABELS come from: `clientFactIr` is the
/// conjunction of the members spoken by `SpeakerRole::Consumer` speakers,
/// `vendorFactIr` gathers the members spoken by `SpeakerRole::Vendor`
/// speakers -- read from the pool's attribution map (see [`attribution`]),
/// never inferred from conjunct position, sworn-vector authority, or source
/// text.
pub fn solve(
    pool: &MementoPool,
    plan: &SolverPlan,
    registry: &HashMap<SolverSeat, SolverHandle>,
    compilers: &CompilerRegistry,
    project_root: &Path,
) -> Vec<ConsistencyResult> {
    verify_consistency(pool, plan, registry, compilers, project_root)
}

/// Convenience constructors so protocol callers do not hand-build structs.
impl Speaker {
    pub fn vendor(id: impl Into<String>) -> Self {
        Speaker {
            id: id.into(),
            role: SpeakerRole::Vendor,
        }
    }

    pub fn consumer(id: impl Into<String>) -> Self {
        Speaker {
            id: id.into(),
            role: SpeakerRole::Consumer,
        }
    }
}
