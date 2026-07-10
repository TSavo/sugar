# Vendor-op coordinate scale re-sweep (handoff C)

**Date:** 2026-07-10  
**HEAD:** `origin/main` @ post-#3986 / handoff rev 4  
**Instrument:** `tests/test_vendor_op_coordinate_scale_sweep.py`

## Command

```
cd implementations/python/sugar-lift-py-tests
python tests/test_vendor_op_coordinate_scale_sweep.py
```

## Result (paste the count)

```
scale-sweep total=187 ok=187 gap=0
  chain: 10 shapes, gaps=0
  df_attr: 11 shapes, gaps=0
  df_attrish: 2 shapes, gaps=0
  df_method: 28 shapes, gaps=0
  kwarg_multi: 20 shapes, gaps=0
  ndarray_method: 21 shapes, gaps=0
  series_attr: 13 shapes, gaps=0
  series_method: 40 shapes, gaps=0
  showcase: 4 shapes, gaps=0
  ufunc_binary: 17 shapes, gaps=0
  ufunc_unary: 21 shapes, gaps=0
```

**#3944 claim held:** 187 real API shapes, **0 gaps** through R-drains and coordinate membrane work.

Also: `pytest tests/test_vendor_op_coordinate_scale_sweep.py` → **2 passed**.
