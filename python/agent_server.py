"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import base64
import os
import re
import time
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from starlette.responses import StreamingResponse
from pydantic_ai import Agent, DeferredToolResults
from pydantic_ai.ag_ui import run_ag_ui, StateDeps
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.messages import ToolCallPart
from pydantic_ai.models.bedrock import BedrockConverseModel, BedrockModelSettings
from pydantic_ai.providers.bedrock import BedrockProvider
from pydantic_ai import DeferredToolRequests
from ag_ui.core.types import RunAgentInput, TextInputContent, BinaryInputContent, UserMessage
import uuid
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

agent = Agent(
    "openai-responses:gpt-5.2",
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
    with open("../static/index.html", "r") as f:
        html = f.read()
    with open("../static/styles.css", "r") as f:
        css = f.read()
    html = html.replace(
        '<link rel="stylesheet" href="/static/styles.css">',
        f"<style>\n{css}</style>"
    )
    return HTMLResponse(html)


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
        attachments_info = {}

        if run_input.state:
            # Only create DeferredToolResults if there are actual approvals
            approvals = run_input.state.get("deferred_tool_approvals", {})
            if approvals:
                deferred_tool_results = DeferredToolResults(approvals=approvals)

            # Process attachments from state
            attachments = run_input.state.get("attachments", {})
            if attachments and run_input.messages:
                # Find the last user message index
                last_user_idx = -1
                for i in range(len(run_input.messages) - 1, -1, -1):
                    if run_input.messages[i].role == "user":
                        last_user_idx = i
                        break

                if last_user_idx >= 0:
                    msg = run_input.messages[last_user_idx]
                    # Convert message content to list if it's a string (for binary attachments)
                    content_list = None
                    text_attachment_messages = []

                    for filename, data_url in attachments.items():
                        parsed = parse_data_url(data_url)
                        if parsed:
                            media_type, base64_data = parsed
                            attachments_info[filename] = data_url

                            if media_type.startswith("text/"):
                                # Decode text content and create a separate user message
                                text_content = base64.b64decode(base64_data).decode("utf-8")
                                text_attachment_messages.append(
                                    UserMessage(
                                        id=str(uuid.uuid4()),
                                        role="user",
                                        content=f"<file-attachment name=\"{filename}\">{text_content}</file-attachment>"
                                    )
                                )
                            else:
                                # Use BinaryInputContent for non-text (images, etc.)
                                if content_list is None:
                                    if isinstance(msg.content, str):
                                        content_list = [TextInputContent(text=msg.content)]
                                    else:
                                        content_list = list(msg.content)
                                content_list.append(
                                    BinaryInputContent(
                                        mimeType=media_type,
                                        data=base64_data,
                                        filename=filename
                                    )
                                )

                    # Update message content if we added binary attachments
                    if content_list is not None:
                        msg.content = content_list

                    # Insert text attachment messages after the user message
                    for idx, text_msg in enumerate(text_attachment_messages):
                        run_input.messages.insert(last_user_idx + 1 + idx, text_msg)

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
                    deferred_event = CustomEvent(
                        name="deferred_tool_requests",
                        value=deferred_tool_requests,
                        timestamp=int(time.time() * 1000)
                    )
                    yield f"data: {json.dumps(deferred_event.model_dump())}\n\n"

            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")




from opentelemetry import trace
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExportResult

from pydantic_ai import InstrumentationSettings


import logging


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
