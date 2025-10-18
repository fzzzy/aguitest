"""
Example Pydantic AI Agent with AG-UI Integration
"""

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.ag_ui import StateDeps
from ag_ui.core import CustomEvent, EventType
from pydantic_ai import ToolReturn


class ConversationState(BaseModel):
    """State that's shared with the frontend"""
    message_count: int = 0
    topic: str = ""


# Create an agent with AG-UI state management
agent = Agent(
    'openai:gpt-4',
    instructions='You are a helpful assistant. Be concise and friendly.',
    deps_type=StateDeps[ConversationState]
)


@agent.tool_plain
async def count_messages() -> ToolReturn:
    """Count messages and emit a custom event"""
    return ToolReturn(
        return_value='Message counted',
        metadata=[
            CustomEvent(
                type=EventType.CUSTOM,
                name='message_count',
                value='1'
            )
        ]
    )


@agent.tool_plain
async def set_topic(topic: str) -> ToolReturn:
    """Set the conversation topic"""
    return ToolReturn(
        return_value=f'Topic set to: {topic}',
        metadata=[
            CustomEvent(
                type=EventType.CUSTOM,
                name='topic_changed',
                value=topic
            )
        ]
    )


if __name__ == '__main__':
    print("Agent defined successfully!")
    print(f"Available tools: {[tool.name for tool in agent._function_tools.values()]}")
