import unittest

SCALARS = (str, bytes, int, float, bool, type(None))
SEQUENCES = (tuple, list, set, frozenset)


def is_serializable(value) -> bool:
    """True for the plain values execnet, the transport of pytest-xdist, can send to its controller."""
    if isinstance(value, SEQUENCES):
        return all(is_serializable(item) for item in value)
    if isinstance(value, dict):
        return all(is_serializable(key) and is_serializable(item) for key, item in value.items())
    return type(value) in SCALARS


def guard_sub_test(original):
    def sub_test(self, *args, **params):
        for name, value in params.items():
            if not is_serializable(value):
                self.fail(
                    f"subTest parameter {name!r} is a {type(value).__name__} that pytest-xdist cannot send "
                    "to its controller; pass a str, number, bool, None, or a plain list, tuple, set, or dict of those"
                )
        return original(self, *args, **params)

    sub_test.__doc__ = original.__doc__
    return sub_test


unittest.TestCase.subTest = guard_sub_test(unittest.TestCase.subTest)
