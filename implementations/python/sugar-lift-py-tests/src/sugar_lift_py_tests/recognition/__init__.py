"""Structural source recognizers used by registered Sugars.

Factory may only select a registered Sugar or panic. Semantic/structural
recognition helpers (including ``recognize_*``) belong here or inside the
owning Sugar — never under ``factory/``.
"""