"""AG-UI Agent Server using standard AG-UI protocol with agent.to_ag_ui()"""

import asyncio
import base64
import json
import logging
import re
import signal
import time
import typing
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import FrameType
from uuid import uuid4

from ag_ui.core import CustomEvent
from ag_ui.core.types import RunAgentInput, TextInputContent, BinaryInputContent
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from pydantic_ai import Agent, DeferredToolRequests, DeferredToolResults
from pydantic_ai.ag_ui import run_ag_ui, StateDeps
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, ToolCallPart, UserPromptPart
from pydantic_ai.models import ModelRequestParameters, ModelSettings
from pydantic_ai.models.function import DeltaToolCall, FunctionModel, AgentInfo
from pydantic_ai.toolsets import FunctionToolset
from pydantic_ai.usage import Usage
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from simpleeval import simple_eval
from starlette.responses import StreamingResponse

logger = logging.getLogger("agent_server")
logger.setLevel(logging.DEBUG)
_handler = logging.StreamHandler()
_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(_handler)


DEBUG = False


def tool_schema_to_a2ui(tool_name: str, tool: typing.Any) -> list[dict[str, typing.Any]]:
    """Convert a tool's JSON schema into A2UI messages for a form UI."""
    schema = tool.function_schema.json_schema
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    children_ids: list[str] = []
    components: list[dict[str, typing.Any]] = []

    for prop_name, prop_schema in properties.items():
        field_id = f"{tool_name}-{prop_name}"
        prop_type = prop_schema.get("type", "string")

        if prop_type == "boolean":
            component = {
                "id": field_id,
                "component": {
                    "Checkbox": {
                        "label": {"literalString": prop_name},
                        "dataModelKey": prop_name,
                    }
                },
            }
        elif prop_type == "number" or prop_type == "integer":
            component = {
                "id": field_id,
                "component": {
                    "TextField": {
                        "label": {"literalString": prop_name},
                        "inputType": "number",
                        "dataModelKey": prop_name,
                    }
                },
            }
        else:
            component = {
                "id": field_id,
                "component": {
                    "TextField": {
                        "label": {"literalString": prop_name},
                        "dataModelKey": prop_name,
                    }
                },
            }

        children_ids.append(field_id)
        components.append(component)

    # Add submit button
    submit_id = f"{tool_name}-submit"
    children_ids.append(submit_id)
    components.append({
        "id": submit_id,
        "component": {
            "Button": {
                "label": {"literalString": f"Run {tool_name}"},
                "action": {"name": f"invoke_{tool_name}"},
            }
        },
    })

    # Wrap in a Column
    root_id = f"{tool_name}-form"
    components.insert(0, {
        "id": root_id,
        "component": {
            "Column": {
                "children": children_ids,
            }
        },
    })

    surface_update = {
        "surfaceUpdate": {
            "surfaceId": tool_name,
            "components": components,
        }
    }

    begin_rendering = {
        "beginRendering": {
            "surfaceId": tool_name,
            "root": root_id,
        }
    }

    return [surface_update, begin_rendering]


AGENT_INSTRUCTIONS = "You are a helpful assistant. Be concise and friendly."


def parse_data_url(data_url: str) -> tuple[str, str] | None:
    """Parse a data URL and return (media_type, base64_data) or None if invalid."""
    match = re.match(r"data:([^;]+);base64,(.+)", data_url)
    if not match:
        return None
    media_type = match.group(1)
    base64_data = match.group(2)
    return media_type, base64_data


class Dependencies(BaseModel):
    pass


@dataclass
class Session:
    """Holds state for each connected client session."""
    agent: Agent[typing.Any]
    queue: asyncio.Queue[typing.Any]
    current_task: asyncio.Task[typing.Any] | None = None


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


# --- Meme generator tool ---

IMPACT_FONT = "/System/Library/Fonts/Supplemental/Impact.ttf"
MEME_DIR = Path(__file__).parent / "generated_memes"
MEME_DIR.mkdir(exist_ok=True)

# Store generated meme filenames for serving
generated_memes: dict[str, Path] = {}


def _draw_meme_text(draw: ImageDraw.ImageDraw, text: str, y: int, width: int, font: ImageFont.FreeTypeFont) -> None:
    """Draw Impact-style text (white with black outline) centered at y."""
    text = text.upper()
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    x = (width - text_width) // 2
    # Black outline
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            draw.text((x + dx, y + dy), text, font=font, fill="black")
    # White text
    draw.text((x, y), text, font=font, fill="white")


DOGE_TEMPLATE = Path(__file__).parent / "meme_templates" / "doge.jpg"


def make_meme(top_text: str, bottom_text: str) -> str:
    """Generate a doge meme image with Impact font.

    Creates a classic doge meme with white-on-black outlined text in Impact font.

    Args:
        top_text: Text for the top of the meme (will be uppercased)
        bottom_text: Text for the bottom of the meme (will be uppercased)

    Returns a URL to the generated image.
    """
    img = Image.open(DOGE_TEMPLATE).copy()
    width, height = img.size
    draw = ImageDraw.Draw(img)

    font = ImageFont.truetype(IMPACT_FONT, width // 12)

    _draw_meme_text(draw, top_text, 20, width, font)
    _draw_meme_text(draw, bottom_text, height - 80, width, font)

    meme_id = str(uuid4())[:8]
    filename = f"meme_{meme_id}.png"
    filepath = MEME_DIR / filename
    img.save(filepath)
    generated_memes[meme_id] = filepath

    return json.dumps({"url": f"/memes/{meme_id}", "meme_id": meme_id})


toolset.add_function(
    make_meme,
    requires_approval=False,
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

def create_agent() -> Agent[StateDeps[Dependencies]]:
    """Create a new agent instance for a session."""
    model = "google-gla:gemini-3.1-pro-preview"
    logger.info(f"Creating agent with model: {model}")
    return Agent(
        model,
        system_prompt=AGENT_INSTRUCTIONS,
        toolsets=[toolset],  # type: ignore[list-item]
        output_type=[DeferredToolRequests, str],
        deps_type=StateDeps[Dependencies],
    )


def make_injector_stream_fn(
    tool_name: str,
    tool_args: str,
    real_model: typing.Any,
) -> typing.Callable[..., typing.AsyncIterator[str | dict[int, DeltaToolCall]]]:
    """Create a stream function that injects a predetermined tool call on the first turn,
    then delegates to the real model for the summary."""
    call_count = 0

    async def injector_stream_fn(
        messages: list[ModelMessage], info: AgentInfo
    ) -> typing.AsyncIterator[str | dict[int, DeltaToolCall]]:
        nonlocal call_count
        call_count += 1
        # Inject a user turn so Gemini sees: user -> tool_call (not model -> tool_call)
        user_msg = ModelRequest(parts=[UserPromptPart(
            content=f"The user manually triggered the {tool_name} tool with args: {tool_args}"
        )])
        insert_idx = 1 if len(messages) > 0 else 0
        messages.insert(insert_idx, user_msg)

        if call_count == 1:
            yield {0: DeltaToolCall(
                name=tool_name,
                json_args=tool_args,
                tool_call_id=str(uuid4()),
            )}
        else:
            response = await real_model.request(
                messages, info.model_settings, info.model_request_parameters
            )
            for part in response.parts:
                if hasattr(part, 'content'):
                    yield part.content

    return injector_stream_fn


SignalHandler = Callable[[int, FrameType | None], object] | int | None

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


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Install signal handlers to gracefully close SSE before uvicorn shuts down
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        prev: SignalHandler = signal.getsignal(sig)

        def make_handler(
            s: signal.Signals, previous: SignalHandler
        ) -> Callable[[], None]:
            def handler() -> None:
                for session in sessions.values():
                    session.queue.put_nowait({"die": True})
                if callable(previous):
                    previous(s, None)

            return handler

        loop.add_signal_handler(sig, make_handler(sig, prev))

    # Start ping task
    ping_task = asyncio.create_task(ping_all_sessions())
    yield
    ping_task.cancel()


app = FastAPI(lifespan=lifespan)


@app.get("/memes/{meme_id}")
async def serve_meme(meme_id: str):
    filepath = generated_memes.get(meme_id)
    if not filepath or not filepath.exists():
        raise HTTPException(status_code=404, detail="Meme not found")
    from starlette.responses import FileResponse
    return FileResponse(filepath, media_type="image/png")


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
        mime_type=media_type,
        data=base64_data,
        filename=filename
    )


def process_attachments(run_input: RunAgentInput) -> dict[str, str]:
    attachments = run_input.state.get("attachments", {})
    attachments_info: dict[str, str] = {}
    if not (attachments and run_input.messages):
        return attachments_info
    # Find the last user message index
    last_user_idx = -1
    for i in range(len(run_input.messages) - 1, -1, -1):
        if run_input.messages[i].role == "user":
            last_user_idx = i
            break

    if last_user_idx < 0:
        return attachments_info

    msg = run_input.messages[last_user_idx]
    content_list: list[TextInputContent | BinaryInputContent] | None = None

    for filename, data_url in attachments.items():
        parsed = parse_data_url(data_url)
        if not parsed:
            continue
        media_type, base64_data = parsed
        attachments_info[filename] = data_url

        if content_list is None:
            if isinstance(msg.content, str):
                content_list = [TextInputContent(text=msg.content)]
            elif isinstance(msg.content, list):
                content_list = list(msg.content)  # type: ignore[arg-type]
            else:
                content_list = []

        if media_type.startswith("text/"):
            content_list.append(process_text_attachment(base64_data, filename))
        else:
            content_list.append(
                process_binary_attachment(media_type, base64_data, filename)
            )

    if content_list:
        msg.content = content_list  # type: ignore[assignment]

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
    available_tools = [
        {
            "name": name,
            "description": tool.description or "",
            "a2ui": tool_schema_to_a2ui(name, tool),
        }
        for name, tool in toolset.tools.items()
    ]

    async def event_stream():
        logger.info(f"[{token[:8]}] /events client connected")
        try:
            # First event: JSON with agent URL and available tools
            first_event = {"agent": agent_url, "available_tools": available_tools}
            print(f"[DEBUG] Sending first_event: {first_event}")
            yield f"data: {json.dumps(first_event)}\n\n"

            # Loop forever reading from queue
            while True:
                event = await session.queue.get()
                if isinstance(event, dict) and event.get("die"):
                    yield "event: die\ndata: shutdown\n\n"
                    return
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

    # Filter tools based on disabled_tools in state
    disabled_tools = set(run_input.state.get("disabled_tools", [])) if run_input.state else set()
    if disabled_tools:
        filtered = toolset.filtered(
            lambda _ctx, tool_def: tool_def.name not in disabled_tools
        )
        agent = Agent(
            agent.model,
            system_prompt=AGENT_INSTRUCTIONS,
            toolsets=[filtered],  # type: ignore[list-item]
            output_type=[DeferredToolRequests, str],
            deps_type=StateDeps[Dependencies],
        )

    state["ag_ui_events"] = run_ag_ui(  # type: ignore[misc]
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

    deferred_tool_requests: dict[str, typing.Any] = {}
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

    # Check for manual tool call — use FunctionModel to inject a predetermined tool call
    manual_call = run_input.state.get("manual_tool_call") if run_input.state else None
    if manual_call:
        stream_fn = make_injector_stream_fn(
            tool_name=manual_call["name"],
            tool_args=json.dumps(manual_call["args"]),
            real_model=session.agent.model,
        )
        injector_model = FunctionModel(stream_function=stream_fn, model_name="manual-tool-injector")
        auto_approved_toolset = FunctionToolset()
        for name, tool in toolset.tools.items():
            auto_approved_toolset.add_function(
                tool.function,
                name=name,
                description=tool.description,
                requires_approval=False,
            )
        agent = Agent(
            injector_model,
            system_prompt=AGENT_INSTRUCTIONS + "\nThe user manually triggered a tool call. Briefly describe the result.",
            toolsets=[auto_approved_toolset],  # type: ignore[list-item]
            output_type=str,
            deps_type=StateDeps[Dependencies],
        )

    if not manual_call:
        agent = session.agent

    state: dict[str, typing.Any] = {}

    async def event_stream():
        try:
            async for chunk in stream_agent_response(
                token, run_input, agent, deps,
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


def instrument(service_name: str = "default") -> None:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExportResult,
    )

    from pydantic_ai import InstrumentationSettings

    class CustomConsoleSpanExporter(ConsoleSpanExporter):
        def export(self, spans: typing.Sequence[ReadableSpan]) -> SpanExportResult:
            for span in spans:
                formatted_span = self.formatter(span)
                span_dict = json.loads(formatted_span)
                name = span_dict.get("name", "")
                print(name, span_dict)
            return SpanExportResult.SUCCESS

    resource = Resource.create(attributes={SERVICE_NAME: service_name})

    provider = TracerProvider(resource=resource)
    trace.set_tracer_provider(provider)

    print("Enabling local LLM prompt logging to console")
    provider.add_span_processor(BatchSpanProcessor(CustomConsoleSpanExporter()))
    provider._disabled = False  # type: ignore[attr-defined]

    Agent.instrument_all(InstrumentationSettings(version=3))


if DEBUG:
    instrument()
