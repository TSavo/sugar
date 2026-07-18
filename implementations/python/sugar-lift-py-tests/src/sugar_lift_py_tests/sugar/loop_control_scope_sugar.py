from __future__ import annotations

from sugar_lift_py_tests.recognition.loop_control_scope import (
    LoopControlScopeClassification,
    LoopControlScopeRecognition,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar


class LoopControlScopeSugar(Sugar):
    """Sugar-owned loop/control scope recognizer.

    Raw source traversal is isolated in the structural recognition layer. This
    Sugar is the sole semantic owner exposed to For, While, Try, and
    comprehension Sugars; the factory contains no loop/control classifier.
    """

    owns = LoopControlScopeRecognition.owns
    classify = LoopControlScopeRecognition.classify
    own_scope_stored_names = LoopControlScopeRecognition.own_scope_stored_names
    loop_stored_names = LoopControlScopeRecognition.loop_stored_names
    loop_carried_names = LoopControlScopeRecognition.loop_carried_names
    has_unclassified_loop_mutation = (
        LoopControlScopeRecognition.has_unclassified_loop_mutation
    )
    while_definite_break_output_names = (
        LoopControlScopeRecognition.while_definite_break_output_names
    )


__all__ = ["LoopControlScopeClassification", "LoopControlScopeSugar"]
