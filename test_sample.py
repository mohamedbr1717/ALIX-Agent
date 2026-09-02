import ast
import logging
import operator

logger = logging.getLogger(__name__)

MAX_EXPR_LEN = 2000
MAX_AST_DEPTH = 30
MAX_AST_NODES = 500
MAX_INT_BITS = 1024

class SafeEvalError(Exception):
    """Custom exception for safe evaluation errors."""
    pass

def _enforce_value_limits(val):
    if isinstance(val, int) and not isinstance(val, bool):
        if val.bit_length() > MAX_INT_BITS:
            raise SafeEvalError("Security Violation: Evaluated integer exceeds bit limit")
    return val

def _validate_ast_security(node, depth=0, count=0):
    if depth > MAX_AST_DEPTH:
        raise SafeEvalError("Security Violation: AST depth limit exceeded")
    
    if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool):
        if node.value.bit_length() > MAX_INT_BITS:
            raise SafeEvalError("Security Violation: Integer value exceeds bit limit")
            
    for child in ast.iter_child_nodes(node):
        count += 1
        if count > MAX_AST_NODES:
            raise SafeEvalError("Security Violation: AST node count limit exceeded")
        _validate_ast_security(child, depth + 1, count)

def _evaluate_node(node):
    if isinstance(node, ast.Expression):
        return _evaluate_node(node.body)
    elif isinstance(node, ast.Constant):
        return _enforce_value_limits(node.value)
    elif isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand)
        if isinstance(node.op, ast.UAdd):
            return +operand
        elif isinstance(node.op, ast.USub):
            return -operand
        elif isinstance(node.op, ast.Not):
            return not operand
        raise SafeEvalError(f"Unsupported unary operator: {type(node.op).__name__}")
    elif isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left)
        right = _evaluate_node(node.right)
        if isinstance(node.op, ast.Add):
            return _enforce_value_limits(left + right)
        elif isinstance(node.op, ast.Sub):
            return _enforce_value_limits(left - right)
        elif isinstance(node.op, ast.Mult):
            return _enforce_value_limits(left * right)
        elif isinstance(node.op, ast.Div):
            if right == 0:
                raise SafeEvalError("Division by zero")
            return left / right
        elif isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise SafeEvalError("Division by zero")
            return left // right
        elif isinstance(node.op, ast.Mod):
            if right == 0:
                raise SafeEvalError("Division by zero")
            return left % right
        elif isinstance(node.op, ast.Pow):
            return _enforce_value_limits(left ** right)
        raise SafeEvalError(f"Unsupported binary operator: {type(node.op).__name__}")
    elif isinstance(node, ast.Compare):
        left = _evaluate_node(node.left)
        ops_map = {
            ast.Eq: operator.eq,
            ast.NotEq: operator.ne,
            ast.Lt: operator.lt,
            ast.LtE: operator.le,
            ast.Gt: operator.gt,
            ast.GtE: operator.ge,
        }
        for op, comparator in zip(node.ops, node.comparators):
            op_type = type(op)
            if op_type not in ops_map:
                raise SafeEvalError(f"Unsupported comparison operator: {op_type.__name__}")
            right = _evaluate_node(comparator)
            if not ops_map[op_type](left, right):
                return False
            left = right
        return True
    elif isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            for val in node.values:
                if not _evaluate_node(val):
                    return False
            return True
        elif isinstance(node.op, ast.Or):
            for val in node.values:
                res = _evaluate_node(val)
                if res:
                    return res
            return False
        raise SafeEvalError(f"Unsupported boolean operator: {type(node.op).__name__}")
    else:
        raise SafeEvalError(f"Unsupported expression type: {type(node).__name__}")

def safe_eval(data):
    if not isinstance(data, str):
        raise SafeEvalError("Input must be a string")
    if len(data) > MAX_EXPR_LEN:
        raise SafeEvalError("Input string exceeds maximum allowed length")
    try:
        parsed = ast.parse(data, mode="eval")
        _validate_ast_security(parsed)
        return _evaluate_node(parsed)
    except SyntaxError as exc:
        logger.info("Failed to evaluate input (len=%d): %s", len(str(data)) if data else 0, exc)
        raise SafeEvalError(f"Invalid syntax (unsupported expression type): {exc}") from exc
    except SafeEvalError as exc:
        logger.info("Failed to evaluate input (len=%d): %s", len(str(data)) if data else 0, exc)
        raise
    except Exception as exc:
        logger.info("Failed to evaluate input (len=%d): %s", len(str(data)) if data else 0, exc)
        raise SafeEvalError(f"Evaluation error: {exc}") from exc
