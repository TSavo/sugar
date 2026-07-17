# Constructor call evidence design

## Scope

Issue #4727 tracks the 17-file `ConstructorCallSugar` fatal-corpus front from
#4684. The front is not one missing permissive fallback: it contains generated
field constructors, positional defaults, inherited constructors, and
effectful `__init__` bodies.

## Construction boundary

The closed static subset is:

- an exact `@dataclass` class whose body contains annotation-only fields and
  whose call supplies exactly one positional argument per field;
- an exact `NamedTuple` subclass with annotation-only fields and exact
  positional arity;
- an explicit `__init__` with only ordinary positional parameters, trailing
  defaults, and the existing assignment-only body. Missing trailing arguments
  are reduced from the actual default-expression source fragments.

These forms construct the existing `ObjectValue` and `ObjectField` evidence.
No parallel object vocabulary is introduced.

Everything outside that proven subset remains loud:

- inherited constructors, dynamic bases, decorators other than exact
  `@dataclass`, and effectful `__init__` statements produce a named
  `ConstructorRuntimeEffect`;
- statically impossible positional arity produces the existing witnessed
  `TypeErrorRuntimeEffect`.

Both effects are authenticated by a constructor-call term containing the
actual reduced argument terms and the genuine call-site `SourceFragment`.
Presence is not success and an effect never yields an `ObjectValue`.

## Discrimination

- Dataclass, NamedTuple, and positional-default truth twins discharge from
  constructed fields; wrong twins refute.
- Inherited/effectful constructors stay typed red with a mandatory witness.
- Impossible arity stays a witnessed type error.
- The existing assignment-only constructor witness remains truthful/lying
  discriminating.

Focused corpus children must eliminate `owner=ConstructorCallSugar` by either
constructing evidence or advancing to a different loud named boundary. No
partial report or caught factory panic counts as completion.
