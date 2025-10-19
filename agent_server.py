"""AG-UI Agent Server using mumulib and Pydantic AI"""

import os
import logging
import uuid
import json
from pathlib import Path
from typing import Optional, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.ag_ui import SSE_CONTENT_TYPE
from ag_ui.core import RunAgentInput
from simpleeval import simple_eval

from database import init_db, save_message, get_message, reconstruct_history
from streaming import stream_agent_events

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if "AWS_DEFAULT_REGION" not in os.environ:
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"

# Initialize database on startup
init_db()


# Pydantic models for API
class MessageRequest(BaseModel):
    content: str
    previous_id: Optional[str] = None


class MessageResponse(BaseModel):
    id: str


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


# Create FastAPI app
app = FastAPI()


@app.get("/")
async def root():
    """Root endpoint returning hello world"""
    return {"message": "hello world"}


@app.get("/chat.html", response_class=HTMLResponse)
async def get_chat_html():
    """Serve the chat.html file"""
    chat_html_path = Path(__file__).parent / "chat.html"
    return HTMLResponse(content=chat_html_path.read_text(), status_code=200)


@app.post("/message", response_model=MessageResponse)
async def post_message(request: MessageRequest):
    """Persist a user message and return its UUID"""
    # Create a user message event in the correct format for Pydantic AI
    user_event = {
        "id": str(uuid.uuid4()),
        "role": "user",
        "content": request.content,
    }

    message_id = save_message(
        content=request.content,
        events=[user_event],  # User input as first event
        previous_id=request.previous_id,
    )
    return MessageResponse(id=message_id)


@app.get("/agent")
async def agent_endpoint(message_id: str):
    """SSE endpoint for agent communication - reconstructs history from message_id"""
    # Get the message that triggered this request
    message = get_message(message_id)
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    # Reconstruct the full chat history
    history = reconstruct_history(message_id)

    # Extract all events from history to build messages
    messages_dicts: list[dict[str, Any]] = []
    for msg in history:
        # Parse events JSON from database
        events = json.loads(msg["events"]) if msg["events"] else []
        # Add all events from this message to the messages list
        messages_dicts.extend(events)

    # Log the reconstructed history being sent to the agent
    logger.info(f"\n\n\n\nSending {len(messages_dicts)} messages to agent:")
    logger.info(json.dumps(messages_dicts, indent=2))

    # Create a unique thread_id based on the conversation chain
    # Use the first message's ID as the thread identifier
    thread_id = history[0]["id"] if history else message_id

    run_input = RunAgentInput.model_validate(
        {
            "thread_id": thread_id,
            "run_id": f"run-{message_id}",
            "state": {},
            "messages": messages_dicts,
            "tools": [],
            "context": [],
            "forwarded_props": {},
        }
    )

    return StreamingResponse(
        stream_agent_events(agent, run_input, message_id), media_type=SSE_CONTENT_TYPE
    )
