# Resolved Binary Profile as Suite Identity

## Goal

Make the authoritative Python package-suite artifact prove which Sugar build
profile it requested and which profile the measured binary actually carries.
A report is provisional unless both values are present, are members of
`{"release", "debug"}`, and are equal.

## Existing boundaries

- `bin/sugarbin` already rejects a path that visibly contradicts the requested
  profile (#6282). That protects path-evident overrides, but an opaque override
  path carries no authenticated profile evidence.
- `<resolved-binary>.sugarbin.json` is written by the binary producer and
  already carries `sourceStamp`, `buildIdentity`, `profile`, and the binary
  checksum. The authoritative workflow already reads `sourceStamp` from this
  manifest.
- `tools/python_package_suite_report.py` serializes suite identity into
  `suite-report.json`.
- `tools/python_suite_identity_gate.py` re-reads the serialized report and
  decides whether it is authoritative or provisional (#6290).

## Design

### Resolution testimony

The workflow requests one explicit profile, currently `release`, and stores it
as `requestedBinaryProfile`. After `bin/sugarbin` resolves the binary, the
workflow reads `profile` from `<binary>.sugarbin.json` and stores it separately
as `resolvedBinaryProfile`.

The workflow must not derive the resolved value from the binary path. The
manifest is the authenticated producer testimony; path spelling remains only
the earlier #6282 fast refusal.

### Missing manifest-profile boundary

A manifest without a `profile` key predates this identity boundary. Resolution
must stop before pytest and emit a distinct diagnostic:

> resolved binary manifest predates the profile identity boundary; rebuild it

This is not a mismatch. A missing value cannot contradict another value because
it provides no testimony at all. The missing-field and mismatch branches have
separate discrimination tests and separate crime identifiers.

### Serialized report fields

`suite-report.json` carries:

```json
{
  "requestedBinaryProfile": "release",
  "resolvedBinaryProfile": "release",
  "authority": {
    "status": "authoritative",
    "profileIdentity": "resolved"
  }
}
```

The report plugin accepts `--suite-requested-binary-profile` and
`--suite-resolved-binary-profile`. It serializes the two values exactly as
provided; it does not infer or repair them.

### Gate law

The post-serialization gate applies these checks in order:

1. If `requestedBinaryProfile` is missing, emit
   `crime=profile-identity-absent` naming the requested field.
2. If `resolvedBinaryProfile` is missing, emit
   `crime=profile-manifest-predates-boundary` with the rebuild instruction.
3. If either populated field is outside `release|debug`, emit
   `crime=profile-identity-malformed`.
4. If both populated fields are valid but unequal, emit
   `crime=profile-identity-mismatch`.
5. Only equal valid values earn profile authority.

The gate continues to return every crime it finds rather than stopping at the
first failure.

### Machine-readable provisional verdict

`suite-report.json` must carry an `authority` object. Before the post-run gate,
the plugin writes:

```json
{
  "status": "provisional",
  "profileIdentity": "unverified"
}
```

The gate rewrites the serialized artifact after checking it:

- no crimes: `status=authoritative`, `profileIdentity=resolved`;
- any crime: `status=provisional`, `profileIdentity=unresolved`, plus a
  `crimes` list containing the exact machine-readable crime identifiers.

Downstream consumers therefore refuse provisional evidence by reading fields,
not by parsing logs. The existing authoritative/provisional artifact naming
remains an additional publication boundary, not the only testimony.

## Files

- `.github/workflows/python-package-suite.yml`
  - declare the requested profile once;
  - read `sourceStamp` and `profile` from the resolved binary manifest;
  - refuse a manifest that predates the profile boundary;
  - pass both profile values to the report plugin.
- `tools/python_package_suite_report.py`
  - add the two command-line options;
  - serialize the two fields and initial provisional authority object.
- `tools/python_suite_identity_gate.py`
  - validate profile presence, enumeration, and equality;
  - write the machine-readable authority verdict back to the report.
- `tools/python_package_suite_summary.py`
  - display requested/resolved profile and authority status without turning
    prose into the gate.
- `tests/test_python_suite_identity_gate_twins.py`
  - green equal-profile face;
  - distinct missing-manifest-profile face and message;
  - malformed requested/resolved faces;
  - release/debug mismatch face;
  - serialized provisional and authoritative verdict faces.

## Testing

1. Run the standalone identity twins red before implementation and green after:

   ```bash
   python3 tests/test_python_suite_identity_gate_twins.py
   ```

2. Run the full repository package for the touched top-level identity tooling:

   ```bash
   python3 -m pytest tests/test_python_suite_identity_gate_twins.py -q
   ```

3. Validate workflow syntax and source contracts through the existing tests,
   then run:

   ```bash
   git diff --check
   ```

No Python verdict baseline is changed. This gate decides whether a measurement
is authoritative; it does not reinterpret failed, error, skipped, or passed
nodes.
