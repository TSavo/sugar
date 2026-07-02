// SPDX-License-Identifier: Apache-2.0
//
// Ed25519 signing helper. v1.1.0 of the protocol mandates
// self-identifying signatures of the form:
//
//   "ed25519:" + base64-stdpad(64-byte-signature)
//
// And self-identifying public keys of the same form. The .proof file
// envelope itself stores its catalog signature as a RAW 64-byte CBOR
// byte string (not the prefixed string form): only the per-memento
// `producerSignature` field uses the prefixed string form, because
// memento envelopes are JCS-JSON.

use base64::{engine::general_purpose::STANDARD as B64, Engine as _};
use ed25519_dalek::{Signature as DalekSignature, Signer, SigningKey, Verifier, VerifyingKey};
use serde::{Deserialize, Deserializer, Serialize, Serializer};
use std::fmt;

pub type Ed25519Seed = [u8; 32];
pub type Ed25519Signature = [u8; 64];
pub type Ed25519PublicKey = [u8; 32];

pub const ED25519_SIG_PREFIX: &str = "ed25519:";
pub const ED25519_KEY_PREFIX: &str = "ed25519:";

#[derive(Clone, Debug, PartialEq, Eq, PartialOrd, Ord)]
pub struct Signature {
    wire: String,
    bytes: Ed25519Signature,
}

impl Signature {
    fn from_bytes(bytes: Ed25519Signature) -> Self {
        let mut wire = String::with_capacity(ED25519_SIG_PREFIX.len() + 88);
        wire.push_str(ED25519_SIG_PREFIX);
        wire.push_str(&B64.encode(bytes));
        Self { wire, bytes }
    }

    pub fn try_parse(raw: String) -> Result<Self, SignatureParseError> {
        let Some(sig_b64) = raw.strip_prefix(ED25519_SIG_PREFIX) else {
            return Err(SignatureParseError { raw });
        };
        if sig_b64.len() != 88 {
            return Err(SignatureParseError { raw });
        }
        let sig_bytes = B64
            .decode(sig_b64)
            .map_err(|_| SignatureParseError { raw: raw.clone() })?;
        if sig_bytes.len() != 64 {
            return Err(SignatureParseError { raw });
        }
        let mut bytes = [0u8; 64];
        bytes.copy_from_slice(&sig_bytes);
        Ok(Self { wire: raw, bytes })
    }

    pub fn as_str(&self) -> &str {
        &self.wire
    }

    pub fn bytes(&self) -> &Ed25519Signature {
        &self.bytes
    }
}

impl fmt::Display for Signature {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

impl AsRef<str> for Signature {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl Serialize for Signature {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(self.as_str())
    }
}

impl<'de> Deserialize<'de> for Signature {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let raw = String::deserialize(deserializer)?;
        Self::try_parse(raw).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Debug, PartialEq, Eq, thiserror::Error)]
#[error(
    "invalid Ed25519 signature format `{raw}`; expected `ed25519:` plus base64-stdpad 64-byte Ed25519 signature"
)]
pub struct SignatureParseError {
    raw: String,
}

/// Sign `message` with the Ed25519 private key derived from `seed`.
/// Returns the raw 64-byte signature. Mirrors the C++ helper.
pub fn ed25519_sign_with_seed(seed: &Ed25519Seed, message: &[u8]) -> Ed25519Signature {
    let key = SigningKey::from_bytes(seed);
    let sig = key.sign(message);
    sig.to_bytes()
}

/// Sign `message` and return the spec's self-identifying string form
/// (`"ed25519:" + base64(sig)`).
pub fn ed25519_sign_string(seed: &Ed25519Seed, message: &[u8]) -> String {
    let sig = ed25519_sign_with_seed(seed, message);
    Signature::from_bytes(sig).to_string()
}

/// Derive the public key from a seed and return the self-identifying
/// string form (`"ed25519:" + base64(pubkey)`).
pub fn ed25519_pubkey_string(seed: &Ed25519Seed) -> String {
    let sk = SigningKey::from_bytes(seed);
    let vk: VerifyingKey = sk.verifying_key();
    let bytes = vk.to_bytes();
    let mut s = String::with_capacity(ED25519_KEY_PREFIX.len() + 44);
    s.push_str(ED25519_KEY_PREFIX);
    s.push_str(&B64.encode(bytes));
    s
}

/// Verify `message` against `sig_string` (spec form
/// `"ed25519:" + base64(sig)`) using `pubkey_string`
/// (spec form `"ed25519:" + base64(pubkey)`).
/// Returns `true` iff the signature is valid. Returns `false` for any
/// malformed input rather than panicking. The verifier load path treats a
/// carried member signature that returns `false` as a load error; unsigned
/// members remain accepted until a separate trust policy requires presence.
pub fn ed25519_verify_string(pubkey_string: &str, signature: &Signature, message: &[u8]) -> bool {
    let pk_b64 = match pubkey_string.strip_prefix(ED25519_KEY_PREFIX) {
        Some(s) => s,
        None => return false,
    };
    let pk_bytes = match B64.decode(pk_b64) {
        Ok(b) => b,
        Err(_) => return false,
    };
    if pk_bytes.len() != 32 {
        return false;
    }
    let mut pk_arr = [0u8; 32];
    pk_arr.copy_from_slice(&pk_bytes);
    let vk = match VerifyingKey::from_bytes(&pk_arr) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let sig = DalekSignature::from_bytes(signature.bytes());
    vk.verify(message, &sig).is_ok()
}

/// Verify `message` against a raw 64-byte Ed25519 signature using a
/// self-identifying string public key (`"ed25519:" + base64(pubkey)`).
/// The `.proof` catalog envelope stores its outer signature in this raw
/// byte-string form.
pub fn ed25519_verify_bytes(pubkey_string: &str, sig_bytes: &[u8], message: &[u8]) -> bool {
    let pk_b64 = match pubkey_string.strip_prefix(ED25519_KEY_PREFIX) {
        Some(s) => s,
        None => return false,
    };
    let pk_bytes = match B64.decode(pk_b64) {
        Ok(b) => b,
        Err(_) => return false,
    };
    if pk_bytes.len() != 32 || sig_bytes.len() != 64 {
        return false;
    }
    let mut pk_arr = [0u8; 32];
    pk_arr.copy_from_slice(&pk_bytes);
    let mut sig_arr = [0u8; 64];
    sig_arr.copy_from_slice(sig_bytes);
    let vk = match VerifyingKey::from_bytes(&pk_arr) {
        Ok(v) => v,
        Err(_) => return false,
    };
    let sig = DalekSignature::from_bytes(&sig_arr);
    vk.verify(message, &sig).is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn deterministic_signature_for_fixed_seed() {
        let seed: Ed25519Seed = [0x42; 32];
        let a = ed25519_sign_with_seed(&seed, b"hello");
        let b = ed25519_sign_with_seed(&seed, b"hello");
        assert_eq!(a, b);
    }

    #[test]
    fn string_form_has_prefix_and_base64() {
        let seed: Ed25519Seed = [0x42; 32];
        let s = ed25519_sign_string(&seed, b"hello");
        assert!(s.starts_with(ED25519_SIG_PREFIX));
    }

    #[test]
    fn pubkey_form_has_prefix() {
        let seed: Ed25519Seed = [0x42; 32];
        let s = ed25519_pubkey_string(&seed);
        assert!(s.starts_with(ED25519_KEY_PREFIX));
    }

    #[test]
    fn verify_round_trip() {
        let seed: Ed25519Seed = [0x42; 32];
        let pk = ed25519_pubkey_string(&seed);
        let sig = Signature::try_parse(ed25519_sign_string(&seed, b"hello world"))
            .expect("valid signature parses");
        assert!(ed25519_verify_string(&pk, &sig, b"hello world"));
        assert!(!ed25519_verify_string(&pk, &sig, b"goodbye world"));
    }

    #[test]
    fn signature_parse_rejects_prefix_only_shape() {
        let err = Signature::try_parse("ed25519:AAAA".to_string())
            .expect_err("prefix-only signature shape must not construct");
        assert!(
            err.to_string().contains("64-byte Ed25519 signature"),
            "parse error should name the required signature shape: {err}"
        );
    }

    #[test]
    fn signature_round_trips_wire_string_through_display_and_serde() {
        let seed: Ed25519Seed = [0x42; 32];
        let raw = ed25519_sign_string(&seed, b"hello world");
        let signature = Signature::try_parse(raw.clone()).expect("valid signature parses");

        assert_eq!(signature.to_string(), raw);
        assert_eq!(
            serde_json::to_value(&signature).expect("serialize signature"),
            serde_json::Value::String(raw.clone())
        );
        assert_eq!(
            serde_json::from_value::<Signature>(serde_json::Value::String(raw))
                .expect("deserialize signature"),
            signature
        );
    }

    #[test]
    fn verify_raw_signature_round_trip() {
        let seed: Ed25519Seed = [0x42; 32];
        let pk = ed25519_pubkey_string(&seed);
        let sig = ed25519_sign_with_seed(&seed, b"hello world");
        assert!(ed25519_verify_bytes(&pk, &sig, b"hello world"));
        assert!(!ed25519_verify_bytes(&pk, &sig, b"goodbye world"));
    }

    #[test]
    fn verify_rejects_malformed() {
        let seed: Ed25519Seed = [0x42; 32];
        let sig = Signature::try_parse(ed25519_sign_string(&seed, b"x")).expect("signature parses");
        assert!(!ed25519_verify_string("not-prefixed", &sig, b"x"));
        assert!(Signature::try_parse("not-prefixed".to_string()).is_err());
        assert!(Signature::try_parse("ed25519:!!!!".to_string()).is_err());
    }
}
