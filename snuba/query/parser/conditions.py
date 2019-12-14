from typing import Any, Callable, Optional, OrderedDict, Sequence, TypeVar

from snuba.datasets.dataset import Dataset
from snuba.query.expressions import Column, Expression, Literal, FunctionCall
from snuba.query.conditions import (
    binary_condition,
    ConditionFunctions,
    BooleanFunctions,
)
from snuba.util import is_condition, QUOTED_LITERAL_RE


TExpression = TypeVar("TExpression")


class InvalidConditionException(Exception):
    pass


def parse_conditions(
    simple_expression_builder: Callable[[str], TExpression],
    and_builder: Callable[[Sequence[TExpression]], Optional[TExpression]],
    or_builder: Callable[[Sequence[TExpression]], Optional[TExpression]],
    array_condition_builder: Callable[[str, Sequence[str], TExpression], TExpression],
    simple_condition_builder: Callable[[TExpression, str, Any], TExpression],
    dataset: Dataset,
    conditions: Any,
    array_join: Optional[str],
    depth: int = 0,
) -> Optional[TExpression]:
    """
    Return a boolean expression suitable for putting in the WHERE clause of the
    query.  The expression is constructed by ANDing groups of OR expressions.
    Expansion of columns is handled, as is replacement of columns with aliases,
    if the column has already been expanded and aliased elsewhere.
    """
    from snuba.clickhouse.columns import Array

    if not conditions:
        return ""

    if depth == 0:
        # dedupe conditions at top level, but keep them in order
        sub = OrderedDict(
            (
                parse_conditions(
                    simple_expression_builder,
                    and_builder,
                    or_builder,
                    array_condition_builder,
                    simple_condition_builder,
                    dataset,
                    cond,
                    array_join,
                    depth + 1,
                ),
                None,
            )
            for cond in conditions
        )
        return and_builder([s for s in sub.keys() if s])
    elif is_condition(conditions):
        lhs, op, lit = dataset.process_condition(conditions)

        # facilitate deduping IN conditions by sorting them.
        if op in ("IN", "NOT IN") and isinstance(lit, tuple):
            lit = tuple(sorted(lit))

        # If the LHS is a simple column name that refers to an array column
        # (and we are not arrayJoining on that column, which would make it
        # scalar again) and the RHS is a scalar value, we assume that the user
        # actually means to check if any (or all) items in the array match the
        # predicate, so we return an `any(x == value for x in array_column)`
        # type expression. We assume that operators looking for a specific value
        # (IN, =, LIKE) are looking for rows where any array value matches, and
        # exclusionary operators (NOT IN, NOT LIKE, !=) are looking for rows
        # where all elements match (eg. all NOT LIKE 'foo').
        columns = dataset.get_dataset_schemas().get_read_schema().get_columns()
        if (
            isinstance(lhs, str)
            and lhs in columns
            and isinstance(columns[lhs].type, Array)
            and columns[lhs].base_name != array_join
            and not isinstance(lit, (list, tuple))
        ):
            return array_condition_builder(op, lit, simple_expression_builder(lhs))
        else:
            return simple_condition_builder(simple_expression_builder(lhs), op, lit)

    elif depth == 1:
        sub = (
            parse_conditions(
                simple_expression_builder,
                and_builder,
                or_builder,
                array_condition_builder,
                simple_condition_builder,
                dataset,
                cond,
                array_join,
                depth + 1,
            )
            for cond in conditions
        )
        return or_builder([s for s in sub if s])
    else:
        raise InvalidConditionException(str(conditions))


def parse_conditions_to_expr(expr: Sequence[Any]) -> Expression:
    def simple_expression_builder(val: str) -> Expression:
        # TODO: This will use the schema of the dataset to decide
        # if the expression is a column or a literal.
        if QUOTED_LITERAL_RE.match(val):
            return Literal(None, val[1:-1])
        else:
            return Column(None, val, None)

    def multi_expression_builder(
        expressions: Sequence[Expression], function: str
    ) -> Optional[Expression]:
        if len(expressions) == 0:
            return None
        if len(expressions) == 1:
            return expressions[0]

        return binary_condition(
            None,
            function,
            expressions[0],
            multi_expression_builder(function, expressions[1:]),
        )

    def and_builder(expressions: Sequence[Expression]) -> Optional[Expression]:
        return multi_expression_builder(expressions, BooleanFunctions.AND)

    def or_builder(expressions: Sequence[Expression]) -> Optional[Expression]:
        return multi_expression_builder(expressions, BooleanFunctions.OR)

    def array_condition_builder(
        op: str, literals: Sequence[str], lhs: Expression
    ) -> Expression:
        pass

    def simple_condition_builder(lhs: Expression, op: str, literal: Any) -> Expression:
        pass

    return parse_conditions(
        simple_expression_builder,
        and_builder,
        or_builder,
        array_condition_builder,
        simple_condition_builder,
        dataset,
        conditions,
        query.get_arrayjoin(),
        depth,
    )