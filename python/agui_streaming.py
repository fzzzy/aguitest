"""Streaming module for agent event handling"""

import json
import uuid
import logging
from typing import Any
from pydantic_ai import Agent
from pydantic_ai.ag_ui import run_ag_ui, SSE_CONTENT_TYPE
from ag_ui.core import RunAgentInput

from agui_database import save_message

logger = logging.getLogger(__name__)


async def stream_agent_events(
    agent: Agent, run_input: RunAgentInput, user_message_id: str
):
    """Stream agent events and collect response items for persistence"""
    event_stream = run_ag_ui(agent, run_input, accept=SSE_CONTENT_TYPE)
    current_message_content = ""
    current_message_id: str | None = None
    current_tool_args = ""
    current_tool_call_id: str | None = None
    current_tool_name: str | None = None
    response_items: list[
        dict[str, Any]
    ] = []  # Collect all message objects (messages, tool calls, tool results)
    assistant_message_id: str | None = None  # Track the saved assistant message ID

    async for event in event_stream:
        # Parse the event to log and collect response items
        try:
            # SSE format: "data: {json}\n\n"
            if event.startswith("data: "):
                event_data = event[6:].strip()
                parsed = json.loads(event_data) if event_data else {}

                event_type = parsed.get("type")

                # Yield the event first (before modification)
                if event_type != "RUN_FINISHED":
                    yield event

                if event_type == "TEXT_MESSAGE_START":
                    # Start collecting a new message
                    current_message_id = parsed.get("messageId")
                    current_message_content = ""
                elif event_type == "TEXT_MESSAGE_CONTENT":
                    # Accumulate message content
                    delta = parsed.get("delta", "")
                    current_message_content += delta
                elif event_type == "TEXT_MESSAGE_END":
                    # Log and save the complete message
                    if current_message_content:
                        logger.info(
                            f"Complete message [{current_message_id}]: {current_message_content}"
                        )
                        response_items.append(
                            {
                                "id": current_message_id,
                                "role": "assistant",
                                "content": current_message_content,
                            }
                        )
                    current_message_content = ""
                    current_message_id = None
                elif event_type == "TOOL_CALL_START":
                    # Start collecting tool call
                    current_tool_call_id = parsed.get("toolCallId")
                    current_tool_name = parsed.get("toolCallName")
                    current_tool_args = ""
                    logger.info(f"Event: {event_type} - {parsed}")
                elif event_type == "TOOL_CALL_ARGS":
                    # Accumulate tool call arguments
                    delta = parsed.get("delta", "")
                    current_tool_args += delta
                elif event_type == "TOOL_CALL_END":
                    # Save the complete tool call
                    if current_tool_call_id:
                        tool_call_msg: dict[str, Any] = {
                            "id": str(uuid.uuid4()),
                            "role": "assistant",
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": current_tool_call_id,
                                    "type": "function",
                                    "function": {
                                        "name": current_tool_name,
                                        "arguments": current_tool_args,
                                    },
                                }
                            ],
                        }
                        response_items.append(tool_call_msg)
                        logger.info(
                            f"Tool call: {current_tool_name}({current_tool_args})"
                        )
                    current_tool_call_id = None
                    current_tool_name = None
                    current_tool_args = ""
                elif event_type == "TOOL_CALL_RESULT":
                    # Save the tool call result
                    tool_call_id = parsed.get("toolCallId")
                    content = parsed.get("content", "")
                    if isinstance(content, list):
                        # Extract text from content array
                        content = "\n".join(
                            [
                                item.get("text", "")
                                for item in content
                                if isinstance(item, dict)
                            ]
                        )

                    tool_result_msg = {
                        "id": str(uuid.uuid4()),
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": str(content),
                    }
                    response_items.append(tool_result_msg)
                    logger.info(f"Event: {event_type} - Result: {str(content)[:100]}")
                elif event_type in ["RUN_STARTED", "RUN_FINISHED"]:
                    # Log lifecycle events
                    logger.info(f"Event: {event_type} - {parsed}")

                    # When run finishes, save all response items
                    if event_type == "RUN_FINISHED":
                        # Use the last message content as summary
                        summary = "Agent completed"
                        for item in reversed(response_items):
                            if item.get("role") == "assistant" and item.get("content"):
                                content_val = item["content"]
                                if isinstance(content_val, str):
                                    summary = content_val
                                break

                        # Save assistant response linked to user message and return the new message ID
                        assistant_message_id = save_message(
                            content=summary,
                            events=response_items,
                            previous_id=user_message_id,
                        )
                        logger.info(
                            f"Saved assistant response with {len(response_items)} items, ID: {assistant_message_id}"
                        )

                        # Add assistant message ID to the RUN_FINISHED event
                        parsed["assistantMessageId"] = assistant_message_id
                        modified_event = f"data: {json.dumps(parsed)}\n\n"
                        yield modified_event
        except Exception as e:
            # If parsing fails, just continue streaming
            logger.error(f"Error parsing event: {e}")
            pass
