# #7345 disjoint lexical-Call rewrite incidence

Measured at exact main `82ed198ba2973b31ebf9c83641155ee6aa3ef9c9`
against authenticated pandas `3.0.3`, aggregate hash
`bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c`.

The selection rule differs from Hockney's size-screened five-file sample:
order the authenticated pin manifest by `sha256(relative_path)`, exclude those
five files, and take the first ten files containing a static nested-function
call candidate. The rule inspected 117 manifest paths. Rewrite and stranding
outcomes do not participate in selection. One selected static candidate had
zero enrolled lexical calls and remains in the result rather than being
postfiltered.

The unpiped command was:

```sh
bin/brun -- env PYTHONPATH=implementations/python/sugar-source-tree/src:implementations/python/sugar-lift-py-tests/src:implementations/python/sugar-lift-python-source/src python3 tools/lexical_call_rewrite_incidence.py
```

It exited `0`. Across the ten named files, nine carried enrolled lexical-call
rows. All 54 of 54 enrolled lexical Calls rewrote and all 54 distinct producer
rows were stranded. The broader temporal fold rewrote 1,765 of 2,415 reached
Call objects.

No enrolled Call that remained unrevised appeared in this slice. That is a
negative result bounded to these ten files, not a claim that such a control
does not exist elsewhere. The result is a lower bound over the named files,
not a corpus estimate.

An earlier run emitted `strandedRows=55` for 54 enrolled rows because one
producer row was visited twice. That run is discarded. The recorded probe
deduplicates stranding by physical producer-row identity; the reproduced
result is 54 distinct stranded rows.
