"""
Simple console agent using Pydantic AI with AWS Bedrock
"""

import asyncio
from pydantic_ai import Agent
from pydantic_ai.models.bedrock import BedrockConverseModel
from pydantic_ai.providers.bedrock import BedrockProvider


# Create Bedrock provider with region
provider = BedrockProvider(region_name='us-east-1')

# Create model with provider
model = BedrockConverseModel(
    'anthropic.claude-sonnet-4-5-20250929-v1:0',
    provider=provider
)

# Create agent with the model
agent = Agent(
    model,
    system_prompt='You are a helpful assistant. Be concise and friendly.',
)


async def main():
    """Run a simple console chat loop"""
    print("Console Agent (AWS Bedrock)")
    print("=" * 50)
    print("Type 'exit' or 'quit' to end the conversation\n")

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in ['exit', 'quit']:
            print("Goodbye!")
            break

        if not user_input:
            continue

        try:
            # Run the agent
            result = await agent.run(user_input)
            print(f"Agent: {result.data}\n")

        except Exception as e:
            print(f"Error: {e}\n")


if __name__ == '__main__':
    asyncio.run(main())
