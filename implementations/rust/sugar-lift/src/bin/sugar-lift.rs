// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar-lift`: direct invocation entry point.

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let flags = sugar_lift::parse_cli_flags(args);
    let code = sugar_lift::run_cli(flags);
    std::process::exit(code);
}
