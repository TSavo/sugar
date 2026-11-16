"""Shared ExitSet helpers for Try and With contract routing.

A boundary hands back the ExitSet it routed. No completed record holds a halt
(#7826), so nothing here promotes a halt out of a record, and nothing projects
an ExitSet back onto a linear block view.
"""

from __future__ import annotations
