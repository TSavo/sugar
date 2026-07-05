// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Fixture for provekit bind integration tests.
//
// Two functions covering the three main contract origins:
//   - deposit: has #[requires] / #[ensures] attributes (annotation-lift path)
//   - withdraw: clean body with a guard-then-commit structure (algebra-synthesis path)
//   - identity: trivial identity function (empty-contract path)
//   - retry_send: retry loop shape (algebra-synthesis)
//   - first_or_empty: option-default shape with annotation

// concept: deposit-then-balance
// substrate-origin: annotation-lift
#[cfg_attr(any(), requires(amount > 0))]
#[cfg_attr(any(), ensures(out >= 0))]
pub fn deposit(balance: i64, amount: i64) -> i64 {
    balance + amount
}

pub fn withdraw(balance: i64, amount: i64) -> i64 {
    if amount > balance {
        balance
    } else {
        balance - amount
    }
}

pub fn identity(x: i64) -> i64 {
    x
}

pub fn retry_send(max_attempts: i64) -> bool {
    let mut attempt = 0;
    while attempt < max_attempts {
        attempt += 1;
        if attempt >= 2 {
            return true;
        }
    }
    false
}

#[cfg_attr(any(), requires(items_len >= 0))]
#[cfg_attr(any(), ensures(out >= 0))]
pub fn first_or_empty(items_len: i64) -> i64 {
    if items_len == 0 {
        0
    } else {
        1
    }
}
