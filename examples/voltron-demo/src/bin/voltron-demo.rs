// SPDX-License-Identifier: MIT OR Apache-2.0
//
// voltron-demo binary entry — thin shell that invokes the library's
// spine and prints the result.

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let input = r#"{"event_type":"signup","user":"alice","payload":{"age":30}}"#;
    let summary = voltron_demo::run_voltron_demo(input)?;
    println!("{summary}");
    Ok(())
}
