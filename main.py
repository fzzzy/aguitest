"""
AGUI Test Project - Learning the Agent User Interaction Protocol
"""

from ag_ui.core import (
    AssistantMessage,
    UserMessage,
    SystemMessage,
    Context,
    Tool,
    State,
    RunAgentInput,
    TextMessageStartEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
)


def main():
    print("Hello from AGUI Test Project!")
    print("=" * 50)
    print("AGUI Protocol imported successfully.\n")

    # Example 1: Create different message types
    user_msg = UserMessage(
        id="msg-1",
        role="user",
        content="Hello, agent! What can you do?"
    )
    assistant_msg = AssistantMessage(
        id="msg-2",
        role="assistant",
        content="I can help you with various tasks!"
    )
    system_msg = SystemMessage(
        id="msg-3",
        role="system",
        content="You are a helpful assistant."
    )

    print("Example Messages:")
    print(f"  User: {user_msg.content}")
    print(f"  Assistant: {assistant_msg.content}")
    print(f"  System: {system_msg.content}\n")

    # Example 2: Create a context for additional information
    context = Context(
        description="User location",
        value="San Francisco, CA"
    )
    print(f"Context created: {context.description} = {context.value}\n")

    # Example 3: Show event types
    print("AGUI uses streaming events like:")
    print("  - TextMessageStartEvent: Begin streaming a message")
    print("  - TextMessageContentEvent: Stream message content")
    print("  - TextMessageEndEvent: Complete message streaming")
    print("  - ToolCallStartEvent: Begin tool execution")
    print("  - RunStartedEvent: Agent run begins")
    print("  - RunFinishedEvent: Agent run completes")
    print("\nReady to build agent interactions!")


if __name__ == "__main__":
    main()
