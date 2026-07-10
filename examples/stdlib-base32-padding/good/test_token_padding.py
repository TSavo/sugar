import base64

def encode_b32_nopad(data: bytes) -> bytes:
    return base64.b32encode(data).rstrip(b"=")

def test_token_padding():
    assert encode_b32_nopad(b"provekit") == b"OBZG65TFNNUXI"
