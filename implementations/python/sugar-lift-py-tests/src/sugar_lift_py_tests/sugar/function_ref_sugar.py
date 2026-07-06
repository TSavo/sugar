from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.outcome import Complete, Outcome


def _from_site_impl(site, functions_by_name):
    """Core recognition logic operating entirely through SourceFragment accessors."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if site.observed != "Name":
        return None
    func_name = site.name_id()
    func_node = functions_by_name.get(func_name)
    if func_node is None:
        return None
    if isinstance(func_node, SourceFragment):
        func_site = func_node
    else:
        func_site = SourceFragment.from_node(func_node, site.filename)
    params = func_site.function_params()
    if len(params) != 1:
        return None
    body_sites = func_site.function_body()
    if len(body_sites) != 1:
        return None
    body_stmt = body_sites[0]
    if body_stmt.observed != "Return":
        return None
    ret_site = body_stmt.return_value()
    if ret_site is None or ret_site.observed != "Name":
        return None
    return FunctionRefSugar(
        name=func_site.function_name(),
        parameter=params[0],
        return_name=ret_site.name_id(),
    )


@dataclass(frozen=True)
class FunctionRefSugar:
    name: str
    parameter: str
    return_name: str

    @classmethod
    def from_site(cls, site, *, functions_by_name):
        return _from_site_impl(site, functions_by_name)

    def desugar(self, ctx=None) -> Outcome:
        del ctx
        return Complete(
            FunctionCallable(
                name=self.name,
                parameter=self.parameter,
                return_name=self.return_name,
            )
        )


def function_ref_sugar(node, functions_by_name):
    """Legacy entry-point accepting a raw AST node -- wraps it in a SourceFragment."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_node(node, "")
    return _from_site_impl(site, functions_by_name)


def function_ref_sugar_from_site(
    site, functions_by_name: dict
) -> "FunctionRefSugar | None":
    """Site-based entry point -- no raw AST required."""
    return _from_site_impl(site, functions_by_name)
