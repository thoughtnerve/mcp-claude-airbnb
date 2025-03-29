from typing import List
import os
import asyncio
import json
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load environment variables from .env file
load_dotenv()

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
model = "claude-3-7-sonnet-20250219"  # Using the latest available model

# System prompt focused on getting Claude to make tool calls
SYSTEM_PROMPT = """You are a travel assistant AI specializing in finding accommodations.
You MUST use the provided tools for any booking-related questions.
For ANY travel query, use the airbnb_search tool FIRST with the location, dates, and number of guests from the query.
Then you MUST use the airbnb_listing_details tool with the ID of at least one listing from the search results to get detailed information.
Begin by searching for accommodations, then select the best-rated or most relevant listing and get its details.
Present a helpful summary of options including prices, ratings, and amenities, with direct booking links."""

# System prompt for summarizing results
SUMMARY_PROMPT = """You are a helpful travel assistant specializing in booking accommodations.
Your tone is friendly, conversational, and concise. 
You provide recommendations based on the data you're given without mentioning APIs, tools, or data sources.
When summarizing accommodation options, focus on the top 2-3 choices with their unique features and direct booking links."""

# Create server parameters for stdio connection
server_params = StdioServerParameters(
    command="npx",  # Executable
    args=[
        "-y",
        "@openbnb/mcp-server-airbnb",
        "--ignore-robots-txt",
    ],  # Optional command line arguments
    env=None,  # Optional environment variables
)

async def agent_loop(prompt: str, client: AsyncAnthropic, session: ClientSession):
    # Initialize the connection
    await session.initialize()
    
    # --- 1. Get Tools from Session and convert to Claude Tool objects ---
    mcp_tools = await session.list_tools()
    claude_tools = [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.inputSchema,
        }
        for tool in mcp_tools.tools
    ]
    
    # Print available tools for debugging
    print(f"Available tools: {[tool['name'] for tool in claude_tools]}")
    
    # --- 2. Let Claude make the tool calls ---
    print(f"Sending prompt to Claude: {prompt}")
    
    messages = [
        {"role": "user", "content": prompt}
    ]
    
    response = await client.messages.create(
        model=model,
        system=SYSTEM_PROMPT,
        messages=messages,
        temperature=0.2,  # Lower temperature for more deterministic tool use
        max_tokens=4096,
        tools=claude_tools,
    )
    
    return await process_claude_response(response, session, prompt, claude_tools)

async def process_claude_response(response, session, original_prompt, claude_tools):
    # Process the response from Claude
    print("\nReceived response from Claude:")
    
    # Initialize conversation history
    conversation = [
        {"role": "user", "content": original_prompt}
    ]
    
    # Handle tool calls if present
    while response.content and any(block.type == 'tool_use' for block in response.content):
        # Find tool calls in the response
        for i, block in enumerate(response.content):
            if block.type == 'tool_use':
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id
                
                print(f"Claude is calling tool: {tool_name}")
                print(f"Tool input: {json.dumps(tool_input, indent=2)}")
                
                # Make the actual tool call
                tool_result = await session.call_tool(tool_name, tool_input)
                
                if tool_result.isError:
                    tool_output = {"error": tool_result.content[0].text}
                    print(f"Tool call error: {tool_result.content[0].text}")
                else:
                    print(f"Tool call successful: {tool_name}")
                    # Parse JSON response for debugging
                    try:
                        parsed_result = json.loads(tool_result.content[0].text)
                        if tool_name == "airbnb_search" and "searchResults" in parsed_result:
                            print(f"Found {len(parsed_result['searchResults'])} search results")
                        # Print just the first 100 chars of the result for brevity
                        print(f"Tool response snippet: {tool_result.content[0].text[:100]}...")
                    except Exception as e:
                        print(f"Could not parse tool result as JSON: {e}")
                    
                    tool_output = {"result": tool_result.content[0].text}
                
                # Add the tool call and result to conversation
                conversation.append({
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": tool_name, "id": tool_id, "input": tool_input}]
                })
                
                conversation.append({
                    "role": "user", 
                    "content": [{"type": "tool_result", "tool_use_id": tool_id, "content": json.dumps(tool_output)}]
                })
                
                break  # Process one tool call at a time
        
        # Get Claude's next response with the tool results
        print("Getting Claude's next response with tool results...")
        response = await client.messages.create(
            model=model,
            system=SYSTEM_PROMPT,
            messages=conversation,
            temperature=0.2,
            max_tokens=4096,
            tools=claude_tools,
        )
    
    # Final response (after all tool calls are done)
    final_text = ""
    for block in response.content:
        if block.type == 'text':
            final_text += block.text
    
    print("Claude has completed all tool calls and provided a final response.")
    return {"content": final_text, "conversation": conversation}

async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
        ) as session:
            # Prompt for booking
            prompt = "I want to book an apartment in Paris for 2 nights from April 15 to April 17, 2025 for 2 adults."
            print(f"Running agent loop with prompt: {prompt}")
            # Run agent loop
            res = await agent_loop(prompt, client, session)
            return res

# Fix the await run() error by using asyncio.run
if __name__ == "__main__":
    result = asyncio.run(run())
    print("\nFinal result:")
    
    # Print the final result
    print(result["content"])