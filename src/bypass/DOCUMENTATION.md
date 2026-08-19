# Advanced Web Scraping Browser - Complete Guide

## Table of Contents
1. [Overview](#overview)
2. [Core Concepts](#core-concepts)
3. [Architecture](#architecture)
4. [Components Explained](#components-explained)
5. [How It Works](#how-it-works)
6. [Usage Examples](#usage-examples)
7. [Advanced Features](#advanced-features)

---

## Overview

This is a powerful web scraping library written in Rust that allows you to fetch and extract data from websites. Think of it as your own programmable web browser that you can control with code.

### What Can It Do?

- **Fetch web pages** - Download HTML, JSON, XML from any website
- **Extract data** - Pull out links, images, tables, forms, and text
- **Handle cookies** - Maintain session state across requests
- **Rate limiting** - Prevent overwhelming servers with too many requests
- **Browser pooling** - Manage multiple browser instances efficiently
- **Caching** - Store previously fetched pages to speed up repeated requests
- **Stealth mode** - Look like a real browser to avoid detection
- **Multiple engines** - Use simple HTTP, headless browser, or dynamic selection

---

## Core Concepts

### 1. **Browser Engine**
The "engine" is how the browser fetches pages. There are three types:

```rust
pub enum BrowserEngine {
    Simple,      // Fast, uses HTTP requests (like curl)
    Headless,    // Full browser, can run JavaScript (like Chrome without UI)
    Dynamic,     // Smart: picks Simple for APIs, Headless for websites
}
```

**When to use which:**
- **Simple**: Fast, lightweight, good for APIs and simple HTML pages
- **Headless**: Needed for JavaScript-heavy sites (React, Vue, Angular apps)
- **Dynamic**: Automatically chooses the best option

### 2. **Page Content**
Everything you get from a webpage is stored in `PageContent`:

```rust
pub struct PageContent {
    pub url: String,              // The actual URL loaded
    pub html: String,             // Raw HTML content
    pub text: Option<String>,     // Plain text (if detected)
    pub json: Option<Value>,      // JSON data (if it's an API)
    pub headers: HashMap,         // HTTP response headers
    pub status_code: u16,         // 200 = OK, 404 = Not Found, etc.
    pub load_time: Duration,      // How long it took to load
    pub screenshots: Vec<Vec<u8>>, // Screenshots (if enabled)
    pub console_logs: Vec<String>, // JavaScript console output
    pub network_requests: Vec,    // All network calls made
    pub cookies: Vec<Cookie>,     // Cookies received
    pub redirects: Vec<String>,   // If the page redirected
}
```

### 3. **Browser Configuration**
Control how the browser behaves:

```rust
pub struct BrowserConfig {
    pub user_agent: String,        // Pretend to be Chrome, Firefox, etc.
    pub proxy: Option<String>,     // Route through a proxy server
    pub timeout: Duration,         // How long to wait before giving up
    pub cache_enabled: bool,       // Save pages for reuse
    pub javascript_enabled: bool,  // Allow JavaScript execution
    pub follow_redirects: bool,    // Follow 301/302 redirects
    pub verify_ssl: bool,          // Check SSL certificates
    pub stealth_mode: bool,        // Hide automation detection
}
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  Your Application                   │
└─────────────────────┬───────────────────────────────┘
                      │
        ┌─────────────┴─────────────┐
        │                           │
        ▼                           ▼
┌──────────────┐            ┌──────────────┐
│   Browser    │            │ BrowserPool  │
│   (Single)   │            │  (Multiple)  │
└──────┬───────┘            └──────┬───────┘
       │                           │
       │    ┌──────────────────────┘
       │    │
       ▼    ▼
┌─────────────────┐
│  Browser Engine │
│  (HTTP/Headless)│
└────────┬────────┘
         │
         ▼
    ┌────────┐
    │Internet│
    └────────┘
```

### Flow:
1. You create a Browser or get one from BrowserPool
2. Browser uses the configured Engine (Simple/Headless)
3. Engine makes the actual HTTP request or launches Chrome
4. Response is parsed into PageContent
5. You extract data using helper methods

---

## Components Explained

### 1. **Browser** (The Main Component)

This is your primary interface to the web. It manages:
- Configuration (headers, cookies, timeouts)
- State (history, cache, cookies)
- Statistics (request count, errors)

**Key Methods:**

```rust
// Create a browser
let browser = Browser::new(BrowserEngine::Simple);

// Configure it
let browser = browser
    .set_user_agent("MyBot/1.0")
    .set_timeout(Duration::from_secs(30))
    .add_header("Authorization", "Bearer token")
    .enable_cache();

// Use it
let page = browser.navigate("https://example.com")?;
```

**How navigate() works step by step:**

1. Check if browser is active (not closed)
2. Check cache for this URL (if caching enabled)
3. Increment request counter
4. Call the appropriate fetch method based on engine:
   - `fetch_with_http()` for Simple engine
   - `fetch_with_browser()` for Headless engine
5. Parse the response into PageContent
6. Store in history
7. Update cache (if enabled)
8. Return PageContent or Error

### 2. **BrowserPool** (Resource Management)

Manages multiple browser instances efficiently. Why?
- Creating browsers is expensive
- Reusing browsers is faster
- Limits memory usage

```rust
// Create a pool of up to 5 browsers
let pool = BrowserPool::new(5, BrowserEngine::Simple);

// Get a browser from the pool
let browser = pool.get_browser();

// Use it
let page = browser.navigate("https://example.com")?;

// Browser returns to pool automatically
```

**How it works:**
1. Pool maintains a list of Browser instances
2. `get_browser()` looks for an available (active) browser
3. If none available and under max_size, creates new one
4. If at max_size, removes oldest and creates new one
5. You use the browser, then it stays in pool for reuse

### 3. **WebScraper** (High-Level Interface)

Built on top of Browser, adds convenience features:

```rust
let scraper = WebScraper::new(BrowserEngine::Simple);

// Scrape multiple pages with rate limiting
let urls = vec!["https://example.com/page1", "https://example.com/page2"];
let results = scraper.scrape_multiple_pages(urls);

// Scrape paginated content
let pages = scraper.scrape_with_pagination("https://example.com/posts", 10);

// Extract structured data
let data = scraper.extract_structured_data(&page, vec!["h1", "p.content"]);
```

### 4. **RateLimiter** (Politeness)

Prevents you from overwhelming servers with requests:

```rust
// Allow 10 requests per second
let limiter = RateLimiter::new(10, Duration::from_secs(1));

limiter.wait(); // Blocks if limit reached
// Make request here
```

**How it works:**
1. Stores timestamps of recent requests
2. When `wait()` is called:
   - Remove old timestamps outside the time window
   - If at limit, calculate how long to sleep
   - Sleep if necessary
   - Add current timestamp
3. Ensures you never exceed max_requests per time_window

---

## How It Works

### The Request Lifecycle

Let's trace what happens when you call `browser.navigate("https://example.com")`:

```
1. VALIDATION
   ├─ Check if browser is active
   ├─ Increment request counter
   └─ Check cache for URL
       └─ If cached, return immediately

2. PREPARATION
   ├─ Create HTTP client with:
   │  ├─ Timeout settings
   │  ├─ User agent
   │  ├─ Proxy (if configured)
   │  └─ SSL verification
   └─ Build request with:
      ├─ Headers (Accept, Authorization, etc.)
      └─ Cookies (from configuration)

3. EXECUTION
   ├─ Send HTTP GET request
   ├─ Wait for response (up to timeout)
   └─ Handle redirects (if enabled)

4. RESPONSE PROCESSING
   ├─ Read status code (200, 404, 500, etc.)
   ├─ Read headers
   ├─ Read body content
   ├─ Detect content type (HTML, JSON, Text)
   └─ Parse accordingly:
      ├─ JSON → parse into json field
      ├─ Text → store in text field
      └─ HTML → store in html field

5. LOGGING
   ├─ Create NetworkRequest record
   ├─ Store in network_logs
   └─ Add to page_history

6. CACHING
   └─ If cache enabled, store PageContent

7. RETURN
   └─ Return PageContent to caller
```

### Data Extraction Process

After you have a `PageContent`, you extract data:

```rust
let page = browser.navigate("https://example.com")?;

// Extract links
let links = browser.get_all_links(&page);
```

**What happens inside `get_all_links()`:**

```
1. PARSING
   └─ Parse HTML string into DOM tree using scraper crate

2. SELECTING
   └─ Create CSS selector: "a[href]"
      (find all <a> tags with href attribute)

3. ITERATING
   ├─ Loop through all matching elements
   ├─ Get the "href" attribute value
   └─ Collect into Vec<String>

4. RETURN
   └─ Return vector of link URLs
```

Similar process for:
- `get_all_images()` - selects "img[src]"
- `get_elements_by_selector()` - uses your custom selector
- `extract_tables()` - selects "table", then "tr", then "td/th"
- `extract_forms()` - selects "form", then "input/textarea/select"

---

## Usage Examples

### Example 1: Basic Scraping

```rust
use std::time::Duration;

fn main() -> Result<(), String> {
    // Create a simple browser
    let browser = Browser::new(BrowserEngine::Simple)
        .set_user_agent("MyBot/1.0")
        .set_timeout(Duration::from_secs(10));
    
    // Fetch a page
    let page = browser.navigate("https://example.com")?;
    
    // Extract data
    let links = browser.get_all_links(&page);
    let text = browser.get_text(&page);
    
    println!("Found {} links", links.len());
    println!("Page text: {}", text);
    
    Ok(())
}
```

**What's happening:**
1. Creates a browser with Simple engine (HTTP requests)
2. Sets user agent to identify our bot
3. Sets 10-second timeout for requests
4. Fetches the page (makes HTTP GET request)
5. Parses HTML and extracts all links
6. Extracts all visible text from the page

### Example 2: Advanced Configuration

```rust
fn main() -> Result<(), String> {
    // Create custom configuration
    let config = BrowserConfig {
        user_agent: "Mozilla/5.0...".to_string(),
        proxy: Some("http://proxy.com:8080".to_string()),
        timeout: Duration::from_secs(30),
        cache_enabled: true,
        stealth_mode: true,
        verify_ssl: false,  // For development only!
        ..Default::default()
    };
    
    // Create browser with config
    let browser = Browser::new(BrowserEngine::Dynamic)
        .with_config(config)
        .add_cookie("session_id", "abc123");
    
    // Navigate with configuration applied
    let page = browser.navigate("https://example.com")?;
    
    Ok(())
}
```

**What's happening:**
1. Creates custom configuration with:
   - Real browser user agent (avoids detection)
   - Proxy server (routes traffic through intermediary)
   - 30-second timeout (for slow sites)
   - Cache enabled (reuses previously fetched pages)
   - Stealth mode (hides automation signals)
   - SSL verification disabled (for testing only)
2. Uses Dynamic engine (smart selection)
3. Adds session cookie for authenticated access

### Example 3: Scraping Multiple Pages

```rust
fn main() -> Result<(), String> {
    // Create scraper with rate limiting
    let scraper = WebScraper::new(BrowserEngine::Simple);
    
    // List of URLs to scrape
    let urls = vec![
        "https://example.com/page1",
        "https://example.com/page2",
        "https://example.com/page3",
    ];
    
    // Scrape all pages (rate limited automatically)
    let results = scraper.scrape_multiple_pages(urls);
    
    // Process results
    for (i, result) in results.iter().enumerate() {
        match result {
            Ok(page) => {
                println!("Page {}: {} links found", i, 
                    scraper.browser.get_all_links(page).len());
            }
            Err(e) => println!("Page {}: Error - {}", i, e),
        }
    }
    
    Ok(())
}
```

**What's happening:**
1. Creates WebScraper (includes built-in rate limiter)
2. Defines list of URLs to fetch
3. Calls `scrape_multiple_pages()` which:
   - Loops through each URL
   - Waits using rate limiter (prevents overload)
   - Fetches each page
   - Collects results
4. Processes each result (success or error)

### Example 4: Extracting Tables

```rust
fn main() -> Result<(), String> {
    let browser = Browser::new(BrowserEngine::Simple);
    let page = browser.navigate("https://example.com/data.html")?;
    
    // Extract all tables from the page
    let tables = browser.extract_tables(&page);
    
    // Process first table
    if let Some(table) = tables.first() {
        println!("Table has {} rows", table.len());
        
        // Print header row
        if let Some(header) = table.first() {
            println!("Columns: {:?}", header);
        }
        
        // Print data rows
        for row in table.iter().skip(1) {
            println!("Row: {:?}", row);
        }
    }
    
    Ok(())
}
```

**What's happening:**
1. Fetches a page with HTML tables
2. `extract_tables()` finds all `<table>` elements
3. For each table, extracts rows and cells
4. Returns as Vec<Vec<Vec<String>>> structure:
   - Outer Vec: list of tables
   - Middle Vec: list of rows in a table
   - Inner Vec: list of cells in a row
5. Processes the first table's data

### Example 5: Browser Pool for Concurrent Scraping

```rust
use std::thread;

fn main() -> Result<(), String> {
    // Create pool of 5 browsers
    let pool = Arc::new(BrowserPool::new(5, BrowserEngine::Simple));
    
    let urls = vec![
        "https://example.com/1",
        "https://example.com/2",
        "https://example.com/3",
        "https://example.com/4",
        "https://example.com/5",
    ];
    
    let mut handles = vec![];
    
    // Spawn thread for each URL
    for url in urls {
        let pool = Arc::clone(&pool);
        
        let handle = thread::spawn(move || {
            // Get browser from pool
            let browser = pool.get_browser();
            
            // Scrape the page
            match browser.navigate(url) {
                Ok(page) => {
                    println!("{}: {} bytes", url, page.html.len());
                }
                Err(e) => println!("{}: Error - {}", url, e),
            }
        });
        
        handles.push(handle);
    }
    
    // Wait for all threads
    for handle in handles {
        handle.join().unwrap();
    }
    
    Ok(())
}
```

**What's happening:**
1. Creates pool with 5 browser slots
2. Wraps pool in Arc (atomic reference count) for thread safety
3. For each URL:
   - Spawns a new thread
   - Thread gets browser from pool
   - Thread scrapes its URL
   - Browser returns to pool
4. Waits for all threads to complete
5. Efficient: reuses browsers instead of creating 5 new ones

---

## Advanced Features

### 1. **Caching System**

```rust
let browser = Browser::new(BrowserEngine::Simple)
    .enable_cache();

// First request: fetches from web
let page1 = browser.navigate("https://example.com")?;  // Slow

// Second request: returns from cache
let page2 = browser.navigate("https://example.com")?;  // Fast!
```

**How it works:**
- Uses HashMap to store URL → PageContent mapping
- On navigate(), checks cache first
- If found, returns immediately (no network request)
- If not found, fetches and stores in cache
- Controlled by `cache_enabled` flag

### 2. **Rate Limiting**

```rust
let limiter = RateLimiter::new(
    5,                          // Max 5 requests
    Duration::from_secs(10)     // Per 10 seconds
);

for url in urls {
    limiter.wait();  // Blocks if limit reached
    let page = browser.navigate(url)?;
}
```

**How it works:**
- Maintains Vec of request timestamps
- Before each request:
  - Removes timestamps older than time_window
  - If at max_requests, calculates sleep time
  - Sleeps to respect rate limit
  - Adds current timestamp
- Ensures politeness to servers

### 3. **Stealth Mode**

```rust
let browser = Browser::new(BrowserEngine::Headless)
    .enable_stealth_mode();
```

**How it works:**
- Adds Chrome flag: `--disable-blink-features=AutomationControlled`
- This hides the `navigator.webdriver` property
- Makes the browser look like a real human user
- Helps avoid bot detection systems

### 4. **POST Requests**

```rust
let mut data = HashMap::new();
data.insert("username".to_string(), "user".to_string());
data.insert("password".to_string(), "pass".to_string());

let page = browser.post("https://example.com/login", data)?;
```

**How it works:**
- Creates POST request instead of GET
- Encodes data as form-urlencoded
- Sends to server
- Returns response as PageContent

### 5. **Statistics Tracking**

```rust
let stats = browser.get_statistics();

println!("Total requests: {}", stats.total_requests);
println!("Errors: {}", stats.total_errors);
println!("Pages visited: {}", stats.pages_visited);
println!("Cache size: {}", stats.cache_size);
```

**How it works:**
- Browser maintains counters using Arc<Mutex<T>>
- Increments on each operation
- Thread-safe (can be used from multiple threads)
- Useful for monitoring and debugging

---

## Memory Management

### How Rust Helps

1. **Ownership**: Each Browser owns its data
2. **Arc<Mutex<T>>**: For shared, thread-safe data
3. **Clone**: BrowserPool can hand out clones safely
4. **Drop**: Resources cleaned up automatically

### Thread Safety

```rust
Arc<Mutex<Vec<PageContent>>>
 │    │     └─ Actual data
 │    └─ Mutex ensures only one thread accesses at a time
 └─ Arc allows sharing across threads
```

When you call `browser.get_history()`:
1. Locks the mutex (waits if another thread has it)
2. Clones the vector
3. Releases the lock
4. Returns the clone

---

## Common Patterns

### Pattern 1: Try Multiple URLs Until One Works

```rust
let urls = vec!["https://site1.com", "https://site2.com"];

for url in urls {
    match browser.navigate(url) {
        Ok(page) => {
            println!("Success with {}", url);
            // Process page
            break;
        }
        Err(e) => {
            println!("Failed {}: {}", url, e);
            continue;
        }
    }
}
```

### Pattern 2: Retry with Exponential Backoff

```rust
let mut delay = Duration::from_secs(1);

for attempt in 1..=5 {
    match browser.navigate(url) {
        Ok(page) => return Ok(page),
        Err(e) => {
            println!("Attempt {} failed: {}", attempt, e);
            thread::sleep(delay);
            delay *= 2;  // 1s, 2s, 4s, 8s, 16s
        }
    }
}
```

### Pattern 3: Scrape and Follow Links

```rust
let page = browser.navigate("https://example.com")?;
let links = browser.get_all_links(&page);

for link in links {
    if link.starts_with("http") {
        limiter.wait();
        if let Ok(subpage) = browser.navigate(&link) {
            // Process subpage
        }
    }
}
```

---

## Performance Tips

1. **Use Simple engine when possible** - 10x faster than Headless
2. **Enable caching** - Avoid redundant requests
3. **Use BrowserPool** - Reuse browser instances
4. **Set appropriate timeouts** - Don't wait too long for slow sites
5. **Use rate limiting** - Prevent overwhelming servers
6. **Process data incrementally** - Don't store all pages in memory

---

## Error Handling

The library uses `Result<T, String>` for errors:

```rust
match browser.navigate(url) {
    Ok(page) => {
        // Success: use page
    }
    Err(e) => {
        // Error: handle it
        println!("Error: {}", e);
    }
}
```

Common errors:
- "Browser has been closed" - Browser was disposed
- "Failed to fetch URL: ..." - Network error
- "Navigation failed: ..." - Page load error
- "Timeout" - Request took too long

---

## Summary

This library provides:
- **Browser**: Main interface for web scraping
- **BrowserEngine**: Choice of HTTP or Headless Chrome
- **BrowserConfig**: Full control over behavior
- **BrowserPool**: Efficient resource management
- **WebScraper**: High-level convenience interface
- **RateLimiter**: Polite request limiting
- **Data Extraction**: Links, images, tables, forms, text

Key concepts:
- **PageContent**: Everything from a web page
- **NetworkRequest**: Metadata about HTTP calls
- **Statistics**: Monitor performance
- **Caching**: Speed up repeated requests
- **Thread Safety**: Arc<Mutex<T>> for shared state

Use cases:
- Web scraping
- Data mining
- Testing web applications
- Automated browsing
- Content aggregation
- Price monitoring
- News gathering

Now you understand how every part works and fits together!
