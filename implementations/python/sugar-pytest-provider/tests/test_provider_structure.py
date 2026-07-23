from sugar_pytest_provider.declaration import *
import pytest

def test_provider_owns_single_export_and_payload_is_typed_slot():
    with pytest.raises(ValueError): pytest_raises_declaration(contract_payload=None)
    d=pytest_raises_declaration(contract_payload=PytestRaisesContractSlot(
        mode="expects", effect_kind="raise", parameters=("expected", "match"),
        expected_type_formal=0, message_pattern_formal=1, binding="exception-info"))
    assert d.provider_kit_id == PROVIDER_KIT_ID
    assert d.bridge_source_symbol == "pytest.raises"

def test_consumer_kit_has_no_provider_declaration_surface():
    import sugar_lift_py_tests.lift_rpc as consumer
    assert not hasattr(consumer, "pytest_raises_declaration")
