# uuid.UUID.bytes length logo — discrimination scope

**Surface:** CPython `len(uuid.UUID(...).bytes)`.

**Bug-shape class:** **length/bounds invariant**.

| Half | Assert | Role |
|------|--------|------|
| true | len(UUID(int=0).bytes) == 16 | truth |
| lie | len(UUID(int=0).bytes) == 8 | lie |

Claim: UUID bytes are 16 long on the attribute/callsite coordinate.
