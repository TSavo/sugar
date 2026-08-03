# Numpy Attribute-Safety Showcase

This is the Python class-shapes capstone. It proves a small real numpy wrapper
on two axes:

- The full `python` construction surface lifts classShapes, parameter links,
  and attribute-safety obligations from the library source. The good suite
  discharges every `self.<attr>` access from guaranteed-present classShapes
  attributes. The bad suite accesses a non-guaranteed attribute and must
  refuse. The narrower `python-source` surface deliberately remains limited to
  source-file and universe enumeration.
- `python-pytest-witness` reruns pytest over the same suite. The good suite
  passes with a real `numpy.ndarray`; the bad suite raises `AttributeError`.

The source lifter is scoped to each suite's `src/` directory so the proof axis
only sees the library under test. The witness axis runs pytest over the whole
suite with real numpy installed in the showcase venv.

## Scope

This showcase proves attribute read/access presence, not whole-program
panic-freedom. The `__init__` assignments that create `self.values` and
`self.scale` still surface as attribute-write panic loci in the verifier report,
and they remain undecidable here. That is intentional and loud: Slice 2 proves
that reads such as `self.values` and `self.scale` are present when classShapes
guarantees them. Attribute-write panic-safety is a separate property and is out
of scope for this showcase.
