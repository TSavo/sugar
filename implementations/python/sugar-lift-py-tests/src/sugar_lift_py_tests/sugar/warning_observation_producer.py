"""The producer of authenticated warning testimony.

``dd3d1b5ca`` (#6458) routed authenticated warnings on completed ``With``
faces, and ``WithEffectBoundarySugar`` has consumed ``WarningObservationValue``
ever since -- but nothing in any ``src`` tree ever CONSTRUCTED one.  Every
warning boundary therefore reached the "unresolved warning producers" refusal
by construction, and the consumer's own twins were green against a category
term (``python:warning_category_identity``) that exists at no revision outside
the test that invented it.  This module is the missing producer, and it emits
the real ``python:exception_type_identity`` the ``raise``/``except`` projection
already mints, so no new vocabulary enters the term table.

The occurrence recognised here is a ``warnings.warn(...)`` call in STATEMENT
position.  Three things bound it, all lexical:

* the callee is the closed import-bound coordinate ``warnings.warn`` --
  ``Call._import_bound_callee_symbol`` refuses a shadowed, parameter or
  ambiguous head, so a local named ``warnings`` mints nothing;
* the operand positions come from CPython's own fixed ``warnings.warn``
  signature, not from a vendor convention;
* the category is authenticated by the ordinary exception-class authenticator
  (``SourceUnit.exception_type_identity``), because a Python warning category
  IS an exception class.

An occurrence that fails any of those keeps its ordinary ``CallSiteValue`` and
rides the record unchanged, where the boundary already names it as an
unresolved warning producer.  Producing nothing is the honest outcome; a bare
``warnings.warn("msg")`` is NOT evidence of a ``UserWarning`` occurrence, since
that default lives in CPython rather than in the source text, and inferring it
here would put an unstated assumption inside an authenticated coordinate.
"""

from __future__ import annotations

# CPython's own signature:
#   warn(message, category=UserWarning, stacklevel=1, source=None, *,
#        skip_file_prefixes=())
# Only the category position is read.  ``stacklevel``/``source`` select the
# frame a warning is ATTRIBUTED to; they do not decide which warning occurred,
# so they neither contribute to nor block the observation.
WARNING_OCCURRENCE_SYMBOL = "warnings.warn"
WARNING_MESSAGE_PARAMETER_INDEX = 0
WARNING_CATEGORY_PARAMETER_INDEX = 1
WARNING_CATEGORY_PARAMETER_NAME = "category"
_WARNING_KEYWORD_PARAMETER_NAMES = frozenset(
    {"message", "category", "stacklevel", "source", "skip_file_prefixes"}
)


def project_warning_observation(value):
    """Project one authenticated ``WarningObservationValue``, or ``None``.

    ``value`` is the reduced statement value.  ``None`` means "this statement
    is not an authenticated warning occurrence" -- never "no warning occurred".
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    if not isinstance(value, CallSiteValue):
        return None
    if value.target_name != WARNING_OCCURRENCE_SYMBOL:
        return None

    keyword_names = value.keyword_names
    keyword_count = len(keyword_names)
    positional = value.arg_values[: len(value.arg_values) - keyword_count]
    keywords = dict(zip(keyword_names, value.arg_values[len(positional) :]))

    # A spread (``**kwargs``) keyword arrives spelled ``**``: the actual set is
    # not closed, so the occurrence is not authenticated.
    if not set(keywords) <= _WARNING_KEYWORD_PARAMETER_NAMES:
        return None
    if len(positional) <= WARNING_MESSAGE_PARAMETER_INDEX and "message" not in keywords:
        return None
    if len(positional) > WARNING_CATEGORY_PARAMETER_INDEX:
        category = positional[WARNING_CATEGORY_PARAMETER_INDEX]
        if WARNING_CATEGORY_PARAMETER_NAME in keywords:
            return None
    else:
        category = keywords.get(WARNING_CATEGORY_PARAMETER_NAME)
    if category is None:
        return None

    identity_reader = getattr(category, "exception_type_identity", None)
    if not callable(identity_reader):
        return None
    identity = identity_reader()
    if identity is None:
        return None
    category_name = _category_spelling(identity)
    if category_name is None:
        return None

    from sugar_lift_py_tests.effect.warning_effect import WarningEffect
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )

    return WarningObservationValue(
        WarningEffect(
            category_name=category_name,
            # The message operand is a constructed value, not necessarily a
            # literal (pandas warns with f-strings).  ``None`` is the documented
            # "no authenticated message carried"; it is not an empty message and
            # cannot discharge a message-pattern obligation.  The boundary keeps
            # message-bearing warning assertions loud on its own side.
            message=None,
            blame=None if value.site is None else str(value.site),
            category_identity=identity,
        )
    )


def _category_spelling(identity):
    """The diagnostic spelling, read OFF the authenticated identity.

    Deliberately not read off the source text: the spelling must never be able
    to disagree with the term that decides the match.
    """
    args = getattr(identity, "args", ())
    if len(args) != 2:
        return None
    name = getattr(args[1], "value", None)
    if not isinstance(name, str):
        return None
    return name
