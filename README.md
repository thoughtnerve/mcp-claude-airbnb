# Claude Tools for Airbnb Search

This project demonstrates how to use Claude 3.7 Sonnet with tools to search for Airbnb listings programmatically. Claude naturally uses the provided tools to search for accommodations based on user queries without requiring extensive system prompts.

## Features

- Uses Claude 3.7 Sonnet with tool-calling capabilities
- Connects to the Airbnb MCP Server for listing searches
- Supports searching for accommodations with parameters like:
  - Location
  - Check-in/check-out dates
  - Number of guests
- Rate limiting to prevent API throttling
- Error handling for robust operation

## How It Works

1. The script initializes a connection to the Airbnb MCP Server
2. It provides two tools to Claude:
   - `airbnb_search`: Searches for listings based on location, dates, and guest count
   - `airbnb_listing_details`: Gets detailed information about a specific listing
3. Claude naturally selects and uses the appropriate tool based on the user's query
4. Results are formatted and presented in a user-friendly way

## Example

When prompted with "I want to book an apartment in Paris for 2 nights from April 15 to April 17, 2025 for 2 adults", Claude:

1. Uses the `airbnb_search` tool with the correct parameters
2. Processes the search results
3. Formats a response with apartment options, including:
   - Prices
   - Ratings
   - Amenities
   - Direct booking links

## Setup

1. Install dependencies:
   ```
   pip install anthropic python-dotenv
   npm install -g @openbnb/mcp-server-airbnb
   ```

2. Create a `.env` file with your Anthropic API key:
   ```
   ANTHROPIC_API_KEY=your_api_key_here
   ```

3. Run the script:
   ```
   python simple_mcp.py
   ```

## Requirements

- Python 3.9+
- Anthropic API key with Claude 3.7 Sonnet access
- Node.js (for the Airbnb MCP Server)

## License

MIT 