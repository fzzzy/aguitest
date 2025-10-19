"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import os
import logging
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic_ai import Agent
from simpleeval import simple_eval

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if "AWS_DEFAULT_REGION" not in os.environ:
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

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
    """
    try:
        result = simple_eval(expression)
        return str(result)
    except Exception as e:
        return f"Error evaluating expression: {str(e)}"


# Create the AG-UI ASGI app from the agent
ag_ui_app = agent.to_ag_ui()

# Create FastAPI app for serving static files
app = FastAPI()

# Mount the AG-UI app at /agent
app.mount("/agent", ag_ui_app)

# Mount static files
app.mount("/static", StaticFiles(directory="../static"), name="static")
app.mount("/dist", StaticFiles(directory="../dist"), name="dist")


@app.get("/")
async def root():
    """Serve the main chat interface"""
    return FileResponse("../static/index.html")
