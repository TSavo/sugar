# build witness showcase

This showcase ties the existing witness protocol to install/build scripts. A
build script can assert no source-language contracts, but its run is still
witnessable: input CIDs plus output artifact CIDs form a content-addressed
witness body. The semantic kill is a plain solver claim over those CIDs; the
build kit does not get to decide it by returning a verdict string.

```sh
./run.sh
```

## What It Proves

The fixture is a deterministic configure-style build:

- `repo/configure.py` is the script in the source repository.
- `distributed/configure.py` is the distributed script.
- `src/message.txt` and `src/version.txt` are source inputs.
- `distributed/libdemo.txt` is the distributed artifact.
- `.build/libdemo.txt` is the rebuilt artifact.

The build witness records the repo script CID, distributed script CID,
source-tree CID, toolchain id, and output artifact CIDs. The lift emits two
plain consistency claims:

- repo script CID equals distributed script CID
- distributed output CID equals rebuilt output CID

Each equality carries custom execution-witness evidence pinned to the shared
build-witness package CID. The Rust verifier asks the untrusted kit resolver to
rerun the build and return only bytes, then independently checks the BLAKE3 CID
and committed outcome before discharging either equality.

## Twins

- `good`: repo script, distributed script, and rebuilt artifact all match.
- `bad-script`: distributed script differs from the repo script, the xz-shaped
  tarball gap. The failed shared package leaves both witness-backed equality
  rows unsatisfied even if the discharge command lies and returns `DISCHARGED`.
- `bad-output`: distributed artifact differs from the rebuilt artifact. The
  failed shared package leaves both witness-backed equality rows unsatisfied
  even if the discharge command lies and returns `DISCHARGED`.
- `tampered-script`: a good witness is minted first, then the distributed
  script is changed before verification. Recompute produces a different witness
  CID, so Rust refuses the stale proof.
- `tampered-output`: a good witness is minted first, then the distributed
  artifact is changed before verification. Recompute produces a different
  witness CID, so Rust refuses the stale proof.

## Residual

Non-reproducible builds cannot be recompute-verified by this witness. A build
that embeds timestamps, random IDs, host paths, network downloads, or compiler
non-determinism must be refused or made reproducible first; this showcase does
not fake determinism.
