# Array-function dispatch recognizer plan

1. Pin the current NumPy enumeration failure at the `array_function_dispatch`
   decorator callsite and add a focused red regression for its missing body.
2. Extend the factory-owned keyword-call recognizer at the exact
   `functools.partial` import coordinate so it constructs a pre-bound callable
   through the existing callable floor.
3. Prove the constructed partial supplies the real
   `numpy._core.overrides.array_function_dispatch` body, while unresolved and
   lookalike coordinates remain loud.
4. Re-run focused enumeration, witness, claim-mass, and provenance-matched local
   binary receipts; re-pin any moved claim-mass fixture.
