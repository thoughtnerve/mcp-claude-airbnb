from flask import Flask, render_template, request, jsonify
import asyncio
import json
from io import StringIO
import sys
import threading
import builtins

# Import the core functionality from simple_mcp.py
from simple_mcp import agent_loop, client, server_params, stdio_client, ClientSession

app = Flask(__name__)

# Store execution logs and results
class CaptureOutput:
    def __init__(self):
        self.logs = []
        self.current_output = ""
        self.final_result = ""
    
    def add_log(self, message):
        self.logs.append(message)
        self.current_output += message + "\n"
    
    def set_result(self, result):
        self.final_result = result
    
    def clear(self):
        self.logs = []
        self.current_output = ""
        self.final_result = ""

capture = CaptureOutput()

# Async function to run the agent_loop and capture output
async def run_agent_with_capture(prompt):
    capture.clear()
    
    # Create a custom print function
    original_print = builtins.print
    
    def custom_print(*args, **kwargs):
        message = " ".join(str(arg) for arg in args)
        capture.add_log(message)
        original_print(*args, **kwargs)
    
    # Replace the built-in print with our custom one
    builtins.print = custom_print
    
    try:
        # Run the agent loop
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                capture.add_log(f"Running agent loop with prompt: {prompt}")
                
                # Run agent loop with the prompt
                result = await agent_loop(prompt, client, session)
                
                # Make sure we have a valid result
                if result:
                    # Log details about the result
                    capture.add_log(f"Final result received: {len(result)} characters")
                    # Store the result
                    capture.set_result(result)
                    # Improve logging so we have clear markers in logs
                    capture.add_log("Claude has completed all tool calls and provided the final response.")
                else:
                    capture.add_log("Warning: Empty result received from Claude")
                    capture.set_result("No results found. Please try a different search.")
                
                return result
    finally:
        # Restore original print function
        builtins.print = original_print

# Route for the main page
@app.route('/')
def index():
    return render_template('index.html')

# Route to process the search request
@app.route('/search', methods=['POST'])
def search():
    data = request.json
    prompt = data.get('prompt', '')
    
    # Create a background task to run the agent
    def run_background_task():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_agent_with_capture(prompt))
        loop.close()
    
    thread = threading.Thread(target=run_background_task)
    thread.start()
    
    return jsonify({"status": "started"})

# Route to get the current execution status
@app.route('/status')
def status():
    # Consider a request complete if we have a final result or if we've got a substantial response from Claude
    done = bool(capture.final_result) or any(
        log in log_text for log_text in capture.logs 
        for log in ["Claude has completed all tool calls", "Final result received"]
    )
    
    # Extract the length of the final result for debugging
    result_length = len(capture.final_result) if capture.final_result else 0
    
    return jsonify({
        "logs": capture.logs,
        "current_output": capture.current_output,
        "final_result": capture.final_result,
        "result_length": result_length,
        "done": done
    })

# Create a templates directory and index.html file
@app.route('/setup')
def setup():
    import os
    
    # Create templates directory if it doesn't exist
    if not os.path.exists('templates'):
        os.makedirs('templates')
    
    # Create static directory if it doesn't exist
    if not os.path.exists('static'):
        os.makedirs('static')
    
    # Create index.html
    with open('templates/index.html', 'w') as f:
        f.write(r'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Airbnb MCP via Claude</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0-beta3/css/all.min.css">
    <style>
        :root {
            --airbnb-red: #FF385C;
            --airbnb-dark: #222222;
            --airbnb-light: #FFFFFF;
            --airbnb-gray: #717171;
            --airbnb-light-gray: #F7F7F7;
            --airbnb-border: #DDDDDD;
        }
        
        body {
            font-family: Circular, -apple-system, "system-ui", Roboto, "Helvetica Neue", sans-serif;
            color: var(--airbnb-dark);
            background-color: var(--airbnb-light);
            margin: 0;
            padding: 0;
        }
        
        .header {
            border-bottom: 1px solid var(--airbnb-border);
            padding: 20px 0;
            background-color: var(--airbnb-light);
        }
        
        .header-content {
            display: flex;
            align-items: center;
            justify-content: space-between;
            max-width: 1760px;
            margin: 0 auto;
            padding: 0 80px;
        }
        
        .logo {
            display: flex;
            align-items: center;
            color: var(--airbnb-red);
            font-weight: bold;
            font-size: 24px;
            text-decoration: none;
        }
        
        .logo i {
            margin-right: 10px;
        }
        
        .search-bar-container {
            max-width: 850px;
            margin: 32px auto;
            padding: 0 24px;
        }
        
        .search-form {
            background-color: #fff;
            border: 1px solid var(--airbnb-border);
            border-radius: 32px;
            box-shadow: 0 1px 2px rgba(0,0,0,0.08), 0 4px 12px rgba(0,0,0,0.05);
            transition: box-shadow 0.2s;
            padding: 14px 32px;
        }
        
        .search-form:focus-within {
            box-shadow: 0 6px 20px rgba(0,0,0,0.1);
        }
        
        .search-form label {
            font-size: 12px;
            font-weight: 600;
            color: var(--airbnb-dark);
        }
        
        .search-form textarea {
            border: none;
            outline: none;
            width: 100%;
            font-size: 14px;
            resize: none;
            background: transparent;
        }
        
        .search-button {
            background-color: var(--airbnb-red);
            color: white;
            padding: 14px 24px;
            border-radius: 24px;
            font-size: 16px;
            font-weight: 600;
            border: none;
            cursor: pointer;
            transition: transform 0.1s;
        }
        
        .search-button:hover {
            transform: scale(1.04);
            background-color: #E61E4D;
        }
        
        .search-button i {
            margin-right: 8px;
        }
        
        .results-section {
            max-width: 1760px;
            margin: 0 auto;
            padding: 0 80px;
        }
        
        .tabs-container {
            border-bottom: 1px solid var(--airbnb-border);
            margin-bottom: 24px;
        }
        
        .tab-list {
            display: flex;
            list-style: none;
            padding: 0;
            margin: 0;
        }
        
        .tab-item {
            margin-right: 32px;
        }
        
        .tab-button {
            background: none;
            border: none;
            padding: 16px 0;
            font-size: 16px;
            color: var(--airbnb-gray);
            cursor: pointer;
            border-bottom: 2px solid transparent;
            margin-bottom: -1px;
        }
        
        .tab-button.active {
            color: var(--airbnb-dark);
            border-bottom: 2px solid var(--airbnb-dark);
            font-weight: 500;
        }
        
        .tab-content {
            padding: 24px 0;
        }
        
        .tab-panel {
            display: none;
        }
        
        .tab-panel.active {
            display: block;
        }
        
        .results-heading {
            font-size: 32px;
            font-weight: 600;
            margin-bottom: 32px;
            color: var(--airbnb-dark);
        }
        
        .loading-indicator {
            display: inline-flex;
            align-items: center;
            font-size: 22px;
            color: var(--airbnb-dark);
            margin-bottom: 24px;
        }
        
        .loading-spinner {
            display: inline-block;
            width: 24px;
            height: 24px;
            border: 3px solid rgba(255, 56, 92, 0.25);
            border-radius: 50%;
            border-top-color: var(--airbnb-red);
            animation: spin 1s ease-in-out infinite;
            margin-left: 12px;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .execution-log {
            height: 400px;
            overflow-y: auto;
            background-color: var(--airbnb-light-gray);
            font-family: 'Menlo', monospace;
            padding: 16px;
            border-radius: 12px;
            margin-bottom: 20px;
            font-size: 14px;
            line-height: 1.5;
        }
        
        .tool-call {
            color: var(--airbnb-red);
            font-weight: 500;
            margin-bottom: 8px;
        }
        
        .tool-result {
            color: #008A05;
            margin-bottom: 8px;
        }
        
        .system-log {
            color: var(--airbnb-gray);
            margin-bottom: 8px;
        }
        
        .error {
            color: #D93900;
            margin-bottom: 8px;
        }
        
        .listings-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            grid-gap: 24px;
            margin-top: 24px;
        }
        
        .listing-card {
            border-radius: 12px;
            overflow: hidden;
            transition: transform 0.2s, box-shadow 0.2s;
            border: 1px solid var(--airbnb-border);
            background-color: #fff;
        }
        
        .listing-card:hover {
            transform: scale(1.02);
            box-shadow: 0 6px 16px rgba(0,0,0,0.12);
        }
        
        .listing-link {
            display: block;
            height: 100%;
            text-decoration: none;
            color: var(--airbnb-dark);
        }
        
        .listing-link:hover {
            text-decoration: none;
        }
        
        .listing-info {
            padding: 24px;
            height: 100%;
            display: flex;
            flex-direction: column;
        }
        
        .listing-title {
            font-weight: 600;
            font-size: 18px;
            margin-bottom: 12px;
            color: var(--airbnb-dark);
            overflow: hidden;
            text-overflow: ellipsis;
            display: -webkit-box;
            -webkit-line-clamp: 1;
            -webkit-box-orient: vertical;
        }
        
        .listing-detail {
            color: var(--airbnb-gray);
            font-size: 14px;
            margin-bottom: 8px;
        }
        
        .listing-price {
            font-weight: 600;
            color: var(--airbnb-dark);
            font-size: 16px;
            margin-top: 12px;
            margin-bottom: 8px;
        }
        
        .listing-rating {
            display: flex;
            align-items: center;
            margin-bottom: 16px;
        }
        
        .listing-rating i {
            color: var(--airbnb-dark);
            margin-right: 4px;
            font-size: 12px;
        }
        
        .listing-rating span {
            font-size: 14px;
            color: var(--airbnb-dark);
        }
        
        .view-property-button {
            background-color: var(--airbnb-red);
            color: white;
            font-size: 14px;
            font-weight: 600;
            padding: 10px 16px;
            border-radius: 8px;
            text-align: center;
            margin-top: auto;
            transition: transform 0.1s;
        }
        
        .listing-link:hover .view-property-button {
            transform: scale(1.02);
            background-color: #E61E4D;
        }
        
        .intro-text {
            font-size: 16px;
            line-height: 1.5;
            color: var(--airbnb-dark);
            margin-bottom: 32px;
        }
        
        a {
            color: var(--airbnb-red);
            text-decoration: none;
        }
        
        a:hover {
            text-decoration: underline;
        }
        
        .listing-property-type {
            display: inline-block;
            padding: 4px 8px;
            background-color: var(--airbnb-light-gray);
            border-radius: 4px;
            font-size: 12px;
            font-weight: 500;
            color: var(--airbnb-gray);
            margin-bottom: 8px;
        }
        
        .listing-badge {
            display: inline-flex;
            align-items: center;
            background-color: var(--airbnb-light-gray);
            border-radius: 4px;
            padding: 4px 8px;
            margin-right: 8px;
            margin-bottom: 8px;
            font-size: 12px;
            font-weight: 500;
        }
        
        .listing-badge i {
            margin-right: 4px;
            font-size: 12px;
        }
        
        .listing-badges {
            display: flex;
            flex-wrap: wrap;
            margin-bottom: 8px;
        }
        
        .listing-placeholder {
            height: 150px;
            background-color: var(--airbnb-light-gray);
            border-radius: 12px 12px 0 0;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 24px;
            color: var(--airbnb-gray);
        }
        
        @media (max-width: 992px) {
            .header-content {
                padding: 0 24px;
            }
            
            .results-section {
                padding: 0 24px;
            }
        }
        
        @media (max-width: 768px) {
            .listings-grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <!-- Header -->
    <header class="header">
        <div class="header-content">
            <a href="/" class="logo">
                <i class="fab fa-airbnb"></i>
                <span>Airbnb MCP via Claude</span>
            </a>
        </div>
    </header>
    
    <!-- Search Form -->
    <div class="search-bar-container">
        <form id="searchForm" class="search-form">
            <label for="prompt">WHERE TO?</label>
            <textarea id="prompt" rows="2" placeholder="Tell Claude what you're looking for...">I want to book an apartment in New York City for 2 nights from April 15 to April 17, 2025 for 2 adults</textarea>
            <div class="d-flex justify-content-end mt-2">
                <button type="submit" class="search-button" id="searchButton">
                    <i class="fas fa-search"></i>Search
                </button>
            </div>
        </form>
    </div>
    
    <!-- Results Section -->
    <div class="results-section" id="resultsSection" style="display: none;">
        <div class="loading-indicator" id="loadingIndicator">
            <span id="searchingText">Looking for places in New York...</span>
            <span class="loading-spinner"></span>
        </div>
        
        <div class="tabs-container">
            <ul class="tab-list" role="tablist">
                <li class="tab-item">
                    <button class="tab-button active" id="results-tab" data-tab="results">Places to stay</button>
                </li>
                <li class="tab-item">
                    <button class="tab-button" id="execution-tab" data-tab="execution">Search Details</button>
                </li>
            </ul>
        </div>
        
        <div class="tab-content">
            <div class="tab-panel active" id="results">
                <div id="resultContent"></div>
            </div>
            <div class="tab-panel" id="execution">
                <div class="execution-log" id="executionLog"></div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script>
        // Tab functionality
        document.querySelectorAll('.tab-button').forEach(button => {
            button.addEventListener('click', () => {
                // Remove active class from all buttons and panels
                document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
                document.querySelectorAll('.tab-panel').forEach(panel => panel.classList.remove('active'));
                
                // Add active class to clicked button and corresponding panel
                button.classList.add('active');
                document.getElementById(button.getAttribute('data-tab')).classList.add('active');
            });
        });
        
        // Search form submission
        document.getElementById('searchForm').addEventListener('submit', function(e) {
            e.preventDefault();
            
            const prompt = document.getElementById('prompt').value;
            if (!prompt) return;
            
            // Update loading text based on prompt
            const locationMatch = prompt.match(/in ([^,\.]+)/i);
            const location = locationMatch ? locationMatch[1] : 'your ideal place';
            document.getElementById('searchingText').innerText = `Looking for places in ${location}...`;
            
            // Show results section and clear previous results
            document.getElementById('resultsSection').style.display = 'block';
            document.getElementById('executionLog').innerHTML = '';
            document.getElementById('resultContent').innerHTML = '';
            document.getElementById('searchButton').disabled = true;
            document.getElementById('loadingIndicator').style.display = 'flex';
            
            // Scroll to results
            document.getElementById('resultsSection').scrollIntoView({ behavior: 'smooth' });
            
            // Start the search
            fetch('/search', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ prompt })
            })
            .then(response => response.json())
            .then(data => {
                // Poll for status updates
                pollStatus();
            })
            .catch(error => {
                console.error('Error:', error);
                document.getElementById('searchButton').disabled = false;
                document.getElementById('loadingIndicator').style.display = 'none';
            });
        });
        
        function pollStatus() {
            fetch('/status')
                .then(response => response.json())
                .then(data => {
                    // Update the execution log
                    const executionLog = document.getElementById('executionLog');
                    executionLog.innerHTML = formatLogs(data.logs);
                    executionLog.scrollTop = executionLog.scrollHeight;
                    
                    // Debug info in console
                    console.log("Status update:", {
                        done: data.done,
                        resultLength: data.result_length,
                        hasResult: Boolean(data.final_result)
                    });
                    
                    // If search is complete, update the result and stop polling
                    if (data.done && data.final_result) {
                        document.getElementById('loadingIndicator').style.display = 'none';
                        
                        console.log("Final result:", data.final_result);
                        
                        // First, add the raw response to the execution log for debugging
                        const executionLog = document.getElementById('executionLog');
                        const rawResponseDiv = document.createElement('div');
                        rawResponseDiv.className = 'system-log';
                        rawResponseDiv.style.whiteSpace = 'pre-wrap';
                        rawResponseDiv.style.border = '1px solid var(--airbnb-red)';
                        rawResponseDiv.style.padding = '8px';
                        rawResponseDiv.style.borderRadius = '4px';
                        rawResponseDiv.style.marginBottom = '16px';
                        rawResponseDiv.style.backgroundColor = '#fff0f0';
                        rawResponseDiv.innerHTML = `<strong>Raw Claude Response:</strong><br>${data.final_result.replace(/</g, '&lt;').replace(/>/g, '&gt;')}`;
                        executionLog.appendChild(rawResponseDiv);
                        
                        // Display the content
                        const resultContent = document.getElementById('resultContent');
                        resultContent.innerHTML = ''; // Clear any previous content
                        
                        // SIMPLIFIED APPROACH - Create a default intro text
                        const introDiv = document.createElement('div');
                        introDiv.className = 'intro-text';
                        introDiv.textContent = "I've found several apartment options in New York City for your 2-night stay from April 15 to April 17, 2025, for 2 adults.";
                        resultContent.appendChild(introDiv);
                        
                        // Create a simplified listings grid
                        const listingsGrid = document.createElement('div');
                        listingsGrid.className = 'listings-grid';
                        
                        // Parse the response to find basic listings information
                        const listingRegex = /(\d+\.\s*[^$\n]+).*?\$([0-9,]+).*?(\d+\.\d+)\/5.*?((?:view listing|view property))/gis;
                        let match;
                        let cardCount = 0;
                        const processedTitles = new Set(); // To avoid duplicates
                        
                        const responseText = data.final_result;
                        
                        // First, extract all URLs from the response
                        const urlRegex = /(?:\(|\[)?(https?:\/\/[^\s"']+)(?:\)|\]|\.|\,)?/g;
                        const airbnbUrls = [];
                        let urlMatch;
                        
                        while ((urlMatch = urlRegex.exec(responseText)) !== null) {
                            let url = urlMatch[1];
                            
                            // Clean up URL by removing trailing punctuation
                            if (url.endsWith(')') || url.endsWith(']') || url.endsWith(',') || url.endsWith('.')) {
                                url = url.slice(0, -1);
                            }
                            
                            // Sometimes may start with punctuation
                            if (url.startsWith('(') || url.startsWith('[')) {
                                url = url.substring(1);
                            }
                            
                            if (url.includes('airbnb.com') || url.includes('/rooms/')) {
                                airbnbUrls.push(url);
                                console.log("Found Airbnb URL:", url);
                            }
                        }
                        
                        while ((match = listingRegex.exec(responseText)) !== null) {
                            const title = match[1].trim();
                            const price = '$' + match[2].trim();
                            const rating = match[3].trim();
                            const fullMatchText = match[0]; // The entire matched text
                            
                            // Skip if we've seen this title before
                            if (processedTitles.has(title)) continue;
                            processedTitles.add(title);
                            
                            cardCount++;
                            
                            // Try to find a URL for this listing by looking for a URL near this match
                            let listingUrl = "#"; // Default fallback
                            
                            // First, look for a URL within this specific listing text
                            const listingUrlMatch = fullMatchText.match(/(?:\(|\[)?(https?:\/\/[^\s"']+)(?:\)|\]|\.|\,)?/);
                            if (listingUrlMatch) {
                                let url = listingUrlMatch[1];
                                
                                // Clean up URL by removing trailing punctuation
                                if (url.endsWith(')') || url.endsWith(']') || url.endsWith(',') || url.endsWith('.')) {
                                    url = url.slice(0, -1);
                                }
                                
                                // Sometimes may start with punctuation
                                if (url.startsWith('(') || url.startsWith('[')) {
                                    url = url.substring(1);
                                }
                                
                                if (url.includes('airbnb.com') || url.includes('/rooms/')) {
                                    listingUrl = url;
                                    console.log("Found URL in listing text:", listingUrl);
                                }
                            } 
                            // If not found in this specific listing, use the global URL list
                            else if (airbnbUrls.length >= cardCount) {
                                listingUrl = airbnbUrls[cardCount - 1];
                            }
                            
                            // Extract location from title if possible
                            let location = '';
                            const locationMatch = title.match(/in\s+([^,.]+)/i);
                            if (locationMatch) {
                                location = locationMatch[1].trim();
                            } else {
                                const commonLocations = ["New York", "Manhattan", "Brooklyn", "Queens", "Bronx", 
                                                       "Hell's Kitchen", "Jersey City", "Harlem"];
                                for (const loc of commonLocations) {
                                    if (title.includes(loc)) {
                                        location = loc;
                                        break;
                                    }
                                }
                            }
                            
                            // Extract property type from title
                            let propertyType = '';
                            const typePatterns = [
                                /apartment/i, /studio/i, /condo/i, /house/i, /room/i
                            ];
                            
                            for (const pattern of typePatterns) {
                                if (title.match(pattern)) {
                                    propertyType = pattern.source.replace(/\\/g, '').replace(/i/g, '');
                                    propertyType = propertyType.charAt(0).toUpperCase() + propertyType.slice(1);
                                    break;
                                }
                            }
                            
                            // Create a listing card
                            const card = document.createElement('div');
                            card.className = 'listing-card';
                            
                            // Add the card content
                            card.innerHTML = `
                                <a href="${listingUrl}" target="_blank" class="listing-link">
                                    <div class="listing-placeholder">
                                        <i class="fab fa-airbnb fa-2x"></i>
                                    </div>
                                    <div class="listing-info">
                                        ${propertyType ? `<div class="listing-property-type">${propertyType}</div>` : ''}
                                        <div class="listing-title">${title}</div>
                                        ${location ? `<div class="listing-detail"><i class="fas fa-map-marker-alt"></i> ${location}</div>` : ''}
                                        
                                        <div class="listing-price">${price} total</div>
                                        <div class="listing-rating">
                                            <i class="fas fa-star"></i>
                                            <span>${rating}/5</span>
                                        </div>
                                        <div class="view-property-button">
                                            <i class="fab fa-airbnb me-2"></i>View on Airbnb
                                        </div>
                                    </div>
                                </a>
                            `;
                            
                            listingsGrid.appendChild(card);
                        }
                        
                        // If we found any listings, add them to the result content
                        if (cardCount > 0) {
                            resultContent.appendChild(listingsGrid);
                            console.log(`Created ${cardCount} listing cards`);
                        } else {
                            // If no matches were found, try a different regex pattern for listings
                            const alternateRegex = /(\d+\.\s*[^$\n]+).*?\$([0-9,]+)/g;
                            
                            while ((match = alternateRegex.exec(responseText)) !== null) {
                                const title = match[1].trim();
                                const price = '$' + match[2].trim();
                                const fullMatchText = match[0]; // The entire matched text
                                
                                // Skip if we've seen this title before
                                if (processedTitles.has(title)) continue;
                                processedTitles.add(title);
                                
                                cardCount++;
                                
                                // Try to find a URL for this listing from the extracted URLs
                                let listingUrl = "#"; // Default fallback
                                
                                // First, look for a URL within this specific listing text
                                const listingUrlMatch = fullMatchText.match(/(?:\(|\[)?(https?:\/\/[^\s"']+)(?:\)|\]|\.|\,)?/);
                                if (listingUrlMatch) {
                                    let url = listingUrlMatch[1];
                                    
                                    // Clean up URL by removing trailing punctuation
                                    if (url.endsWith(')') || url.endsWith(']') || url.endsWith(',') || url.endsWith('.')) {
                                        url = url.slice(0, -1);
                                    }
                                    
                                    // Sometimes may start with punctuation
                                    if (url.startsWith('(') || url.startsWith('[')) {
                                        url = url.substring(1);
                                    }
                                    
                                    if (url.includes('airbnb.com') || url.includes('/rooms/')) {
                                        listingUrl = url;
                                        console.log("Found URL in alternate listing text:", listingUrl);
                                    }
                                } 
                                // If not found in this specific listing, use the global URL list
                                else if (airbnbUrls.length >= cardCount) {
                                    listingUrl = airbnbUrls[cardCount - 1];
                                }
                                
                                // Create a listing card
                                const card = document.createElement('div');
                                card.className = 'listing-card';
                                
                                // Add the card content with less information
                                card.innerHTML = `
                                    <a href="${listingUrl}" target="_blank" class="listing-link">
                                        <div class="listing-placeholder">
                                            <i class="fab fa-airbnb fa-2x"></i>
                                        </div>
                                        <div class="listing-info">
                                            <div class="listing-title">${title}</div>
                                            <div class="listing-price">${price} total</div>
                                            <div class="view-property-button">
                                                <i class="fab fa-airbnb me-2"></i>View on Airbnb
                                            </div>
                                        </div>
                                    </a>
                                `;
                                
                                listingsGrid.appendChild(card);
                            }
                            
                            // If we found any listings with the alternate pattern, add them to the result content
                            if (cardCount > 0) {
                                resultContent.appendChild(listingsGrid);
                                console.log(`Created ${cardCount} listing cards with alternate pattern`);
                            } else {
                                // Last resort - just show the parsed markdown
                                console.log("No listing patterns matched, showing original parsed content");
                                resultContent.innerHTML = marked.parse(data.final_result);
                            }
                        }
                        
                        document.getElementById('searchButton').disabled = false;
                    } else {
                        // Continue polling
                        setTimeout(pollStatus, 1000);
                    }
                })
                .catch(error => {
                    console.error('Error:', error);
                    document.getElementById('searchButton').disabled = false;
                    document.getElementById('loadingIndicator').style.display = 'none';
                });
        }
        
        function formatLogs(logs) {
            return logs.map(log => {
                if (log.includes('Claude is calling tool')) {
                    return `<div class="tool-call">${log}</div>`;
                } else if (log.includes('Tool response') || log.includes('Tool call successful')) {
                    return `<div class="tool-result">${log}</div>`;
                } else if (log.includes('Error')) {
                    return `<div class="error">${log}</div>`;
                } else {
                    return `<div class="system-log">${log}</div>`;
                }
            }).join('\n');
        }
    </script>
</body>
</html>''')
    
    # Create CSS file
    with open('static/style.css', 'w') as f:
        f.write('''
/* Add additional styles here */
        ''')
    
    return "Setup complete. Templates and static files created."

if __name__ == '__main__':
    # First run setup to create necessary files
    setup()
    
    # Then start the Flask app
    app.run(debug=True, host='0.0.0.0', port=8080)