"""Calculator Tool."""


class Calculator:
    """Simple calculator for basic arithmetic."""

    async def calculate(self, expression: str) -> dict:
        try:
            result = eval(expression, {"__builtins__": {}})
            return {"expression": expression, "result": result}
        except (SyntaxError, NameError, TypeError, ValueError, ZeroDivisionError, ArithmeticError) as e:
            return {"expression": expression, "error": str(e)}
