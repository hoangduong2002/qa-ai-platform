import ast
import operator
import re
from dataclasses import dataclass
from decimal import Decimal, DivisionByZero, InvalidOperation


@dataclass
class CalculatorToolResult:
    answer: str
    confidence: float
    tool_name: str = "calculator_tool"


ALLOWED_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
    ast.UAdd: operator.pos,
}


def answer_calculation_question(message: str) -> CalculatorToolResult | None:
    expression = _extract_expression(message)
    if not expression:
        return None

    try:
        value = _safe_eval(expression)
    except (ValueError, ZeroDivisionError, OverflowError, InvalidOperation, DivisionByZero):
        return None

    return CalculatorToolResult(
        answer=f"{_format_expression(expression)} = {_format_number(value)}",
        confidence=1.0,
    )


def _extract_expression(message: str) -> str:
    text = (message or "").strip().lower()
    text = text.replace("×", "*").replace("÷", "/").replace("^", "**")
    text = re.sub(r"(?<=\d)\s*x\s*(?=\d)", "*", text)
    text = re.sub(r"\bplus\b", "+", text)
    text = re.sub(r"\bminus\b", "-", text)
    text = re.sub(r"\b(times|multiplied by|multiply by)\b", "*", text)
    text = re.sub(r"\b(divided by|divide by)\b", "/", text)
    text = re.sub(r"\b(calculate|compute|solve|what is|what's|tính|bằng bao nhiêu)\b", "", text)
    text = text.replace("?", "").replace("=", "").strip()

    match = re.search(r"[\d\s().+\-*/%]+", text)
    expression = match.group(0).strip() if match else ""
    if not expression or not any(operator_char in expression for operator_char in "+-*/%"):
        return ""

    if not re.fullmatch(r"[\d\s().+\-*/%]+", expression):
        return ""

    return expression


def _safe_eval(expression: str) -> Decimal:
    node = ast.parse(expression, mode="eval")
    return _eval_node(node.body)


def _eval_node(node) -> Decimal:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return Decimal(str(node.value))

    if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_OPERATORS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 10:
            raise ValueError("Exponent too large.")
        return ALLOWED_OPERATORS[type(node.op)](left, right)

    if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_OPERATORS:
        return ALLOWED_OPERATORS[type(node.op)](_eval_node(node.operand))

    raise ValueError("Unsupported expression.")


def _format_number(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _format_expression(expression: str) -> str:
    compact = re.sub(r"\s+", "", expression)
    return re.sub(r"([+\-*/%])", r" \1 ", compact).strip()
