class Parcel:
    pass


def read_through_opaque_alias(alias_factory):
    original = Parcel()
    alias = alias_factory(original)
    original.payload = 7
    return alias.payload


class Capsule:
    pass


def renamed_read_through_opaque_alias(project):
    source = Capsule()
    echo = project(source)
    source.marker = 7
    return echo.marker
