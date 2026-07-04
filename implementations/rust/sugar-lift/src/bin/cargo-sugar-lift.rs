// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `cargo-sugar-lift`: Cargo subcommand entry point.
//
// When the user runs `cargo sugar-lift ...`, Cargo finds this
// binary on PATH and invokes it with argv[1] = "sugar-lift". The
// shared CLI parser strips that token and then reads flags as usual.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let flags = sugar_lift::parse_cli_flags(args);
    let code = sugar_lift::run_cli(flags);
    std::process::exit(code);
}
