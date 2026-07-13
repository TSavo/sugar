// SPDX-License-Identifier: MIT OR Apache-2.0
use libsugar::core::Dialect;
#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
use std::{fs, io::Write as _};
use sugar_compiler::kit::{Kit, LiftManifest};
use sugar_linker::{link, LinkerCallEdge, LinkerErrorKind, LinkerInputs};

fn manifest(dir: &std::path::Path) -> LiftManifest {
    let script = dir.join("producer.py");
    let mut f = fs::File::create(&script).unwrap();
    f.write_all(br##"#!/usr/bin/env python3
import json,sys
m={"file":"native/libdecoded.a","functionName":"decoded_len_estimate","span":{"startLine":1,"startCol":0,"endLine":1,"endCol":20},"paramNames":["encoded_len"],"sourceCid":"blake3-512:source","templateCid":"blake3-512:template"}
a={"symbol":"decoded_len_estimate","abiSignature":{"formals":[{"kind":"primitive","name":"Int"}],"returns":{"kind":"primitive","name":"Int"},"platformAbiTag":"x86_64-unknown-linux-gnu"},"artifact":{"headerOrSourceCid":"blake3-512:source","objectCid":"blake3-512:object"},"callingConvention":"C","warrant":"source"}
c={"name":"decoded_len_estimate","kit":"rust-native-producer","contract_cid":"blake3-512:contract","formals":["encoded_len"],"formal_sorts":[{"kind":"primitive","name":"Int"}],"post_json":{"kind":"atomic","name":"=","args":[{"kind":"var","name":"out"},{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":3}]},"euf_coordinate":"call:decoded_len_estimate"}
for line in sys.stdin:
 r=json.loads(line); method=r.get("method"); ident=r.get("id")
 if method=="initialize": out={"protocolVersion":"1.0","serverInfo":{"name":"native-producer","version":"1"},"capabilities":{}}
 elif method=="sugar.plugin.kit_declaration": out={"kit":{"id":"rust-native-producer","language":"rust","version":"1"},"rpc":{"methods":[{"name":"sugar.enumerate","required":True}]},"proofResolution":{"strategy":"exported-symbol-contracts","rpcMethod":"sugar.enumerate"},"residueCategories":[]}
 elif method=="sugar.enumerate":
  p=r["params"]; assert p["level"]=="exports"; at=p.get("at")
  out={"nodes":[{"memento":m,"audit":a,"payload":c}],"gaps":[]} if not at or at.get("symbol")=="decoded_len_estimate" else {"nodes":[],"gaps":[{"reason":"symbol not exported by this artifact"}]}
 elif method=="shutdown": out=None
 else: out={}
 print(json.dumps({"jsonrpc":"2.0","id":ident,"result":out}),flush=True)
"##).unwrap();
    #[cfg(unix)]
    {
        let mut p = fs::metadata(&script).unwrap().permissions();
        p.set_mode(0o755);
        fs::set_permissions(&script, p).unwrap();
    }
    LiftManifest {
        surface: "native".into(),
        name: "native-producer".into(),
        dialect: Dialect::Other("native".into()),
        command: vec![script.display().to_string()],
        working_dir: None,
        method: None,
    }
}

#[test]
fn native_export_scan_and_seek_are_coherent_and_typed() {
    let temp = tempfile::tempdir().unwrap();
    let kit = Kit::rendezvous(manifest(temp.path())).unwrap();
    let scanned = kit.exports(temp.path()).unwrap();
    assert_eq!(scanned.len(), 1);
    let export = &scanned[0];
    assert_eq!(export.symbol(), "decoded_len_estimate");
    assert_eq!(export.calling_convention(), "C");
    assert_eq!(export.contract().kit, "rust-native-producer");
    assert_eq!(
        export.contract().euf_coordinate.as_deref(),
        Some("call:decoded_len_estimate")
    );
    let sought = kit
        .export(temp.path(), "decoded_len_estimate")
        .unwrap()
        .unwrap();
    assert_eq!(export.metadata(), sought.metadata());
    assert_eq!(
        export.contract().contract_cid,
        sought.contract().contract_cid
    );
    assert!(kit.export(temp.path(), "absent").unwrap().is_none());

    let good = link(LinkerInputs {
        contracts: vec![sought.contract().clone()],
        call_edges: vec![LinkerCallEdge {
            source_contract_cid: sought.contract().contract_cid.clone(),
            target_contract_cid: None,
            target_symbol: "rust-native-producer:decoded_len_estimate".into(),
            call_site_locus: None,
            import_signature: None,
        }],
    });
    assert!(
        good.linker_errors.is_empty(),
        "producer contract must resolve: {:?}",
        good.linker_errors
    );

    let bad = link(LinkerInputs {
        contracts: vec![sought.contract().clone()],
        call_edges: vec![LinkerCallEdge {
            source_contract_cid: sought.contract().contract_cid.clone(),
            target_contract_cid: None,
            target_symbol: "rust-native-producer:not_the_export".into(),
            call_site_locus: None,
            import_signature: None,
        }],
    });
    assert_eq!(bad.linker_errors.len(), 1);
    assert_eq!(bad.linker_errors[0].kind, LinkerErrorKind::UnresolvedSymbol);
}
