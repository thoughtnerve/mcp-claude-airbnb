from typing import List
import os
import asyncio
import json
import time
from dotenv import load_dotenv
from anthropic import AsyncAnthropic
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Load environment variables from .env file
load_dotenv()

client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
model = "claude-3-7-sonnet-20250219"  # Using the latest available model

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
        system="",  # No system prompt
        messages=messages,
        temperature=0.2,  # Lower temperature for more deterministic tool use
        max_tokens=4096,
        tools=claude_tools,
    )
    
    # Process the response from Claude
    print("\nReceived response from Claude")
    
    # Initialize conversation history
    conversation = [
        {"role": "user", "content": prompt}
    ]
    
    # Track number of tool calls for rate limiting
    tool_call_count = 0
    max_tool_calls = 5  # Limit the number of tool calls
    
    # Handle tool calls if present
    while response.content and any(block.type == 'tool_use' for block in response.content) and tool_call_count < max_tool_calls:
        tool_call_count += 1
        
        # Apply rate limiting for API calls
        if tool_call_count > 1:
            wait_time = 3  # Wait 3 seconds between API calls
            print(f"Rate limiting: Waiting {wait_time} seconds before next API call...")
            await asyncio.sleep(wait_time)
        
        # Find tool calls in the response
        for i, block in enumerate(response.content):
            if block.type == 'tool_use':
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id
                
                print(f"Claude is calling tool ({tool_call_count}/{max_tool_calls}): {tool_name}")
                print(f"Tool input: {json.dumps(tool_input, indent=2)}")
                
                # Make the actual tool call
                try:
                    tool_result = await session.call_tool(tool_name, tool_input)
                    
                    if tool_result.isError:
                        tool_output = {"error": tool_result.content[0].text}
                        print(f"Tool call failed: {tool_result.content[0].text}")
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
                
                except Exception as e:
                    print(f"Error making tool call: {e}")
                    tool_output = {"error": f"Error making tool call: {str(e)}"}
                
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
        try:
            # Apply rate limiting for Claude API calls
            wait_time = 2  # Wait 2 seconds before each Claude API call
            print(f"Rate limiting: Waiting {wait_time} seconds before Claude API call...")
            await asyncio.sleep(wait_time)
            
            response = await client.messages.create(
                model=model,
                system="",  # No system prompt
                messages=conversation,
                temperature=0.2,
                max_tokens=4096,
                tools=claude_tools,
            )
        except Exception as e:
            print(f"Error getting Claude response: {e}")
            print("Waiting longer before retrying...")
            await asyncio.sleep(5)  # Wait longer on error
            try:
                response = await client.messages.create(
                    model=model,
                    system="",  # No system prompt
                    messages=conversation,
                    temperature=0.2,
                    max_tokens=4096,
                    tools=claude_tools,
                )
            except Exception as e2:
                print(f"Failed to get Claude response after retry: {e2}")
                break  # Exit the loop if we still can't get a response
    
    if tool_call_count >= max_tool_calls:
        print(f"Reached maximum tool call limit of {max_tool_calls}. Stopping further tool calls.")
    
    # Final response (after all tool calls are done)
    final_text = ""
    for block in response.content:
        if block.type == 'text':
            final_text += block.text
    
    print("Claude has completed all tool calls and provided a final response.")
    return final_text

async def run():
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(
            read,
            write,
        ) as session:
            # Single prompt
            prompt = "I want to book an apartment in New York City for 2 nights from April 15 to April 17, 2025 for 2 adults. Please tell me about a few options."
            print(f"Running agent loop with prompt: {prompt}")
            
            # Run agent loop with the prompt
            result = await agent_loop(prompt, client, session)
            
            # Print the final result
            print("\n========== CLAUDE'S FINAL RESPONSE ==========")
            print(result)
            print("=============================================")
            
            return result

# Run the script
if __name__ == "__main__":
    result = asyncio.run(run()) 