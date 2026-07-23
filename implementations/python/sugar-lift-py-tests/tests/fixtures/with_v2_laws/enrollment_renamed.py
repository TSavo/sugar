class EffectBoundary: pass
class Sugar: pass
class WithResourceSugar(Sugar): pass
def f9(): return EffectBoundary()
q3 = {"opaque_key": f9}
def z2(k): return q3[k]()
def demand(imported):
    targetSymbol = imported
    return WithResourceSugar(z2(targetSymbol))
