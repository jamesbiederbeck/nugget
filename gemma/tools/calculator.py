import ast
import operator

SCHEMA = {
    "type": "function",
    "function": {
        "name": "calculator",
        "description": "Evaluate a safe arithmetic expression",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Arithmetic expression to evaluate, e.g. '2 + 2' or '(10 * 3) / 4'",
                }
            },
            "required": ["expression"],
        },
    },
}

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"unsupported literal: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op = type(node.op)
        if op not in _OPS:
            raise ValueError(f"unsupported operator: {op}")
        return _OPS[op](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp):
        op = type(node.op)
        if op not in _OPS:
            raise ValueError(f"unsupported operator: {op}")
        return _OPS[op](_eval(node.operand))
    raise ValueError(f"unsupported node: {type(node).__name__}")


def execute(args: dict) -> dict:
    expr = args.get("expression", "")
    try:
        result = _eval(ast.parse(expr, mode="eval"))
        return {"result": result, "expression": expr}
    except Exception as e:
        return {"error": str(e), "expression": expr}
