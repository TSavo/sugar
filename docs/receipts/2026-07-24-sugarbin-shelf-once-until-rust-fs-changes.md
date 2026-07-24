# Expectation: sugarbin builds once until Rust FS changes

**Pin:** after #6210 (monorepo HEAD removed from shelf `build_identity`).

## Law
On a given self-hosted runner, after a stamp has been built and published to
the filesystem shelf (`~/.cache/sugar/binary-shelf-v2/…`):

- The **next** CI run with **no** change under the Rust package input closure
  (and no change to toolchain/platform/profile that enter the stamp) must log
  **`filesystem shelf hit`** for each warmed binary.
- It must **not** log `filesystem shelf miss` + `Compiling …` for those stamps.

## Remembered first-warm stamp (post-#6210)

From a CI run on main @ `8be473aa9293e9dd57e560d91c0d666dd2d7198e`
(Merge #6210 / identity-without-git-head). **First** warm after the identity
formula change — shelf miss + build is expected **once**:

```
sugarbin: filesystem shelf miss for sugar-linux-x86_64-release-blake3-512_a63effa8ba4cfbd85d383ba6a8e86a02181e29a2fd5e870a52e9fa377fd549a8ed86c2f803a9fe268fa0e8ebd4d1cdf5a0cebeed47b354f53d0af399e489b5df
sugarbin: building sugar once for this session (set SUGAR_BIN to skip)
```

**Artifact name (full):**
`sugar-linux-x86_64-release-blake3-512_a63effa8ba4cfbd85d383ba6a8e86a02181e29a2fd5e870a52e9fa377fd549a8ed86c2f803a9fe268fa0e8ebd4d1cdf5a0cebeed47b354f53d0af399e489b5df`

**Identity digest (shelf cell):**
`blake3-512:a63effa8ba4cfbd85d383ba6a8e86a02181e29a2fd5e870a52e9fa377fd549a8ed86c2f803a9fe268fa0e8ebd4d1cdf5a0cebeed47b354f53d0af399e489b5df`

### Pass criterion for the next non-Rust push
Same runner, unchanged Rust inputs → expect:

```
sugarbin: filesystem shelf hit for sugar-linux-x86_64-release-blake3-512_a63effa8ba4cfbd85d383ba6a8e86a02181e29a2fd5e870a52e9fa377fd549a8ed86c2f803a9fe268fa0e8ebd4d1cdf5a0cebeed47b354f53d0af399e489b5df
```

If the digest changes without a Rust FS change, identity is still wrong.
If the digest matches but still **miss**, the shelf is not durable on that runner
(HOME / `SUGAR_BINARY_SHELF_ROOT` / multi-machine scheduling).

## Probe
Trigger CI with a non-Rust commit. Inspect prepare “Warm sugarbin shelf”.
EOF
