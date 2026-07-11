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
    record; extend_scope binds the class name.

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
        # Decorators and metaclass keywords stay loud gaps this arm.
        if site.class_decorators():
            return False
        if site.class_keywords():
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
        return _call_pair(
            name="class_def_return",
            owner_sugar="ClassDefSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce bases left-to-right, then thread the body under the same scope.
        return self._collect_bases(self.bases, (), ctx)

    def _collect_bases(
        self, remaining: tuple, accumulated: tuple, ctx: object
    ) -> Outcome:
        if not remaining:
            return self.body.reduce(ctx).and_then(
                lambda record: Complete(
                    self._class_value(accumulated, record)
                )
            )
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda base: self._collect_bases(
                tuple(rest), (*accumulated, base), ctx
            )
        )

    def _class_value(self, bases: tuple, record: object):
        from sugar_lift_py_tests.floor import ClassValue

        return ClassValue(name=self.name, bases=bases, record=record)

    def walk_children(self):
        return (*self.bases, self.body)
