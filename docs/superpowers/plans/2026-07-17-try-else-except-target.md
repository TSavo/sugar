# Try/else exception-target binding implementation plan

1. Add a focused regression that reduces a try/except/else handler using its
   declared exception target.
2. Add the unnamed-handler bad twin and verify it remains a
   `TemporalContext` panic.
3. Run the focused test before implementation and capture the red missing-name
   terminal.
4. Centralize caught-exception value and handler-entry context construction in
   `try_sugar.py`; route every handler reduction path through it.
5. Add a verdict-bearing `TrySugar` witness whose handler uses the bound target,
   with a refuting wrong-result twin.
6. Run the focused discrimination and witness tests, replay both named corpus
   representatives, and report conservation including the conditional-binding
   residual that must remain loud.
