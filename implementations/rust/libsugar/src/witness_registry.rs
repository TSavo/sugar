// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::BTreeMap;

use sugar_ir_types::{MigrationReceiptError, WitnessMemento};

#[derive(Debug, Clone, Default)]
pub struct WitnessRegistry {
    by_subject_fixture: BTreeMap<(String, String), Vec<WitnessMemento>>,
}

#[derive(Debug, thiserror::Error)]
pub enum WitnessRegistryError {
    #[error("witness-registry: parse witness: {0}")]
    Parse(#[from] serde_json::Error),
    #[error("witness-registry: invalid witness: {0}")]
    Invalid(#[from] MigrationReceiptError),
}

impl WitnessRegistry {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn admit_json_str(&mut self, text: &str) -> Result<(), WitnessRegistryError> {
        let witness: WitnessMemento = serde_json::from_str(text)?;
        self.admit(witness)
    }

    pub fn admit_many<I>(&mut self, witnesses: I) -> Result<(), WitnessRegistryError>
    where
        I: IntoIterator<Item = WitnessMemento>,
    {
        for witness in witnesses {
            self.admit(witness)?;
        }
        Ok(())
    }

    pub fn admit(&mut self, witness: WitnessMemento) -> Result<(), WitnessRegistryError> {
        witness.validate()?;
        let key = (witness.subject.clone(), witness.fixture_state_cid.clone());
        self.by_subject_fixture
            .entry(key)
            .or_default()
            .push(witness);
        Ok(())
    }

    pub fn get(&self, subject: &str, fixture_state_cid: &str) -> &[WitnessMemento] {
        self.by_subject_fixture
            .get(&(subject.to_string(), fixture_state_cid.to_string()))
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    pub fn len(&self) -> usize {
        self.by_subject_fixture.values().map(Vec::len).sum()
    }

    pub fn is_empty(&self) -> bool {
        self.len() == 0
    }
}
