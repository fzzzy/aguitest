"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic_ai import Agent
from simpleeval import simple_eval


# Create the Pydantic AI agent
agent = Agent(
    "bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0",
    system_prompt="You are a helpful assistant. Be concise and friendly.",
)


@agent.tool_plain
def evaluate_expression(expression: str) -> str:
    """Evaluate mathematical and logical expressions using simpleeval.

    This tool uses simpleeval for safe expression evaluation without using Python's eval().

    Default operators: +, -, *, /, ** (power/exponentiation), % (modulo), ==, <, >, <=, >=, >>, <<, ^ (bitwise XOR), |, &, ~, in
    Default functions: randint(x) - random integer below x, rand() - random float 0-1, int(x), float(x), str(x)

    Examples:
    - "2 + 2" returns 4
    - "10 ** 2" returns 100
    - "15 % 4" returns 3
    - "int(3.7)" returns 3
    - "1 / 0" returns inf (infinity)
    """
    try:
        result = simple_eval(expression)
        return str(result)
    except ZeroDivisionError:
        return str(float("inf"))
    except Exception as e:
        return f"Error evaluating expression: {str(e)}"


app = FastAPI()


app.mount("/static", StaticFiles(directory="../static"), name="static")
app.mount("/dist", StaticFiles(directory="../dist"), name="dist")


@app.get("/")
async def root():
    return FileResponse("../static/index.html")


app.mount("/agent", agent.to_ag_ui())
