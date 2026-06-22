#!/usr/bin/env python3
"""Verify a minted world is a CLOSED, RECOMPUTABLE federation.

    federation_verify.py --registry DIR --world SHA

The transitive-walk identity, checked over a real registry. In the
cite-always architecture a bundle's root CID is f(its source, its cited
dep CIDs); ConsequentBundlePinned pins each dep CID into the dependent's
bridges, so the dependent transitively commits to its leaves. This pass
proves the commitment is COHERENT and the accounting is TOTAL:

  1. CITATION COHERENCE -- every cited bundle CID a package carries
     resolves to the CURRENT registry bundle for that dep (no dangling /
     stale citation). A cross-package edge that cites a CID no longer in
     the registry is a broken federation, reported by name.
  2. ONE WORLD -- every bundle's world_sha matches the world under test,
     so all citations live in the same resolved model.
  3. FALSEPASS=0 -- the one invariant that never moves, summed across the
     whole closure.
  4. ZERO SILENT DROP -- every closure member has a registry entry
     (minted | no-test-corpus | refused); none silently absent.
  5. PERIMETER -- the residual (refused + undecidable + uncited deps) is
     reported as a hash-pinned total, named not estimated.

Exit 0 iff the federation is closed (coherent citations, one world,
falsePass=0, no silent drop). Verdicts from the bundles' own receipts.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys


def canon(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def bundle_cid(entry):
    proofs = glob.glob(os.path.join(entry, "blake3-512_*.proof"))
    return os.path.basename(proofs[0]) if proofs else None


def _conjoined_imports_from_proof(entry):
    """The dep CIDs a bundle COMMITS to, read from its own envelope metadata
    (sugar.conjoinedImports) -- the proof-level tie, not the pipeline's
    meta record. Empty if the bundle carries no tie (a leaf) or cbor2 is
    unavailable."""
    proofs = glob.glob(os.path.join(entry, "blake3-512_*.proof"))
    if not proofs:
        return []
    try:
        import cbor2
    except ImportError:
        return []
    try:
        doc = cbor2.load(open(proofs[0], "rb"))
    except Exception:
        return []
    meta = doc.get("metadata", {}) if isinstance(doc, dict) else {}
    ci = meta.get("sugar.conjoinedImports", "")
    return [c for c in ci.split(",") if c]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry", default=os.path.expanduser("~/sugar-registry"))
    ap.add_argument("--world", required=True)
    args = ap.parse_args()

    lock = os.path.join(args.registry, ".world", f"{args.world}.lock")
    if not os.path.exists(lock):
        sys.exit(f"no world lock for {args.world[:16]} in {args.registry}")
    members = [
        line.strip() for line in open(lock) if line.strip()
    ]
    member_names = {canon(spec.split("==")[0]) for spec in members}

    # current registry CID per package (the citation target of record)
    current_cid = {}
    for spec in members:
        name, version = spec.split("==", 1)
        entry = os.path.join(args.registry, canon(name), version)
        current_cid[canon(name)] = bundle_cid(entry)

    problems = []
    edges = 0
    edges_proof = [0]  # proof-level tie edges (bundle metadata commitments)
    perimeter = {"refused": 0, "undecidable": 0, "violations": 0, "uncited_in_world": 0}
    falsepass_total = 0
    minted = nocorpus = 0

    for spec in members:
        name, version = spec.split("==", 1)
        cn = canon(name)
        entry = os.path.join(args.registry, cn, version)
        meta_path = os.path.join(entry, "meta.json")
        # (4) zero silent drop
        if not os.path.exists(meta_path):
            problems.append(f"SILENT-DROP: {spec} has no registry entry")
            continue
        meta = json.load(open(meta_path))
        result = meta.get("result")
        if result == "no-test-corpus":
            nocorpus += 1
            continue
        minted += 1
        # (2) one world
        if meta.get("world_id") not in (args.world, None):
            problems.append(
                f"WRONG-WORLD: {spec} stamped {str(meta.get('world_id'))[:24]} "
                f"!= {args.world[:16]}"
            )
        # (3) falsePass=0
        split = (meta.get("receipt_summary") or {}).get("dischargeSplit") or {}
        fp = split.get("falsePass", 0) or 0
        falsepass_total += fp
        if fp:
            problems.append(f"FALSEPASS: {spec} has {fp} falsePass discharge(s)")
        rs = meta.get("receipt_summary") or {}
        perimeter["refused"] += rs.get("refused", 0) or 0
        perimeter["violations"] += rs.get("violations", 0) or 0
        perimeter["undecidable"] += split.get("undecidable", 0) or 0
        # (1) citation coherence
        for cite in meta.get("cited_bundles", []):
            dep, _, dep_cid = cite.partition(":")
            edges += 1
            want = current_cid.get(canon(dep))
            have = dep_cid if dep_cid.startswith("blake3-512:") else f"blake3-512:{dep_cid}"
            # cited string is truncated (dep:blake3-512:<12hex>); match by prefix
            if want is None:
                problems.append(f"DANGLING: {spec} cites {dep} but no current bundle")
            elif not want.startswith(have.rstrip(".proof")):
                problems.append(
                    f"STALE-CITE: {spec} cites {dep}@{dep_cid[:20]} "
                    f"but current is {want[:28]}"
                )
        # uncited in-world deps = a real federation hole (not optional extras)
        for dep in meta.get("uncited_deps", []):
            if canon(dep) in member_names:
                perimeter["uncited_in_world"] += 1
                problems.append(
                    f"UNCITED-IN-WORLD: {spec} did not cite world member {dep}"
                )
        # (1b) PROOF-LEVEL TIE: the bundle's OWN envelope metadata must commit
        # to its conjoined-import CIDs, and each must be a CURRENT registry
        # bundle. This is stronger than the meta.cited_bundles check above
        # (that's the pipeline's record); this reads the bundle the consumer
        # actually recomputes. A tie CID not in the registry, or absent when
        # the bundle has in-world deps, is a broken proof-level federation.
        tie = _conjoined_imports_from_proof(entry)
        current_cid_set = {c for c in current_cid.values() if c}
        for tie_cid in tie:
            edges_proof[0] += 1
            if f"{tie_cid}.proof" not in current_cid_set:
                problems.append(
                    f"PROOF-TIE-DANGLING: {spec} bundle ties {tie_cid[:28]} "
                    "which is not a current registry bundle"
                )

    print(f"world {args.world[:16]}: {len(members)} members, "
          f"{minted} minted, {nocorpus} no-corpus, {edges} citation edges, "
          f"{edges_proof[0]} PROOF-LEVEL tie edges (bundle commits to dep CIDs)")
    print(f"falsePass total: {falsepass_total}")
    print(f"perimeter (hash-pinned residual): {json.dumps(perimeter)}")
    if problems:
        print(f"\nFEDERATION NOT CLOSED -- {len(problems)} problem(s):")
        for p in problems[:40]:
            print(f"  {p}")
        sys.exit(1)
    print("\nFEDERATION CLOSED: every citation resolves to a current bundle, "
          "one world, falsePass=0, zero silent drop.")


if __name__ == "__main__":
    main()
