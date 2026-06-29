# CONSUMER: imports the vendor's encoder, writes its OWN unit test about an
# input the vendor never swore. With the vendor's .proof staged in
# .sugar/imports/, `sugar prove` conjoins the consumer's fact with the vendor's
# universe via the .proof -- "eHl6" is the correct base64 of "xyz", so SAT.
from b64vendor import encodeBase64


def test_consumer():
    assert encodeBase64("xyz") == "eHl6"
