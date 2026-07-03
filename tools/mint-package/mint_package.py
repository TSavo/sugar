#!/usr/bin/env python3
"""The bundle factory: one vendor, one version, one mint -- ever.

    mint_package.py <name>==<version> [--registry DIR] [--force]

Resolves the pinned vendor into an isolated venv (their code, executed
only by pip and the witness leg -- never by the walk), fetches the sdist
(wheels strip the test corpus), lifts the vendor's OWN test files through
the shipping CLI (point rows + every universe family), verifies with z3,
and stores bundle + receipts in a content-keyed registry:

    <registry>/<name>/<version>/
        meta.json       name, version, sdist sha256, counts
        verify.json     the real receipt (rows, dischargeSplit incl.
                        undecidable/falsePass buckets -- the perimeter)
        blake3-512_*.proof  the bundle

RESOLVE-ONCE LAW: if the registry entry exists with the same sdist hash,
the factory exits without work -- the thousandth consumer pays a memcmp,
not a re-mint. Verdicts are read from receipts; exit codes are never
trusted.
"""
from __future__ import annotations

import argparse
import blake3  # the system's one content-address function
import glob
import hashlib  # only to match PyPI's published sha256 of the sdist bytes
import json
import os
import shutil
import subprocess
import sys
import tarfile
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))


def canon(name):
    """PEP 503 canonical distribution name: lowercase, runs of -_. collapse
    to a single dash. The registry keys by this so a citation never misses
    a dep over casing/separator drift (Flask vs flask, importlib-metadata
    vs importlib_metadata)."""
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def sh(cmd, **kw):
    print("+", " ".join(str(c) for c in cmd), flush=True)
    return subprocess.run(cmd, check=True, **kw)


def _ensure_kit_venv(registry):
    """A persistent venv holding ONLY the kit's lift-time deps (blake3,
    cbor2, pynacl for the canonicalizer). Kept apart from every world venv
    so the kit's own dependencies never leak into a resolved vendor closure
    as bogus members. Created once, reused across all mints."""
    kit_venv = os.path.join(registry, ".kit", "venv")
    kit_py = os.path.join(kit_venv, "bin", "python")
    if not os.path.exists(kit_py):
        os.makedirs(os.path.dirname(kit_venv), exist_ok=True)
        sh([sys.executable, "-m", "venv", kit_venv])
        sh([os.path.join(kit_venv, "bin", "pip"), "install", "-q",
            "blake3", "cbor2", "pynacl"])
    return kit_py


def _imported_properties(registry, cited):
    """Every obligation `property` that belongs to an imported dependency
    bundle, read from each cited dep's stored verify.json in the registry.
    A dep's pool is transitive-closed (it was minted with its own imports),
    so the union over DIRECT deps already covers the whole import closure.
    These properties are the dep bundles' own obligations -- excluding them
    leaves exactly this package's own rows."""
    props = set()
    for cite in cited:
        dep = cite.split(":", 1)[0]
        for verify_path in glob.glob(
            os.path.join(registry, canon(dep), "*", "verify.json")
        ):
            try:
                doc = json.load(open(verify_path))
            except (OSError, ValueError):
                continue
            for r in doc.get("rows", []):
                p = r.get("property")
                if p:
                    props.add(str(p))
    return props


def _direct_dependencies(venv, package):
    """Direct runtime dependency distribution names of `package`, read from
    the resolved venv's installed metadata (Requires-Dist). Normalized to
    the registry's key convention. Extras/markers are kept conservatively
    (a dep behind an unsatisfied marker still gets its bundle cited if
    minted -- citing an unused contract is harmless; missing one would leave
    a seam opaque)."""
    code = (
        "import sys\n"
        "from importlib.metadata import requires, PackageNotFoundError\n"
        "try:\n"
        "    reqs = requires(sys.argv[1]) or []\n"
        "except PackageNotFoundError:\n"
        "    reqs = []\n"
        "out = []\n"
        "for r in reqs:\n"
        "    name = r.replace('(', ' ').split(';')[0].strip()\n"
        "    for sep in ('==','>=','<=','~=','!=','>','<',' ','['):\n"
        "        if sep in name:\n"
        "            name = name.split(sep)[0]\n"
        "    name = name.strip()\n"
        "    if name:\n"
        "        out.append(name)\n"
        "print('\\n'.join(sorted(set(out))))\n"
    )
    r = subprocess.run(
        [os.path.join(venv, "bin", "python"), "-c", code, package],
        capture_output=True,
        text=True,
    )
    return [d for d in r.stdout.splitlines() if d.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec", help="name==version")
    ap.add_argument(
        "--registry", default=os.path.expanduser("~/sugar-registry")
    )
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--venv",
        default=None,
        help="shared world venv (from the corpus orchestrator's conjoined "
        "resolution); per-package venv is the single-package fallback",
    )
    ap.add_argument(
        "--world",
        default=None,
        help="blake3-512 id of the conjoined resolution (the world's identity); "
        "recorded in meta so citation edges are coherence-checkable",
    )
    args = ap.parse_args()
    if "==" not in args.spec:
        sys.exit("spec must be pinned: name==version (the resolve-once key)")
    name, version = args.spec.split("==", 1)

    entry = os.path.join(args.registry, canon(name), version)
    meta_path = os.path.join(entry, "meta.json")
    work = os.path.join(entry, "work")
    os.makedirs(entry, exist_ok=True)

    # ── fetch the sdist first: its hash IS the identity ──────────────────
    sdist_dir = os.path.join(entry, "sdist")
    os.makedirs(sdist_dir, exist_ok=True)
    if not glob.glob(os.path.join(sdist_dir, "*")):
        sh(
            [
                sys.executable, "-m", "pip", "download", "--no-deps",
                "--no-binary", ":all:", "-d", sdist_dir, args.spec, "-q",
            ]
        )
    sdist = sorted(glob.glob(os.path.join(sdist_dir, "*")))[0]
    sdist_sha = hashlib.sha256(open(sdist, "rb").read()).hexdigest()

    if os.path.exists(meta_path) and not args.force:
        prior = json.load(open(meta_path))
        if prior.get("vendor_sdist_sha256") == sdist_sha:
            print(
                f"already minted (resolve-once): {args.spec} "
                f"sha256={sdist_sha[:16]}... -> {entry}"
            )
            return
        sys.exit(
            f"REFUSE: registry holds {args.spec} with a DIFFERENT sdist hash "
            f"({prior.get('vendor_sdist_sha256','?')[:16]} vs {sdist_sha[:16]}); "
            "same name+version, different bytes is a supply-chain alarm, "
            "not a re-mint. Use --force only if you know why."
        )

    shutil.rmtree(work, ignore_errors=True)
    os.makedirs(work)

    # ── the world: ONE conjoined resolution, shared across the corpus ────
    # (per-package isolated venvs mint bundles whose vendor-cites-vendor
    # edges dangle across incompatible worlds; the corpus orchestrator
    # conjoins every requirement set, resolves ONCE, and every mint walks
    # in that single model.)
    if args.venv:
        venv = args.venv
    else:
        venv = os.path.join(entry, "venv")
        if not os.path.exists(os.path.join(venv, "bin", "python")):
            sh([sys.executable, "-m", "venv", venv])
            sh([os.path.join(venv, "bin", "pip"), "install", "-q", args.spec])
    site = subprocess.run(
        [
            os.path.join(venv, "bin", "python"),
            "-c",
            "import site; print(site.getsitepackages()[0])",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    # ── unpack the sdist; harvest the vendor's own test files ─────────────
    src = os.path.join(work, "src")
    os.makedirs(src)
    if sdist.endswith(".zip"):
        zipfile.ZipFile(sdist).extractall(src)
    else:
        tarfile.open(sdist).extractall(src, filter="data")
    test_files = sorted(
        set(
            glob.glob(os.path.join(src, "**", "test_*.py"), recursive=True)
            + glob.glob(os.path.join(src, "**", "*_test.py"), recursive=True)
        )
    )
    if not test_files:
        json.dump(
            {
                "package": name,
                "version": version,
                "vendor_sdist_sha256": sdist_sha,
                "result": "no-test-corpus",
                "note": "the sdist ships no test files; nothing is sworn, "
                "nothing is minted -- the perimeter is the whole package",
            },
            open(meta_path, "w"),
            indent=2,
        )
        print(f"NO TEST CORPUS: {args.spec}; perimeter recorded, no mint")
        return

    project = os.path.join(work, "project")
    lift_dir = os.path.join(project, ".sugar", "lift", "python-tests")
    os.makedirs(lift_dir)

    # BOUNDARY-CITATION: place each resolved DIRECT dependency's already-minted
    # bundle into this project's .sugar/imports/ (CID-named, as the loader
    # requires). The verifier's M*N bridge then cites b's contract by CID at
    # every a->b callsite instead of leaving an opaque cross-package term --
    # ConsequentBundlePinned makes the citation recompute-not-trust. Deps must
    # be minted FIRST (the orchestrator topo-sorts, leaves-up); a missing dep
    # bundle is recorded, never silently skipped.
    imports_dir = os.path.join(project, ".sugar", "imports")
    os.makedirs(imports_dir)
    cited, dep_misses = [], []
    for dep in _direct_dependencies(venv, name):
        dep_proofs = glob.glob(
            os.path.join(args.registry, canon(dep), "*", "blake3-512_*.proof")
        )
        if dep_proofs:
            proof = sorted(dep_proofs)[0]
            shutil.copyfile(proof, os.path.join(imports_dir, os.path.basename(proof)))
            cited.append(f"{dep}:{os.path.basename(proof)[:23]}")
        else:
            dep_misses.append(dep)

    copied = 0
    for tf in test_files:
        dst = os.path.join(
            project, os.path.relpath(tf, src).replace(os.sep, "__")
        )
        shutil.copyfile(tf, dst)
        copied += 1

    open(os.path.join(project, ".sugar", "config.toml"), "w").write(
        '[[plugins]]\nname = "python-tests-lift"\nkind = "lift"\n'
        'surface = "python-tests"\n\n[solvers]\ndefault = "z3"\n\n'
        '[solvers.dispatch]\nlinear_arithmetic = "z3"\ndefault = "z3"\n\n'
        '[solvers.z3]\nbinary = "z3"\nflags = ["-smt2", "-in"]\n'
    )
    # The KIT venv (blake3/cbor2 for the canonicalizer) is SEPARATE from the
    # world venv so the kit's own deps never contaminate the resolved vendor
    # closure (else they leak in as bogus world members). The shim runs the
    # kit python with the WORLD site on PYTHONPATH, so find_spec still resolves
    # each vendor's installed source while the canonicalizer's imports come
    # from the kit venv.
    kit_py = _ensure_kit_venv(args.registry)
    shim = os.path.join(project, "lift-shim.sh")
    open(shim, "w").write(
        "#!/usr/bin/env bash\nset -euo pipefail\n"
        f'export PYTHONPATH="{REPO}/implementations/python/sugar-lift-py-tests/src:'
        f'{REPO}/implementations/python/sugar-lift-python-source/src:{site}"\n'
        f'exec "{kit_py}" -m sugar_lift_py_tests.lift_rpc --rpc\n'
    )
    os.chmod(shim, 0o755)
    open(os.path.join(lift_dir, "manifest.toml"), "w").write(
        'name = "python-tests-lift"\nversion = "0.1.0-draft"\n'
        'protocol_version = "pep/1.7.0"\nkind = "lift"\n'
        'command = ["./lift-shim.sh"]\nworking_dir = "."\n\n'
        '[capabilities]\nauthoring_surfaces = ["python-tests"]\n'
        'ir_version = "v1.1.0"\nemits_signed_mementos = false\n'
    )

    # ── the shipping CLI is the ground ─────────────────────────────────────
    bin_ = os.path.join(REPO, "implementations/rust/target/debug/sugar")
    target = os.environ.get(
        "CARGO_TARGET_DIR", os.path.join(REPO, "implementations/rust/target")
    )
    bin_ = os.path.join(target, "debug", "sugar")
    if not os.path.exists(bin_):
        sh(
            [
                "cargo", "build", "--manifest-path",
                os.path.join(REPO, "implementations/rust/Cargo.toml"),
                "-p", "sugar-cli", "--bin", "sugar",
            ]
        )
    sh([bin_, "mint", "--out", "."], cwd=project)
    verify_path = os.path.join(entry, "verify.json")
    with open(verify_path, "w") as vf:
        subprocess.run(
            [bin_, "verify", "--project", ".", "--json"],
            cwd=project,
            stdout=vf,
        )
    receipt = json.load(open(verify_path))

    bundle_cid = None
    for proof in glob.glob(os.path.join(project, "blake3-512_*.proof")):
        shutil.copy(proof, entry)
        bundle_cid = os.path.basename(proof).replace(".proof", "")

    # PER-BUNDLE ACCOUNTING, not per-pool. `sugar verify --project` loads the
    # imported dep bundles and re-verifies the WHOLE pool, so the receipt's
    # rows are the entire import closure, not this package's own obligations.
    # A dep's rows belong to the DEP's bundle, not ours. Since deps are minted
    # leaves-up and each dep's pool is itself transitive-closed, this package's
    # OWN rows are its pool MINUS the union of its direct deps' pools (keyed by
    # property identity). The imports are dischargers of our cross-package
    # calls, never obligations we re-claim.
    import_props = _imported_properties(args.registry, cited)
    own_rows = [
        r
        for r in receipt.get("rows", [])
        if str(r.get("property", "")) not in import_props
    ]

    def _own_count(*statuses):
        return sum(1 for r in own_rows if r.get("status") in statuses)

    universes = sum(
        1 for r in own_rows if "::assertion" in str(r.get("property", ""))
    )
    own_split = (receipt.get("dischargeSplit") or {})
    own_summary = {
        "ownRows": len(own_rows),
        "discharged": _own_count("discharged"),
        "refused": _own_count("refused"),
        "violations": _own_count("unsatisfied", "violation", "violated"),
        "undecidable": _own_count("undecidable"),
        # falsePass is per-row (dischargeMethod), the invariant that never moves
        "falsePass": sum(
            1 for r in own_rows if r.get("dischargeMethod") == "falsePass"
        ),
    }

    # THE PERIMETER, HASH-PINNED: the residual is every OWN row NOT discharged
    # -- the refused, undecidable, and violated obligations of THIS bundle,
    # named by property. Content-addressed (blake3-512, the system's one hash)
    # so the residual is a single recomputable CID, not an estimate.
    residual = sorted(
        f"{r.get('status')}:{r.get('property')}"
        for r in own_rows
        if r.get("status") not in ("discharged", None)
    )
    # blake3-512, the system's ONE content-address function -- the same hash
    # the substrate uses for every CID. There is no reason to reach for a
    # different one; the CID is the identity, and the identity scheme is
    # singular. Same source against the same world -> same perimeter CID; any
    # change to what we could-not-discharge moves it.
    perimeter_blob = "\n".join(residual).encode()
    perimeter_cid = (
        "blake3-512:" + blake3.blake3(perimeter_blob).digest(length=64).hex()
        if residual
        else None
    )

    meta = {
        "package": name,
        "version": version,
        # THE PROVENANCE SEAM, in two adjacent fields. The hash CHANGES at the
        # trust boundary, and seeing both here tells the whole chain of custody:
        #   vendor_sdist_sha256 -- PyPI's OWN published hash of the sdist bytes,
        #     recomputed by us to confirm the source is what the vendor swore.
        #     Their attestation, in their hash. This is the only sha256 we keep.
        #   bundle_cid -- OUR blake3-512 content address of everything we
        #     derived from that verified source. From here down it is all ours,
        #     in the system's one hash. The no-vendor axiom in two fields: their
        #     word verified, then our recomputation.
        "vendor_sdist_sha256": sdist_sha,
        "bundle_cid": bundle_cid,
        "world_id": args.world,
        "test_files": copied,
        "result": "minted",
        # receipt_summary is the OWN (per-bundle) accounting -- import rows
        # excluded, so a dep's obligations are never re-counted as ours. The
        # dischargeSplit.falsePass shape is preserved for downstream readers.
        "receipt_summary": {
            "discharged": own_summary["discharged"],
            "refused": own_summary["refused"],
            "violations": own_summary["violations"],
            "dischargeSplit": {
                "undecidable": own_summary["undecidable"],
                "falsePass": own_summary["falsePass"],
            },
        },
        # pool view = the whole import closure sugar verify produced; kept for
        # context, never conflated with own.
        "pool_receipt_summary": {
            k: receipt.get(k)
            for k in ("totalCallsites", "discharged", "violations", "refused", "dischargeSplit")
        },
        "assertion_properties": universes,
        "cited_bundles": cited,
        "uncited_deps": dep_misses,
        "perimeter": {
            "cid": perimeter_cid,
            "count": len(residual),
            "rows": residual,
        },
    }
    json.dump(meta, open(meta_path, "w"), indent=2)
    shutil.rmtree(work, ignore_errors=True)
    print(
        f"MINTED: {args.spec} sha256={sdist_sha[:16]}... "
        f"tests={copied} receipt={meta['receipt_summary']} -> {entry}"
    )


if __name__ == "__main__":
    main()
