# Expectation: sugarbin builds once until Rust FS changes

**Pin:** post-#6208 (`sugarbin` is the only Rust binary door in CI).

## Law
On a given self-hosted runner, after a stamp has been built and published to
the filesystem shelf (`~/.cache/sugar/binary-shelf-v2/…`):

- The **next** CI run with **no** change under `implementations/rust` (and no
  change to sugarbin/toolchain inputs that enter the stamp) must log
  **`filesystem shelf hit`** for each warmed binary.
- It must **not** log `filesystem shelf miss` + `Compiling …` for those stamps.

## Probe
Trigger CI with a non-Rust commit. Inspect prepare “Warm sugarbin shelf”:
only first-ever stamps on that runner may miss; stable Rust → all hits.
