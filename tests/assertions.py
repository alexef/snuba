import operator
from contextlib import contextmanager
from typing import Callable, Iterator, TypeVar

T = TypeVar("T")


@contextmanager
def assert_changes(
    callable: Callable[[], T],
    before: T,
    after: T,
    operator: Callable[[T, T], bool] = operator.eq,
) -> Iterator[None]:
    actual = callable()
    assert operator(
        actual, before
    ), f"precondition ({operator}) on {callable} failed: expected: {before!r}, actual: {actual!r}"

    yield

    actual = callable()
    assert operator(
        actual, after
    ), f"postcondition ({operator}) on {callable} failed: expected: {after!r}, actual: {actual!r}"


@contextmanager
def assert_does_not_change(
    callable: Callable[[], T], value: T, operator: Callable[[T, T], bool] = operator.eq,
) -> Iterator[None]:
    actual = callable()
    assert operator(
        actual, value
    ), f"precondition ({operator}) on {callable} failed: expected: {value!r}, actual: {actual!r}"

    yield

    actual = callable()
    assert operator(
        actual, value
    ), f"postcondition ({operator}) on {callable} failed: expected: {value!r}, actual: {actual!r}"
