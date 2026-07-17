# Source Contextmanager Callsite Contract Plan

**Goal:** Carry the exact installed-source contextmanager exit contract to its
callsite and avoid an unnecessary producer-result dig when no `as` value is
demanded.

**Constraints:** Part of #4921. No RuntimeEffect constructor. No panic
weakening. No full-corpus sweep. Author T Savo
`<evilgenius@nefariousplan.com>`. Do not merge.

1. Pin source-derived callable testimony and its conditional-handler bad twin.
2. Carry the contract through `FunctionCallable.callsite`.
3. Pin `WithSugar` discrimination: exact contract skips producer-result dig;
   missing contract still panics.
4. Add and run a source-contextmanager truthful/lying witness.
5. Replay both named representatives and report the decidable subset plus the
   residual with exact conservation.
6. Rebase, Black 26.5.1, focused tests, commit, draft PR `Part of #4921`, post
   receipt, and mark ready. Do not merge.

