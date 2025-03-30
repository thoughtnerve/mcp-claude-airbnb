import os
import asyncio
import json
import time
import threading
import queue
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response
from nl_search import nl_search, extract_search_params
import logging
import re
from simple_airbnb import search_airbnb
from anthropic import AsyncAnthropic

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)

# Global variables to store search results and status
search_results = {}
search_status = {"status": "idle", "message": ""}
debug_logs = []  # Store debug logs for the trail of interactions
log_subscribers = []  # Store active SSE connections as a list instead of a set
log_lock = threading.Lock()  # Lock for thread-safe access to log_subscribers
status_subscribers = []  # Store active SSE connections for status updates as a list
status_lock = threading.Lock()  # Lock for thread-safe access to status_subscribers

# Initialize Anthropic client
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
claude_client = AsyncAnthropic(api_key=anthropic_api_key) if anthropic_api_key else None

# Custom log handler to capture logs
class DebugLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_data = {
            "timestamp": record.created,
            "level": record.levelname,
            "message": record.getMessage()
        }
        debug_logs.append(log_data)
        
        # IMPORTANT: Add explicit stdout logging for troubleshooting
        print(f"LOG HANDLER: Adding log entry: {log_data['level']} - {log_data['message'][:50]}...")
        
        # Check if this is a formatted listing, separator log or integration log
        is_formatted_listing = 'FORMATTED LISTING' in log_data['message'] or '================' in log_data['message']
        is_integration_log = 'INTEGRATION:' in log_data['message']
        
        if is_formatted_listing:
            print(f"LOG HANDLER: Found formatted listing log")
        
        if is_integration_log:
            print(f"LOG HANDLER: Found integration log")
        
        # Notify all SSE subscribers of the new log, respecting their filters
        with log_lock:
            active_subscribers = len(log_subscribers)
            print(f"LOG HANDLER: Broadcasting to {active_subscribers} subscribers")
            dead_subscribers = []
            broadcast_count = 0
            
            for subscriber in log_subscribers:
                try:
                    # Only send if it passes the subscriber's filter
                    filter_type = subscriber.get("filter", "all")
                    should_broadcast = False
                    
                    # Special case for formatted listings - always send to 'all' and 'mcp' filters
                    if is_formatted_listing and (filter_type == 'all' or filter_type == 'mcp'):
                        should_broadcast = True
                        print(f"LOG HANDLER: Should broadcast formatted listing to filter: {filter_type}")
                    # Special case for integration logs - always send to 'all' and 'integration' filters
                    elif is_integration_log and (filter_type == 'all' or filter_type == 'integration'):
                        should_broadcast = True
                        print(f"LOG HANDLER: Should broadcast integration log to filter: {filter_type}")
                    # Regular log filtering
                    elif should_display_log(log_data, filter_type):
                        should_broadcast = True
                        print(f"LOG HANDLER: Should broadcast regular log to filter: {filter_type}")
                    else:
                        print(f"LOG HANDLER: Filtered out log for filter: {filter_type}")
                    
                    # Broadcast if it passed filtering
                    if should_broadcast:
                        data_str = f"data: {json.dumps(log_data)}\n\n"
                        subscriber["queue"].put(data_str)
                        print(f"LOG HANDLER: Placed log in queue for subscriber with filter: {filter_type}")
                        broadcast_count += 1
                except Exception as e:
                    print(f"LOG HANDLER ERROR: {str(e)}")
                    logging.error(f"Error sending log to subscriber: {str(e)}")
                    dead_subscribers.append(subscriber)
            
            # Remove any dead subscribers
            for dead in dead_subscribers:
                if dead in log_subscribers:
                    log_subscribers.remove(dead)
                    print(f"LOG HANDLER: Removed dead subscriber")
            
            print(f"LOG HANDLER: Broadcast complete - sent to {broadcast_count}/{active_subscribers} subscribers")

# Add the custom handler
debug_handler = DebugLogHandler()
debug_handler.setLevel(logging.INFO)
logging.getLogger().addHandler(debug_handler)

# Add HTTP request logging
@app.before_request
def before_request():
    """Log HTTP requests"""
    if request.path not in ['/status', '/debug_logs', '/debug_logs_sse']:  # Don't log polling requests
        log_message = f"HTTP {request.method}: {request.path} from {request.remote_addr}"
        if request.method == 'POST':
            # Log POST data, but exclude sensitive data
            post_data = {k: v for k, v in request.form.items() if k.lower() not in ['password', 'token', 'key']}
            log_message += f" - Data: {post_data}"
        logging.info(log_message)

@app.after_request
def after_request(response):
    """Log HTTP responses"""
    if request.path not in ['/status', '/debug_logs', '/debug_logs_sse']:  # Don't log polling responses
        logging.info(f"HTTP Response: {response.status} for {request.path}")
    return response

async def generate_text_listings(results, query):
    """Generate a human-readable text version of the listings from JSON data"""
    if not results or 'results' not in results or not results['results']:
        return None
    
    debug_logs.append({
        "timestamp": time.time(),
        "level": "INFO",
        "message": f"INTEGRATION: Processing raw listing data for text representation"
    })
    
    # Process each search result and create a readable text representation
    if 'raw_data' in results and 'searchResults' in results['raw_data']:
        for idx, raw_listing in enumerate(results['raw_data']['searchResults']):
            # Extract key summary information for the header
            listing_name = raw_listing.get('listing', {}).get('name', 'Unknown property')
            listing_title = raw_listing.get('title', {}).get('title', 'No title')
            listing_url = raw_listing.get('url', '#')
            
            # Structured content
            primary_line = raw_listing.get('listing', {}).get('structuredContent', {}).get('primaryLine', 'No primary line')
            secondary_line = raw_listing.get('listing', {}).get('structuredContent', {}).get('secondaryLine', 'No secondary line')
            
            # Price information
            price_display = "Price unknown"
            if 'structuredDisplayPrice' in raw_listing and 'primaryLine' in raw_listing['structuredDisplayPrice']:
                price_display = raw_listing['structuredDisplayPrice']['primaryLine'].get('accessibilityLabel', 'Price unknown')
            
            # Rating information
            rating_text = raw_listing.get('avgRatingA11yLabel', 'No rating')
            rating = "No rating"
            reviews_count = 0
            if 'avgRatingA11yLabel' in raw_listing:
                rating_match = re.search(r'(\d+\.\d+)', rating_text)
                if rating_match:
                    rating = f"{rating_match.group(1)} out of 5 average rating"
            
            if 'reviewsCount' in raw_listing:
                reviews_count = raw_listing.get('reviewsCount', 0)
            
            # Amenities
            amenities = raw_listing.get('listingParamOverrides', {}).get('amenities', [])
            amenities_text = "None"
            if amenities:
                if isinstance(amenities, list):
                    amenities_text = ", ".join(amenities[:5])
                    if len(amenities) > 5:
                        amenities_text += f" and {len(amenities) - 5} more"
                else:
                    amenities_text = str(amenities)
            
            # Create a human-readable header with URL link
            header = f"==================== LISTING #{idx+1}: {listing_name} ====================\n"
            header += f"Title: {listing_title}\n"
            header += f"URL: {listing_url}\n"
            header += f"Structured Content - Primary: {primary_line}\n"
            header += f"Structured Content - Secondary: {secondary_line}\n"
            header += f"Price: {price_display}\n"
            header += f"Rating: {rating_text}\n"
            header += f"Reviews: {reviews_count}\n"
            header += f"Amenities: {amenities_text}\n"
            
            # Log the header
            debug_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": header
            })
            
            # Format the listing data in a human-readable way
            def format_property(obj, path="", indent=0):
                """Format a property with indentation and path prefixes"""
                result = ""
                prefix = "  " * indent
                
                if path:
                    current_path = f"{path}"
                else:
                    current_path = ""
                
                if isinstance(obj, dict):
                    for key, value in obj.items():
                        property_path = f"{current_path}.{key}" if current_path else key
                        
                        if isinstance(value, (dict, list)) and value:  # If non-empty complex type
                            # Add a header for this nested section
                            result += f"{prefix}{property_path}:\n"
                            result += format_property(value, property_path, indent + 1)
                        else:
                            # Format the value for display
                            formatted_value = format_value(value)
                            result += f"{prefix}{property_path}: {formatted_value}\n"
                
                elif isinstance(obj, list):
                    if not obj:  # Empty list
                        result += f"{prefix}{current_path}: [] (empty list)\n"
                    elif all(isinstance(item, (str, int, float, bool, type(None))) for item in obj):
                        # Simple list of primitives
                        formatted_items = [format_value(item) for item in obj]
                        result += f"{prefix}{current_path}: [{', '.join(formatted_items)}]\n"
                    else:
                        # List of complex objects
                        result += f"{prefix}{current_path} (list with {len(obj)} items):\n"
                        for i, item in enumerate(obj):
                            result += f"{prefix}  Item #{i+1}:\n"
                            result += format_property(item, f"{current_path}[{i}]", indent + 2)
                
                else:
                    # For primitive values
                    formatted_value = format_value(obj)
                    result += f"{prefix}{current_path}: {formatted_value}\n"
                
                return result
            
            def format_value(value):
                """Format a primitive value for display"""
                if value is None:
                    return "null"
                elif isinstance(value, bool):
                    return str(value).lower()
                elif isinstance(value, (int, float)):
                    return str(value)
                elif isinstance(value, str):
                    if len(value) > 100:  # Truncate very long strings
                        return f'"{value[:100]}..." (truncated)'
                    return f'"{value}"'
                else:
                    return str(value)
            
            # Generate the human-readable version
            human_readable = format_property(raw_listing)
            
            # Log the human-readable version
            debug_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"FORMATTED LISTING #{idx+1}:\n\n{human_readable}"
            })
            
            # Add a separator between listings
            debug_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": "=" * 80
            })
        
        # Log integration complete
        debug_logs.append({
            "timestamp": time.time(),
            "level": "INFO",
            "message": "INTEGRATION: Text representation generation complete"
        })
    
    return "Listings processed and logged"

def run_nl_search(query):
    """Run the natural language search in a background thread"""
    global search_status, search_results, debug_logs
    
    # Update status
    search_status = {"status": "searching", "message": "Searching for listings..."}
    
    # Notify all status subscribers of the status change
    notify_status_subscribers(search_status)
    
    debug_logs.append({"timestamp": time.time(), "level": "INFO", "message": f"INTEGRATION: Starting search for query: '{query}'"})
    
    try:
        # First extract parameters from the query
        debug_logs.append({"timestamp": time.time(), "level": "INFO", "message": "INTEGRATION: Calling Claude to extract search parameters"})
        params = extract_search_params(query)
        logging.info(f"Extracted parameters: {params}")
        
        if not params or 'location' not in params or not params['location']:
            search_status = {"status": "error", "message": "Could not understand the location from your query. Please try again with a clearer location."}
            debug_logs.append({"timestamp": time.time(), "level": "ERROR", "message": "INTEGRATION: Claude failed to extract location from query"})
            notify_status_subscribers(search_status)
            return
        
        # Run the search - passing the already extracted parameters to avoid duplicate extraction
        debug_logs.append({
            "timestamp": time.time(), 
            "level": "INFO", 
            "message": f"INTEGRATION: Calling MCP Airbnb search with parameters: location={params['location']}, dates={params['checkin']} to {params['checkout']}, guests={params['adults']}"
        })
        
        # Call search_airbnb directly instead of nl_search to avoid duplicate parameter extraction
        results = search_airbnb(
            location=params['location'],
            checkin=params['checkin'],
            checkout=params['checkout'],
            adults=params['adults']
        )
        
        # Process the results
        if results and 'searchResults' in results:
            # Format results for display
            formatted_results = []
            for result in results['searchResults']:
                # Get the listing data 
                listing = result.get('listing', {})
                
                # Log integration point - receiving data from Airbnb API
                if listing.get('id'):
                    debug_logs.append({
                        "timestamp": time.time(),
                        "level": "INFO",
                        "message": f"INTEGRATION: Received listing data from Airbnb API - ID: {listing.get('id')}"
                    })
                
                # Extract key details
                listing_data = {
                    'id': listing.get('id', ''),
                    'name': listing.get('name', ''),
                    'title': result.get('title', {}).get('title', '') or listing.get('name', ''),
                    'city': listing.get('city', ''),
                    'roomType': listing.get('roomType', ''),
                    'type': result.get('listingType', ''),
                    'url': result.get('url', ''),
                    'location': listing.get('city', ''),
                    'reviewsCount': result.get('reviewsCount', ''),
                    'thumbnail_url': result.get('primaryImageUrl', '')
                }
                
                # Add debug log for title information
                debug_logs.append({
                    "timestamp": time.time(),
                    "level": "INFO",
                    "message": f"INTEGRATION: Listing data - name: '{listing.get('name', '')}', title from result: '{result.get('title', {}).get('title', '')}'"
                })
                
                # Add the requested specific fields
                
                # Structured content
                if listing.get('structuredContent'):
                    listing_data['structuredContent'] = {
                        'primaryLine': listing.get('structuredContent', {}).get('primaryLine', ''),
                        'secondaryLine': listing.get('structuredContent', {}).get('secondaryLine', '')
                    }
                
                # Rating with full text (already extracting numeric rating above)
                listing_data['avgRatingA11yLabel'] = result.get('avgRatingA11yLabel', '')
                
                # Price display information (already extracting basic price above)
                if result.get('structuredDisplayPrice'):
                    listing_data['structuredDisplayPrice'] = {
                        'primaryLine': result.get('structuredDisplayPrice', {}).get('primaryLine', {}),
                        'secondaryLine': result.get('structuredDisplayPrice', {}).get('secondaryLine', {})
                    }
                
                # Amenities
                if result.get('listingParamOverrides') and result.get('listingParamOverrides').get('amenities'):
                    listing_data['amenities'] = result.get('listingParamOverrides', {}).get('amenities', [])
                
                formatted_results.append(listing_data)
            
            # Update the search results and status
            search_results = {
                "query": query,
                "params": params,
                "results": formatted_results,
                "raw_data": results
            }
            search_status = {"status": "done", "params": params, "results": formatted_results}
            debug_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"INTEGRATION: Search complete - Found {len(formatted_results)} listings from Airbnb MCP"
            })
            logging.info(f"Search complete: found {len(formatted_results)} listings")
            
            # Log integration point - Generate text representation of listings
            debug_logs.append({
                "timestamp": time.time(),
                "level": "INFO",
                "message": f"INTEGRATION: Starting text representation generation for {len(formatted_results)} listings"
            })
            
            # Generate text version of the raw JSON data
            async def get_text_representation():
                text_representation = await generate_text_listings(search_results, query)
                # The text representation is already logged in the generate_text_listings function
            
            asyncio.run(get_text_representation())
            
        else:
            search_status = {"status": "error", "message": "No listings found. Please try a different search."}
            debug_logs.append({"timestamp": time.time(), "level": "WARNING", "message": f"No search results found for query: {query}"})
            logging.warning(f"No search results found for query: {query}")
        
        # Notify all status subscribers of the status change
        notify_status_subscribers(search_status)
    
    except Exception as e:
        logging.error(f"Error during search: {str(e)}")
        debug_logs.append({"timestamp": time.time(), "level": "ERROR", "message": f"Error during search: {str(e)}"})
        search_status = {"status": "error", "message": f"An error occurred: {str(e)}"}
        # Notify all status subscribers of the status change
        notify_status_subscribers(search_status)

def notify_status_subscribers(status_data):
    """Notify all status subscribers of a status change"""
    data_str = f"data: {json.dumps(status_data)}\n\n"
    with status_lock:
        dead_subscribers = []
        for subscriber in status_subscribers:
            try:
                subscriber["queue"].put(data_str)
            except:
                dead_subscribers.append(subscriber)
        
        # Remove any dead subscribers
        for dead in dead_subscribers:
            if dead in status_subscribers:
                status_subscribers.remove(dead)

@app.route('/')
def index():
    # Reset search status and results on new search
    global search_status, search_results, debug_logs
    search_status = {"status": "idle", "message": ""}
    search_results = {}
    debug_logs = []
    
    # Create templates if they don't exist
    create_templates()
    
    return render_template('nl_index.html')

@app.route('/search', methods=['POST'])
def search():
    query = request.form.get('query', '')
    
    if not query:
        return jsonify({"status": "error", "message": "No query provided"})
    
    # Reset previous search data
    global search_status, search_results, debug_logs
    search_status = {"status": "searching", "message": "Searching for listings..."}
    search_results = {}
    debug_logs = []
    
    # Start search in background thread
    thread = threading.Thread(target=run_nl_search, args=(query,))
    thread.daemon = True
    thread.start()
    
    # Return success response
    return jsonify({"status": "searching", "message": "Search started"})

@app.route('/status')
def status():
    """Return the current search status and results"""
    global search_status, search_results
    
    if search_status["status"] == "done":
        return jsonify({
            "status": search_status["status"],
            "params": search_results.get("params", {}),
            "results": search_results.get("results", [])
        })
    elif search_status["status"] == "error":
        return jsonify({
            "status": "error",
            "message": search_status["message"]
        })
    else:
        return jsonify({
            "status": "searching"
        })

@app.route('/debug_logs')
def get_debug_logs():
    """Return the debug logs for the interaction trail"""
    global debug_logs
    return jsonify(debug_logs)

@app.route('/debug_logs_sse')
def debug_logs_sse():
    """Provide debug logs as server-sent events"""
    # Get filter from query parameters
    filter_type = request.args.get('filter', 'all')
    print(f"SSE CONNECT: New connection with filter: {filter_type}")
    
    def generate():
        # Create a queue for this client
        client_queue = queue.Queue()
        subscriber_id = id(client_queue)
        
        # Register subscriber
        subscriber = {"id": subscriber_id, "queue": client_queue, "filter": filter_type}
        with log_lock:
            log_subscribers.append(subscriber)
            print(f"SSE CONNECT: Registered subscriber with filter: {filter_type}, total: {len(log_subscribers)}")
        
        # Send initial message to confirm connection is working
        yield f"data: {json.dumps({'level': 'INFO', 'message': 'SSE connection established', 'timestamp': time.time()})}\n\n"
        print(f"SSE CONNECT: Sent initial connection message")
        
        # Send all existing logs first, applying filter
        sent_count = 0
        for log in debug_logs:
            # Apply filtering logic
            if should_display_log(log, filter_type):
                yield f"data: {json.dumps(log)}\n\n"
                sent_count += 1
                
        print(f"SSE CONNECT: Sent {sent_count} existing logs to new subscriber")
        
        # Add a test log for troubleshooting
        test_log = {"timestamp": time.time(), "level": "INFO", "message": f"TEST LOG: This is a test log entry for filter: {filter_type}"}
        if should_display_log(test_log, filter_type):
            yield f"data: {json.dumps(test_log)}\n\n"
            print(f"SSE CONNECT: Sent test log")
        
        try:
            # Wait for new logs or send heartbeat
            while True:
                try:
                    # Wait for up to 10 seconds for a new log
                    data = client_queue.get(timeout=10)
                    print(f"SSE STREAM: Sending log to client with filter: {filter_type}")
                    yield data
                except queue.Empty:
                    # Send heartbeat if no new logs after timeout
                    print(f"SSE STREAM: Sending heartbeat to client with filter: {filter_type}")
                    yield f"data: {json.dumps({'heartbeat': True, 'timestamp': time.time()})}\n\n"
        finally:
            # Client disconnected, remove from subscribers
            with log_lock:
                for i, sub in enumerate(log_subscribers):
                    if sub["id"] == subscriber_id:
                        log_subscribers.pop(i)
                        print(f"SSE DISCONNECT: Subscriber removed, remaining: {len(log_subscribers)}")
                        break
    
    response = Response(generate(), mimetype="text/event-stream")
    # Add headers to prevent caching
    response.headers['Cache-Control'] = 'no-cache, no-transform'
    response.headers['X-Accel-Buffering'] = 'no'  # For Nginx
    return response

def should_display_log(log, filter_type):
    """Determine if a log should be displayed based on filter type"""
    message = log.get('message', '')
    
    # Special case for formatted listings - ALWAYS show these in 'all' and 'mcp' filters
    if 'FORMATTED LISTING' in message or '====================' in message:
        if filter_type == 'all' or filter_type == 'mcp':
            return True
        else:
            return False
    
    if filter_type == 'all':
        # Skip HTTP logs
        if 'HTTP' in message and ('GET' in message or 'POST' in message or 'Response' in message):
            return False
        return True
    
    # Check for integration logs first (highest priority)
    if filter_type == 'integration' and 'INTEGRATION:' in message:
        return True
    
    # Apply filter based on the type
    if filter_type == 'claude':
        return 'Claude' in message or 'JSON' in message or 'parameter extraction' in message
    
    if filter_type == 'mcp':
        return 'MCP' in message or 'search results' in message or 'listing' in message or 'LISTING' in message or 'FORMATTED LISTING' in message
    
    if filter_type == 'error':
        return log.get('level') == 'ERROR'
    
    # Default to showing log if no filter matches
    return True

@app.route('/status_sse')
def status_sse():
    """Provide search status as server-sent events"""
    def generate():
        # Create a queue for this client
        client_queue = queue.Queue()
        subscriber_id = id(client_queue)
        
        # Register subscriber
        subscriber = {"id": subscriber_id, "queue": client_queue}
        with status_lock:
            status_subscribers.append(subscriber)
        
        # Send current status immediately
        yield f"data: {json.dumps(search_status)}\n\n"
        
        try:
            # Wait for status updates or send heartbeat
            while True:
                try:
                    # Wait for up to 30 seconds for a status update
                    data = client_queue.get(timeout=30)
                    yield data
                except queue.Empty:
                    # Send heartbeat if no updates after timeout
                    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
        finally:
            # Client disconnected, remove from subscribers
            with status_lock:
                for i, sub in enumerate(status_subscribers):
                    if sub["id"] == subscriber_id:
                        status_subscribers.pop(i)
                        break
    
    return Response(generate(), mimetype="text/event-stream")

def create_templates():
    """Create HTML templates if they don't exist"""
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    os.makedirs(template_dir, exist_ok=True)
    
    # We don't need to create the template files here anymore since we're using a static template file

# Add a ping endpoint to keep connections alive
@app.route('/ping')
def ping():
    """Simple ping endpoint to keep connections alive"""
    return jsonify({"status": "ok", "timestamp": time.time()})

if __name__ == '__main__':
    # Add some test logs to verify logging is working
    print("STARTUP: Creating test logs")
    debug_logs.append({"timestamp": time.time(), "level": "INFO", "message": "INTEGRATION: Application startup - logging test"})
    debug_logs.append({"timestamp": time.time(), "level": "INFO", "message": "FORMATTED LISTING #TEST: Test listing data"})
    debug_logs.append({"timestamp": time.time(), "level": "INFO", "message": "Test regular log entry"})
    debug_logs.append({"timestamp": time.time(), "level": "ERROR", "message": "Test error log entry"})
    print(f"STARTUP: Created {len(debug_logs)} test logs")
    
    # Start the Flask application
    app.run(debug=True, port=8080) 