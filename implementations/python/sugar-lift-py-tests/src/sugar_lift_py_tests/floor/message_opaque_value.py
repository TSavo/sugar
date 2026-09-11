"""A proven-message-only opaque value.

When manager receipt seating defers an unresolved value-use because the
reachability slice proved it flows ONLY to a failure-message attribute (never
the suppress/raise decision), and the contract force-floor nonetheless reaches
that coordinate on a symbolic message branch, the value-use consumer yields a
``MessageOpaqueValue`` instead of refusing.  The manager's contract does not
depend on it, so carrying it opaquely is honest — its ONLY basis is the
one-sided ``frame_value_use_is_message_only`` proof.

It is a ``SymbolicValue`` subclass so the whole "symbolic value flows through
arithmetic / string / format operations" machinery the lift already has for
free parameters applies unchanged (``"\\n".join(opaque)``, ``x + opaque``,
``format(opaque)``, truth in a message ternary).  The ONLY additions are the
surfaces ``SymbolicValue`` deliberately refuses — attribute access, call,
iteration, subscript — which for a message opacity yield another message
opacity rather than a named refusal.  Because the slice is sound, a
``MessageOpaqueValue`` can never reach the contract, so this never launders an
unknown into a suppression/raise decision.
"""

from __future__ import annotations

from dataclasses import dataclass

from .symbolic_value import SymbolicValue


@dataclass(frozen=True)
class MessageOpaqueValue(SymbolicValue):
    def _opaque(self):
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self)

    # --- surfaces SymbolicValue refuses: yield another message opacity --------
    def attribute(self, name, site):
        del name, site
        return self._opaque()

    def attribute_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def callable_application_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def call_method_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def call_method_value(
        self, name, arguments, *, owner, blame, ctx=None, keywords=(), required_frame=None
    ):
        del name, arguments, owner, blame, ctx, keywords, required_frame
        return self._opaque()

    def iter_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def next_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def subscript(self, index, site):
        del index, site
        return self._opaque()

    def subscript_with(self, operation, ctx):
        del operation, ctx
        return self._opaque()

    def subscript_with_occurrence(self, index, site, occurrence):
        del index, site, occurrence
        return self._opaque()

    def contains(self, item, site):
        del item, site
        return self._opaque()
