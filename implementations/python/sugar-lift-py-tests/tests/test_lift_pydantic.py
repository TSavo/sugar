# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from sugar_lift_py_tests.lift.pydantic import (
    emit_pydantic_model_source,
    lift_pydantic_model,
    lift_pydantic_model_witnesses,
)


class TestPydanticLift:
    def test_pydantic_v2_field_constraints(self):
        pytest.importorskip("pydantic")
        from pydantic import BaseModel, Field

        class User(BaseModel):
            name: str = Field(min_length=1, max_length=100)
            age: int = Field(ge=0, le=150)
            email: str = Field(pattern=r"^[^@]+@[^@]+$")

        decls = lift_pydantic_model(User)
        names = [d.name for d in decls]
        assert "User.name" in names
        assert "User.age" in names
        assert "User.email" in names

    def test_pydantic_v2_numeric_range(self):
        pytest.importorskip("pydantic")
        from pydantic import BaseModel, Field

        class Score(BaseModel):
            value: int = Field(ge=0, le=100)

        decls = lift_pydantic_model(Score)
        assert len(decls) == 1
        decl = decls[0]
        assert decl.name == "Score.value"
        assert decl.pre is not None

    def test_pydantic_v2_annotated_types(self):
        pytest.importorskip("pydantic")
        from pydantic import BaseModel
        from typing import Annotated
        from annotated_types import Gt, Lt

        class Item(BaseModel):
            quantity: Annotated[int, Gt(0), Lt(100)]

        decls = lift_pydantic_model(Item)
        assert len(decls) == 1
        assert decls[0].name == "Item.quantity"

    def test_pydantic_bridge_emits_source_and_lifts_lossy_witness_without_importing_pydantic(
        self,
    ):
        class FieldInfo:
            metadata = []
            min_length = 1
            max_length = None
            ge = None
            gt = None
            le = None
            lt = None
            pattern = None

            def is_required(self):
                return True

        class User:
            __annotations__ = {"name": str}
            model_fields = {"name": FieldInfo()}

        source = emit_pydantic_model_source(
            "User",
            [
                {
                    "name": "name",
                    "type": "str",
                    "field_args": {"min_length": 1},
                }
            ],
        )

        witnesses = lift_pydantic_model_witnesses(
            User,
            concept_site_cid="blake3-512:" + "1" * 128,
            contract_cid="blake3-512:" + "2" * 128,
            original_predicate_text="name is not None and type(name) == str and len(name) >= 1 and normalized(name)",
        )

        assert "class User(BaseModel):" in source
        assert "name: str = Field(..., min_length=1)" in source
        assert witnesses
        assert all(w["source_kind"] == "native-surface" for w in witnesses)
        assert {w["extension_fields"]["surface"] for w in witnesses} == {
            "pydantic-field"
        }
        assert any(w["extension_fields"]["loss_record"] for w in witnesses)
        predicate_text = " ".join(w["predicate_text"] for w in witnesses)
        assert "name != None" in predicate_text
        assert "is_some(name)" in predicate_text
        assert "type(name) == str" in predicate_text
        assert "strlen(name) >= 1" in predicate_text
