def read(mapping, key): return mapping.get(key)
def demand(imported):
    targetSymbol = imported
    return read({"x": "ordinary"}, targetSymbol)
