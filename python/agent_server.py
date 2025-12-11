"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import time
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.responses import StreamingResponse
from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.ag_ui import run_ag_ui, StateDeps
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.messages import ToolCallPart
from pydantic_ai import DeferredToolRequests
from ag_ui.core.types import RunAgentInput
from ag_ui.core import CustomEvent
from simpleeval import simple_eval
import json
from dataclasses import dataclass


AGENT_INSTRUCTIONS = "You are a helpful assistant. Be concise and friendly."


@dataclass
class Dependencies:
    pass


toolset = FunctionToolset()


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


toolset.add_function(
    evaluate_expression,
    requires_approval=True,
)


agent = Agent(
    "openai-responses:gpt-5.1",
    system_prompt=AGENT_INSTRUCTIONS,
    toolsets=[toolset],
    output_type=[DeferredToolRequests, str],
    deps_type=StateDeps[Dependencies],
)


app = FastAPI()


app.mount("/static", StaticFiles(directory="../static"), name="static")
app.mount("/dist", StaticFiles(directory="../dist"), name="dist")


@app.get("/")
async def root():
    return FileResponse("../static/index.html")


@app.post("/agent")
async def agent_run(run_input: RunAgentInput):
    deferred_tool_requests = {}
    deps = StateDeps(Dependencies())

    def on_complete_callback(result):
        """Callback to capture deferred tool requests when the run completes."""
        nonlocal deferred_tool_requests

        if isinstance(result.output, DeferredToolRequests):
            # Extract tool call information from the last model response
            response = result.response
            for part in response.parts:
                if isinstance(part, ToolCallPart):
                    deferred_tool_requests[part.tool_call_id] = {
                        "tool_name": part.tool_name,
                        "args": part.args
                    }

    async def event_stream():
        deferred_tool_results = None
        if run_input.state:
            deferred_tool_results = DeferredToolResults(
                approvals=run_input.state.get("deferred_tool_approvals", {})
            )

        ag_ui_events = run_ag_ui(
            agent,
            run_input,
            deferred_tool_results=deferred_tool_results,
            on_complete=on_complete_callback,
            deps=deps
        )

        first_event_seen = False
        async for chunk in ag_ui_events:
            # Yield the first event (RUN_STARTED)
            if not first_event_seen:
                yield chunk
                first_event_seen = True

                # After first event, yield instructions event (only on first turn)
                if len(run_input.messages) == 1:
                    instructions_event = CustomEvent(
                        name="instructions",
                        value=AGENT_INSTRUCTIONS,
                        timestamp=int(time.time() * 1000)
                    )
                    yield f"data: {json.dumps(instructions_event.model_dump())}\n\n"
                continue
            if chunk.startswith("data: "):
                json_str = chunk[6:].strip()
                event_data = json.loads(json_str)
                if event_data.get("type") == "RUN_FINISHED":
                    deferred_event = CustomEvent(
                        name="deferred_tool_requests",
                        value=deferred_tool_requests,
                        timestamp=int(time.time() * 1000)
                    )
                    yield f"data: {json.dumps(deferred_event.model_dump())}\n\n"

            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")
