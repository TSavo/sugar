// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Test fixture for the bind integration tests.
// The test-lift path reads these assertions and lifts them into
// the binding's contract evidence.

#[test]
fn test_deposit_positive_amount() {
    let result = deposit(100, 50);
    assert!(result >= 0);
}

#[test]
fn test_withdraw_does_not_go_negative() {
    let result = withdraw(100, 200);
    assert!(result >= 0);
}

// Stand-in declarations so the file compiles without a real crate dep.
fn deposit(balance: i64, amount: i64) -> i64 {
    balance + amount
}
fn withdraw(balance: i64, amount: i64) -> i64 {
    if amount > balance {
        balance
    } else {
        balance - amount
    }
}
