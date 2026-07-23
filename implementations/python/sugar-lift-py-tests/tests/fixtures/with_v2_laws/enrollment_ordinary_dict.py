values = {"pytest.raises": 1, "other": 2}
def demand(imported):
    targetSymbol = imported
    return values[targetSymbol]
