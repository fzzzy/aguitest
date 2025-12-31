"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import asyncio
import base64
import logging
import os
import re
import time
import typing
from uuid import uuid4

logger = logging.getLogger("agent_server")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(_handler)

from fastapi import FastAPI, Request, HTTPException
from starlette.responses import StreamingResponse
from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.ag_ui import run_ag_ui, StateDeps
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai import DeferredToolRequests
from ag_ui.core.types import RunAgentInput, TextInputContent, BinaryInputContent, UserMessage
from ag_ui.core import CustomEvent
from simpleeval import simple_eval
import json
from dataclasses import dataclass


DEBUG = False


AGENT_INSTRUCTIONS = "You are a helpful assistant. Be concise and friendly."


def parse_data_url(data_url: str) -> tuple[str, str] | None:
    """Parse a data URL and return (media_type, base64_data) or None if invalid."""
    match = re.match(r"data:([^;]+);base64,(.+)", data_url)
    if not match:
        return None
    media_type = match.group(1)
    base64_data = match.group(2)
    return media_type, base64_data


@dataclass
class Dependencies:
    pass


@dataclass
class Session:
    """Holds state for each connected client session."""
    agent: Agent
    queue: asyncio.Queue
    current_task: asyncio.Task | None = None


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


#model = BedrockConverseModel(
#    "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
#    provider=BedrockProvider(
#        api_key=os.getenv("AWS_BEARER_TOKEN_BEDROCK"),
#        region_name="us-east-1"
#    ),
#    settings=BedrockModelSettings(
#        bedrock_additional_model_requests_fields={
#            "anthropic_beta": ["context-1m-2025-08-07"]
#        }
#    )
#)
#
#agent = Agent(
#    model=model,
#    instructions=AGENT_INSTRUCTIONS,
#    toolsets=[toolset],
#    output_type=[DeferredToolRequests, str],
#    deps_type=StateDeps[Dependencies],
#)

def create_agent() -> Agent:
    """Create a new agent instance for a session."""
    return Agent(
        "openai-responses:gpt-5.2",
        system_prompt=AGENT_INSTRUCTIONS,
        toolsets=[toolset],
        output_type=[DeferredToolRequests, str],
        deps_type=StateDeps[Dependencies],
    )


app = FastAPI()

# Global dictionary: token (str) -> Session
sessions: dict[str, Session] = {}


async def ping_all_sessions():
    """Send a ping to all connected clients every minute."""
    while True:
        await asyncio.sleep(60)
        ping_event = {"ping": True}
        for session in sessions.values():
            try:
                session.queue.put_nowait(ping_event)
            except asyncio.QueueFull:
                pass


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ping_all_sessions())


def process_text_attachment(base64_data: str, filename: str) -> TextInputContent:
    text_content = base64.b64decode(base64_data).decode("utf-8")
    return TextInputContent(
        text=f"""<file-attachment name="{filename}">
{text_content}
</file-attachment>"""
    )


def process_binary_attachment(
    media_type: str, base64_data: str, filename: str
) -> BinaryInputContent:
    return BinaryInputContent(
        mimeType=media_type,
        data=base64_data,
        filename=filename
    )


def process_attachments(run_input: RunAgentInput) -> dict[str, str]:
    attachments = run_input.state.get("attachments", {})
    attachments_info = {}
    if not (attachments and run_input.messages):
        return
    # Find the last user message index
    last_user_idx = -1
    for i in range(len(run_input.messages) - 1, -1, -1):
        if run_input.messages[i].role == "user":
            last_user_idx = i
            break

    if not (last_user_idx >= 0):
        return [], []

    msg = run_input.messages[last_user_idx]
    content_list = None
    text_attachment_messages = []

    for filename, data_url in attachments.items():
        parsed = parse_data_url(data_url)
        if not parsed:
            continue
        media_type, base64_data = parsed
        attachments_info[filename] = data_url

        if content_list is None:
            if isinstance(msg.content, str):
                content_list = [TextInputContent(text=msg.content)]
            else:
                content_list = list(msg.content)

        if media_type.startswith("text/"):
            message = process_text_attachment(base64_data, filename)
            content_list.append(message)
        else:
            content_list.append(
                process_binary_attachment(media_type, base64_data, filename)
            )

    if content_list:
        msg.content = content_list

    return attachments_info


@app.post("/events")
async def events(request: Request):
    """SSE endpoint that creates a session with its own agent and streams events."""
    token = str(uuid4())
    session = Session(
        agent=create_agent(),
        queue=asyncio.Queue(),
    )
    sessions[token] = session

    agent_url = f"/agent?token={token}"

    async def event_stream():
        logger.info(f"[{token[:8]}] /events client connected")
        try:
            # First event: JSON with agent URL
            first_event = {"agent": agent_url}
            print(f"[DEBUG] Sending first_event: {first_event}")
            yield f"data: {json.dumps(first_event)}\n\n"

            # Loop forever reading from queue
            while True:
                event = await session.queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        except asyncio.CancelledError:
            logger.info(f"[{token[:8]}] /events client disconnected")
        finally:
            # Cancel any running task before cleanup
            if session.current_task and not session.current_task.done():
                session.current_task.cancel()
            sessions.pop(token, None)

    return StreamingResponse(event_stream(), media_type="text/event-stream")


async def stream_agent_response(
    token: str,
    run_input: RunAgentInput,
    agent: Agent,
    deps: StateDeps,
    on_complete_callback,
    deferred_tool_requests: dict,
    state: dict,
):
    """Stream agent response, yielding SSE chunks."""
    deferred_tool_results = None
    attachments_info: dict[str, str] = {}

    if run_input.state:
        # Only create DeferredToolResults if there are actual approvals
        approvals = run_input.state.get("deferred_tool_approvals", {})
        if approvals:
            deferred_tool_results = DeferredToolResults(approvals=approvals)

        attachments_info = process_attachments(run_input)

    state["ag_ui_events"] = run_ag_ui(
        agent,
        run_input,
        deferred_tool_results=deferred_tool_results,
        on_complete=on_complete_callback,
        deps=deps
    )

    first_event_seen = False
    async for chunk in state["ag_ui_events"]:
        # Yield the first event (RUN_STARTED)
        if not first_event_seen:
            logger.debug(f"[{token[:8]}] RUN_STARTED event received")
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

            # Emit attachments event if there are any
            if attachments_info:
                attachments_event = CustomEvent(
                    name="attachments",
                    value=attachments_info,
                    timestamp=int(time.time() * 1000)
                )
                yield f"data: {json.dumps(attachments_event.model_dump())}\n\n"

            continue
        if chunk.startswith("data: "):
            json_str = chunk[6:].strip()
            event_data = json.loads(json_str)
            if event_data.get("type") == "RUN_FINISHED":
                logger.debug(f"[{token[:8]}] RUN_FINISHED event received")
                deferred_event = CustomEvent(
                    name="deferred_tool_requests",
                    value=deferred_tool_requests,
                    timestamp=int(time.time() * 1000)
                )
                yield f"data: {json.dumps(deferred_event.model_dump())}\n\n"

        yield chunk


@app.post("/agent")
async def agent_run(request: Request, run_input: RunAgentInput, token: str):
    # Validate token and get session
    session = sessions.get(token)
    if not session:
        raise HTTPException(status_code=404, detail="Invalid or expired token")

    # Cancel any currently running task
    if session.current_task and not session.current_task.done():
        session.current_task.cancel()
        try:
            await session.current_task
        except asyncio.CancelledError:
            pass

    deferred_tool_requests = {}
    deps = StateDeps(Dependencies())

    def on_complete_callback(result):
        """Callback to capture deferred tool requests when the run completes."""
        if isinstance(result.output, DeferredToolRequests):
            # Extract tool call information from the last model response
            response = result.response
            for part in response.parts:
                if isinstance(part, ToolCallPart):
                    deferred_tool_requests[part.tool_call_id] = {
                        "tool_name": part.tool_name,
                        "args": part.args
                    }

    state = {}

    async def event_stream():
        try:
            async for chunk in stream_agent_response(
                token, run_input, session.agent, deps,
                on_complete_callback, deferred_tool_requests, state
            ):
                yield chunk
        except asyncio.CancelledError:
            logger.info(f"[{token[:8]}] /agent client disconnected")
            raise
        finally:
            # Close the underlying LLM stream to stop wasting API credits
            # NOTE: run_ag_ui has a bug where it doesn't handle GeneratorExit cleanly,
            # causing "RuntimeError: async generator ignored GeneratorExit" in a background task.
            # TODO: Report bug / patch pydantic_ai
            if state.get("ag_ui_events") is not None:
                await state["ag_ui_events"].aclose()

    return StreamingResponse(event_stream(), media_type="text/event-stream")




from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExportResult

from pydantic_ai import InstrumentationSettings


class CustomConsoleSpanExporter(ConsoleSpanExporter):
    def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
        for span in spans:
            formatted_span = self.formatter(span)
            span_dict = json.loads(formatted_span)
            name = span_dict.get("name", "")
            print(name, span_dict)
        return SpanExportResult.SUCCESS


def instrument(service_name="default"):
    resource = Resource.create(attributes={SERVICE_NAME: service_name})

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    print("Enabling local LLM prompt logging to console")
    provider.add_span_processor(BatchSpanProcessor(CustomConsoleSpanExporter()))
    # Override the OTEL_SDK_DISABLED but only if we are logging prompts locally
    provider._disabled = False

    Agent.instrument_all(InstrumentationSettings(version=3))

#    logging.basicConfig(level=logging.DEBUG)
#    logging.getLogger('boto3').setLevel(logging.DEBUG)
#    logging.getLogger('botocore').setLevel(logging.DEBUG)


if DEBUG:
    instrument()
