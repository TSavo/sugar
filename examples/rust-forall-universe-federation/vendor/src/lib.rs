// SPDX-License-Identifier: MIT OR Apache-2.0
//! VENDOR: a real library function. The vendor never swears any per-point
//! vector about it -- the test below swears a bounded-loop LAW, which the
//! rust kit lifts to a forall UNIVERSE (`forall x in 0..8. block_width(x)==64`).

/// Fixed block width for every framing level in this format revision.
pub fn block_width(_level: i32) -> i32 {
    64
}
