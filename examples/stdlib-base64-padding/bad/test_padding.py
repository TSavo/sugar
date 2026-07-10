# BAD TWIN: the padding confusion -- asserting the PADDED standard base64url
# value for a function that rstrip(b"=")'s. Closed strip ambient is total:
# no output of unpadded_urlsafe_b64encode ever ends with '='. Same #euf# key
# as the good twin; padded RHS is unsatisfied under ambient.
import base64


def unpadded_urlsafe_b64encode(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def test_stdlib_base64_padding():
    assert unpadded_urlsafe_b64encode(b"provekit") == b"cHJvdmVraXQ="
