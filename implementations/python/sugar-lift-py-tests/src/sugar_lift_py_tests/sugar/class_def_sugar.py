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
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ClassDef":
            return False
        # Decorated classes construct only when the existing factory recognizer
        # authenticates every decorator as identity-preserving.
        if site.class_decorators() and not cls.decorators_preserve_identity(site):
            return False
        if site.class_keywords():
            return False
        return True

    @staticmethod
    def decorators_preserve_identity(statement) -> bool:
        """Recognize source contracts whose decorator returns the same class."""
        from sugar_lift_py_tests.factory.native_shape import (
            recognizes_identity_decorator,
        )
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        try:
            root = SourceFragment.from_source(
                statement.source, statement.filename or ""
            )
        except (SyntaxError, TypeError):
            return False
        authenticated_names: set[str] = set()
        authenticated_modules: dict[str, str] = {}
        declarations = [
            declaration
            for fragment in root.fragments()
            for declaration in fragment.statements()
        ]
        for declaration in declarations:
            if declaration.observed == "ImportFrom":
                module = declaration.importfrom_module()
                for imported, alias in declaration.importfrom_names():
                    if recognizes_identity_decorator(module, imported):
                        authenticated_names.add(alias or imported)
            elif declaration.observed == "Import":
                for imported, alias in declaration.import_names():
                    authenticated_modules[alias or imported.split(".", 1)[0]] = imported
        for decorator in statement.class_decorators():
            if decorator.observed in {"Name", "Attribute"}:
                receiver = decorator
            elif decorator.observed == "Call":
                receiver = decorator.call_func()
            else:
                return False
            if receiver is None:
                return False
            dotted = receiver.dotted_expr_name()
            if dotted in authenticated_names:
                continue
            if dotted is None:
                return False
            head, separator, tail = dotted.partition(".")
            module = authenticated_modules.get(head)
            if not separator or module is None:
                return False
            qualified = f"{module}.{tail}"
            export_module, _, export_name = qualified.rpartition(".")
            if not recognizes_identity_decorator(export_module, export_name):
                return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "ClassDefSugar":
        # Bases (TERM) and body block (STATEMENT). Never reduce here.
        return cls(
            name=site.class_name(),
            bases=tuple(
                ctx.build_body(base, SugarRole.TERM) for base in site.class_bases()
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
            return self.body.reduce(ctx).and_then(
                lambda record: Complete(self._class_value(accumulated, record))
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda base: self._collect_bases(tuple(rest), (*accumulated, base), ctx)
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
        return (*self.bases, self.body)
