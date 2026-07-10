import uuid

def test_true():
    assert len(uuid.UUID(int=0).bytes) == 16

def test_lie():
    assert len(uuid.UUID(int=0).bytes) == 8
