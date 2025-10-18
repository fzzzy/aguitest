"""
Test the Bedrock agent with a simple query
"""

import asyncio
import os
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider


async def main():
    """Test the agent with a simple query"""
    print("Testing Bedrock Console Agent...")
    print("=" * 50)

    # Set region if not already set
    if 'AWS_DEFAULT_REGION' not in os.environ:
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'

    # Try Claude 3.5 Sonnet (more widely available)
    agent = Agent(
        'bedrock:anthropic.claude-3-5-sonnet-20240620-v1:0',
        system_prompt='You are a helpful assistant. Be concise and friendly.',
    )

    # Test query
    test_query = "What is 2 + 2? Please answer in one sentence."
    print(f"\nQuery: {test_query}")

    try:
        result = await agent.run(test_query)
        print(f"Response: {result.output}\n")
        print("✓ Agent test successful!")
    except Exception as e:
        print(f"✗ Error: {e}")


if __name__ == '__main__':
    asyncio.run(main())
