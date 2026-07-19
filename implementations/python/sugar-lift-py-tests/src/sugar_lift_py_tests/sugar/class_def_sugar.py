from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ClassDefSugar(Sugar, role=SugarRole.STATEMENT):
    """`class Name(Base, ...): body` -- thread the body, carry base coordinates.

    Recognition, not MRO/metaclass modeling: reduce each base to its type
    coordinate (Name/Attribute TERM), reduce the body block (method FunctionDefs
    become nested UniverseValues, class-var assigns bind as usual), and the
    result is a ClassValue. contribution splices the body into the enclosing
    record; methods remain deferred FunctionCallable bindings and extend_scope
    binds the class name.

    Owns the plain shape only:
      * no decorators
      * no keywords (metaclass=M stays loud)
      * zero or more bases (each factory-built as TERM)

    Decorated classes and metaclass keywords stay unowned (loud factory gap) --
    never silently drop the body, a base, or a keyword.
    """

    name: str
    bases: tuple[SugarBody, ...]
    class_options: tuple[SugarBody, ...]
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ClassDef":
            return False
        # Decorated classes construct only when recognition authenticates every
        # decorator as identity-preserving (not factory-owned recognition).
        if site.class_decorators() and not cls.decorators_preserve_identity(site):
            return False
        if site.class_keywords():
            from sugar_lift_py_tests.recognition.class_definition import (
                recognize_pydantic_base_model_extra_class,
                recognize_typed_dict_total_class,
            )

            return (
                recognize_typed_dict_total_class(site) is not None
                or recognize_pydantic_base_model_extra_class(site) is not None
            )
        return True

    @staticmethod
    def decorators_preserve_identity(statement) -> bool:
        """Recognize source contracts whose decorator returns the same class."""
        from sugar_lift_py_tests.recognition.class_decorator import (
            class_decorators_preserve_identity,
        )

        return class_decorators_preserve_identity(statement)

    @classmethod
    def new(cls, site, ctx) -> "ClassDefSugar":
        from sugar_lift_py_tests.recognition.class_definition import (
            recognize_pydantic_base_model_extra_class,
            recognize_typed_dict_total_class,
        )

        typed_dict = recognize_typed_dict_total_class(site)
        pydantic_base_model = recognize_pydantic_base_model_extra_class(site)
        class_option = (
            typed_dict.total_value
            if typed_dict is not None
            else (
                pydantic_base_model.extra_value
                if pydantic_base_model is not None
                else None
            )
        )
        return cls(
            name=site.class_name(),
            bases=tuple(
                ctx.build_body(base, SugarRole.TERM) for base in site.class_bases()
            ),
            class_options=(
                ()
                if class_option is None
                else (ctx.build_body(class_option, SugarRole.TERM),)
            ),
            body=ctx.build_body(site.class_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Class body method present; discriminate on the enclosing return face.
        prefix = (
            "def A(z):\n"
            "    class C:\n"
            "        def m(self):\n"
            "            return 1\n"
            "    return 1\n"
            "\n"
        )
        class_local_default = (
            "def B(z):\n"
            "    class C:\n"
            "        def prior(value):\n"
            "            return value\n"
            "        def later(self, callback=prior):\n"
            "            return callback\n"
            "    return z\n"
            "\n"
        )
        accessor_decorated = (
            "import pandas as pd\n"
            "\n"
            '@pd.api.extensions.register_series_accessor("_sugar_witness_5194")\n'
            "class Accessor:\n"
            "    def __init__(self, obj):\n"
            "        self.obj = obj\n"
            "\n"
            "def C():\n"
            "    return 7\n"
            "\n"
        )
        dataclass_decorated = (
            "import dataclasses\n"
            "\n"
            "def D(z):\n"
            "    @dataclasses.dataclass\n"
            "    class Point:\n"
            "        value: int\n"
            "    return z\n"
            "\n"
        )
        guarded_import_dataclass = (
            "try:\n"
            "    import dataclasses\n"
            "except ImportError:\n"
            "    pass\n"
            "\n"
            "def Guarded(z):\n"
            "    @dataclasses.dataclass\n"
            "    class Point:\n"
            "        value: int\n"
            "    return z\n"
            "\n"
        )
        typed_dict_total = (
            "from typing_extensions import TypedDict\n"
            "\n"
            "def E(z):\n"
            "    class Payload(TypedDict, total=False):\n"
            "        value: int\n"
            "    return z\n"
            "\n"
        )
        pydantic_dataclass = (
            "import pydantic\n"
            "\n"
            "def F(z):\n"
            "    @pydantic.dataclasses.dataclass\n"
            "    class Payload:\n"
            "        value: int\n"
            "    return z\n"
            "\n"
        )
        pydantic_base_model_extra = (
            "from pydantic import BaseModel\n"
            "\n"
            "def G(z):\n"
            '    class Payload(BaseModel, extra="allow"):\n'
            "        value: int\n"
            "    return z\n"
            "\n"
        )
        # Call-form identity decorator: PEP 702 warnings.deprecated returns the
        # same class after stamping deprecation metadata (sklearn residual shape).
        deprecated_decorated = (
            "from warnings import deprecated\n"
            "\n"
            "def H(z):\n"
            '    @deprecated("use other")\n'
            "    class Point:\n"
            "        value = 1\n"
            "    return z\n"
            "\n"
        )
        sqlalchemy_orm_decorated = (
            "from sqlalchemy.orm import as_declarative\n"
            "\n"
            "@as_declarative()\n"
            "class Base:\n"
            "    pass\n"
            "\n"
            "def H(z):\n"
            "    return z\n"
            "\n"
        )
        generic_class_subscription = (
            "from typing import Generic, TypeVar\n"
            "\n"
            'T = TypeVar("T")\n'
            "\n"
            "class CommonBase(Generic[T]):\n"
            "    pass\n"
            "\n"
            "class Base(CommonBase[T]):\n"
            "    pass\n"
            "\n"
            "def I(z):\n"
            "    return z\n"
            "\n"
        )
        return (
            _call_pair(
                name="class_def_return",
                owner_sugar="ClassDefSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
                lying=prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="class_local_default_binding_return",
                owner_sugar="ClassDefSugar",
                truthful=class_local_default + "def test_b():\n    assert B(5) == 5\n",
                lying=class_local_default + "def test_b():\n    assert B(5) == 6\n",
                family="class-local-default-binding",
            ),
            _call_pair(
                name="accessor_decorated_class_return",
                owner_sugar="ClassDefSugar",
                truthful=accessor_decorated
                + "def test_c():\n"
                + "    assert C() == 7\n",
                lying=accessor_decorated + "def test_c():\n" + "    assert C() == 8\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="dataclass_decorated_class_return",
                owner_sugar="ClassDefSugar",
                truthful=dataclass_decorated
                + "def test_d():\n"
                + "    assert D(5) == 5\n",
                lying=dataclass_decorated
                + "def test_d():\n"
                + "    assert D(5) == 6\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="guarded_import_dataclass_class_return",
                owner_sugar="ClassDefSugar",
                truthful=guarded_import_dataclass
                + "def test_guarded():\n"
                + "    assert Guarded(5) == 5\n",
                lying=guarded_import_dataclass
                + "def test_guarded():\n"
                + "    assert Guarded(5) == 6\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="typed_dict_total_class_return",
                owner_sugar="ClassDefSugar",
                truthful=typed_dict_total
                + "def test_e():\n"
                + "    assert E(5) == 5\n",
                lying=typed_dict_total + "def test_e():\n" + "    assert E(5) == 6\n",
                family="typed-dict-total-class",
            ),
            _call_pair(
                name="pydantic_dataclass_class_return",
                owner_sugar="ClassDefSugar",
                truthful=pydantic_dataclass
                + "def test_f():\n"
                + "    assert F(5) == 5\n",
                lying=pydantic_dataclass + "def test_f():\n" + "    assert F(5) == 6\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="pydantic_base_model_extra_class_return",
                owner_sugar="ClassDefSugar",
                truthful=pydantic_base_model_extra
                + "def test_g():\n"
                + "    assert G(5) == 5\n",
                lying=pydantic_base_model_extra
                + "def test_g():\n"
                + "    assert G(5) == 6\n",
                family="pydantic-base-model-extra-class",
            ),
            _call_pair(
                name="deprecated_decorated_class_return",
                owner_sugar="ClassDefSugar",
                truthful=deprecated_decorated
                + "def test_h():\n"
                + "    assert H(5) == 5\n",
                lying=deprecated_decorated
                + "def test_h():\n"
                + "    assert H(5) == 6\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="sqlalchemy_orm_decorated_class_return",
                owner_sugar="ClassDefSugar",
                truthful=sqlalchemy_orm_decorated
                + "def test_h():\n"
                + "    assert H(5) == 5\n",
                lying=sqlalchemy_orm_decorated
                + "def test_h():\n"
                + "    assert H(5) == 6\n",
                family="identity-decorated-class",
            ),
            _call_pair(
                name="generic_class_subscription_return",
                owner_sugar="ClassDefSugar",
                truthful=generic_class_subscription
                + "def test_i():\n"
                + "    assert I(5) == 5\n",
                lying=generic_class_subscription
                + "def test_i():\n"
                + "    assert I(5) == 6\n",
                family="generic-class-subscription",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce bases left-to-right, then thread the body under the same scope.
        return self._collect_bases(self.bases, (), ctx)

    def desugar_module_context(self, ctx: object) -> Outcome:
        """Construct the executed module's inert class binding coordinate."""
        from sugar_lift_py_tests.floor import BlockValue
        from sugar_lift_py_tests.floor.local_exception_class_value import (
            module_class_value,
        )

        base_names = tuple(
            base_name
            for base_name in self.site.class_base_names()
            if base_name is not None
        )
        return Complete(
            module_class_value(
                name=self.name,
                base_names=base_names,
                temporal=ctx.temporal,
                record=BlockValue(()),
            )
        )

    def _collect_bases(
        self, remaining: tuple, accumulated: tuple, ctx: object
    ) -> Outcome:
        if not remaining:
            return self._reduce_class_options(self.class_options, accumulated, ctx)
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda base: self._collect_bases(tuple(rest), (*accumulated, base), ctx)
        )

    def _reduce_class_options(
        self, remaining: tuple[SugarBody, ...], bases: tuple, ctx: object
    ) -> Outcome:
        if not remaining:
            return self.body.reduce(ctx).and_then(
                lambda record: Complete(self._class_value(bases, record))
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda _value: self._reduce_class_options(tuple(rest), bases, ctx)
        )

    def _class_value(self, bases: tuple, record: object):
        from sugar_lift_py_tests.floor import (
            BuiltinExceptionClassValue,
            ClassValue,
            ExceptionClassValue,
            LocalExceptionClassValue,
        )

        if any(
            isinstance(
                base,
                (
                    BuiltinExceptionClassValue,
                    ExceptionClassValue,
                    LocalExceptionClassValue,
                ),
            )
            for base in bases
        ):
            return LocalExceptionClassValue(
                name=self.name,
                bases=bases,
                record=record,
            )

        return ClassValue(name=self.name, bases=bases, record=record)

    def walk_children(self):
        return (*self.bases, *self.class_options, self.body)
