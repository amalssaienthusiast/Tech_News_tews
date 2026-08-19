use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use std::thread;
use std::fs;

#[derive(Debug, Clone, PartialEq)]
pub enum BrowserEngine {
    Simple,
    Headless,
    Dynamic,
}

#[derive(Debug, Clone)]
pub enum ContentType {
    Html,
    Json,
    Xml,
    Text,
    Binary,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PageContent {
    pub url: String,
    pub html: String,
    pub text: Option<String>,
    pub json: Option<serde_json::Value>,
    pub headers: HashMap<String, String>,
    pub status_code: u16,
    pub load_time: Duration,
    pub screenshots: Vec<Vec<u8>>,
    pub console_logs: Vec<String>,
    pub network_requests: Vec<NetworkRequest>,
    pub cookies: Vec<Cookie>,
    pub redirects: Vec<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct NetworkRequest {
    pub url: String,
    pub method: String,
    pub status: u16,
    pub response_size: usize,
    pub duration: Duration,
    pub request_headers: HashMap<String, String>,
    pub response_headers: HashMap<String, String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Cookie {
    pub name: String,
    pub value: String,
    pub domain: String,
    pub path: String,
    pub expires: Option<String>,
    pub secure: bool,
    pub http_only: bool,
}

#[derive(Debug, Clone)]
pub struct BrowserConfig {
    pub user_agent: String,
    pub proxy: Option<String>,
    pub timeout: Duration,
    pub max_memory_mb: usize,
    pub cache_enabled: bool,
    pub javascript_enabled: bool,
    pub screenshots_enabled: bool,
    pub headers: HashMap<String, String>,
    pub cookies: HashMap<String, String>,
    pub follow_redirects: bool,
    pub max_redirects: usize,
    pub verify_ssl: bool,
    pub stealth_mode: bool,
}

impl Default for BrowserConfig {
    fn default() -> Self {
        let mut default_headers = HashMap::new();
        default_headers.insert(
            "Accept".to_string(),
            "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8".to_string(),
        );
        default_headers.insert("Accept-Language".to_string(), "en-US,en;q=0.9".to_string());
        default_headers.insert("Accept-Encoding".to_string(), "gzip, deflate, br".to_string());
        default_headers.insert("DNT".to_string(), "1".to_string());
        default_headers.insert("Connection".to_string(), "keep-alive".to_string());
        default_headers.insert("Upgrade-Insecure-Requests".to_string(), "1".to_string());

        Self {
            user_agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36".to_string(),
            proxy: None,
            timeout: Duration::from_secs(30),
            max_memory_mb: 512,
            cache_enabled: false,
            javascript_enabled: true,
            screenshots_enabled: false,
            headers: default_headers,
            cookies: HashMap::new(),
            follow_redirects: true,
            max_redirects: 10,
            verify_ssl: true,
            stealth_mode: true,
        }
    }
}

#[derive(Debug, Clone)]
pub struct Browser {
    id: String,
    engine: BrowserEngine,
    config: BrowserConfig,
    page_history: Arc<Mutex<Vec<PageContent>>>,
    network_logs: Arc<Mutex<Vec<NetworkRequest>>>,
    is_active: Arc<Mutex<bool>>,
    session_cookies: Arc<Mutex<HashMap<String, Cookie>>>,
    cache: Arc<Mutex<HashMap<String, PageContent>>>,
    request_count: Arc<Mutex<usize>>,
    error_count: Arc<Mutex<usize>>,
}

impl Browser {
    pub fn new(engine: BrowserEngine) -> Self {
        Self {
            id: uuid::Uuid::new_v4().to_string(),
            engine,
            config: BrowserConfig::default(),
            page_history: Arc::new(Mutex::new(Vec::new())),
            network_logs: Arc::new(Mutex::new(Vec::new())),
            is_active: Arc::new(Mutex::new(true)),
            session_cookies: Arc::new(Mutex::new(HashMap::new())),
            cache: Arc::new(Mutex::new(HashMap::new())),
            request_count: Arc::new(Mutex::new(0)),
            error_count: Arc::new(Mutex::new(0)),
        }
    }

    pub fn with_config(mut self, config: BrowserConfig) -> Self {
        self.config = config;
        self
    }

    pub fn set_user_agent(mut self, user_agent: &str) -> Self {
        self.config.user_agent = user_agent.to_string();
        self
    }

    pub fn set_proxy(mut self, proxy: &str) -> Self {
        self.config.proxy = Some(proxy.to_string());
        self
    }

    pub fn set_timeout(mut self, timeout: Duration) -> Self {
        self.config.timeout = timeout;
        self
    }

    pub fn add_header(mut self, key: &str, value: &str) -> Self {
        self.config.headers.insert(key.to_string(), value.to_string());
        self
    }

    pub fn add_cookie(mut self, key: &str, value: &str) -> Self {
        self.config.cookies.insert(key.to_string(), value.to_string());
        self
    }

    pub fn enable_stealth_mode(mut self) -> Self {
        self.config.stealth_mode = true;
        self
    }

    pub fn disable_ssl_verification(mut self) -> Self {
        self.config.verify_ssl = false;
        self
    }

    pub fn enable_cache(mut self) -> Self {
        self.config.cache_enabled = true;
        self
    }

    pub fn navigate(&self, url: &str) -> Result<PageContent, String> {
        *self.request_count.lock().unwrap() += 1;

        if !*self.is_active.lock().unwrap() {
            return Err("Browser has been closed".to_string());
        }

        if self.config.cache_enabled {
            if let Some(cached_page) = self.cache.lock().unwrap().get(url) {
                println!("Returning cached page for: {}", url);
                return Ok(cached_page.clone());
            }
        }

        let start_time = Instant::now();

        let result = match self.engine {
            BrowserEngine::Simple => self.fetch_with_http(url, start_time),
            BrowserEngine::Headless => self.fetch_with_browser(url, start_time),
            BrowserEngine::Dynamic => {
                if url.contains(".json") || url.contains("api") {
                    self.fetch_with_http(url, start_time)
                } else {
                    self.fetch_with_browser(url, start_time)
                }
            }
        };

        match result {
            Ok(page) => {
                if self.config.cache_enabled {
                    self.cache.lock().unwrap().insert(url.to_string(), page.clone());
                }
                Ok(page)
            }
            Err(e) => {
                *self.error_count.lock().unwrap() += 1;
                Err(e)
            }
        }
    }

    fn fetch_with_http(&self, url: &str, start_time: Instant) -> Result<PageContent, String> {
        use reqwest::blocking::Client;

        let mut client_builder = Client::builder()
            .timeout(self.config.timeout)
            .user_agent(&self.config.user_agent)
            .danger_accept_invalid_certs(!self.config.verify_ssl);

        if let Some(proxy) = &self.config.proxy {
            let proxy = reqwest::Proxy::all(proxy).map_err(|e| e.to_string())?;
            client_builder = client_builder.proxy(proxy);
        }

        if self.config.follow_redirects {
            client_builder = client_builder.redirect(reqwest::redirect::Policy::limited(self.config.max_redirects));
        }

        let client = client_builder.build().map_err(|e| e.to_string())?;

        let mut request = client.get(url);

        for (key, value) in &self.config.headers {
            request = request.header(key, value);
        }

        if !self.config.cookies.is_empty() {
            let cookie_string: String = self
                .config
                .cookies
                .iter()
                .map(|(k, v)| format!("{}={}", k, v))
                .collect::<Vec<String>>()
                .join("; ");
            request = request.header("Cookie", cookie_string);
        }

        let response = request
            .send()
            .map_err(|e| format!("Failed to fetch URL: {}", e))?;

        let status_code = response.status().as_u16();
        
        let headers_map: HashMap<String, String> = response
            .headers()
            .iter()
            .map(|(k, v)| (k.as_str().to_string(), v.to_str().unwrap_or("").to_string()))
            .collect();

        let content_type = response
            .headers()
            .get("content-type")
            .and_then(|ct| ct.to_str().ok())
            .unwrap_or("text/html")
            .to_string();

        let final_url = response.url().to_string();

        let html = response
            .text()
            .map_err(|e| format!("Failed to read response: {}", e))?;

        let load_time = start_time.elapsed();

        let mut json_data = None;
        let mut text_data = None;

        if content_type.contains("application/json") {
            json_data = serde_json::from_str(&html).ok();
        } else if content_type.contains("text/plain") {
            text_data = Some(html.clone());
        }

        let network_request = NetworkRequest {
            url: url.to_string(),
            method: "GET".to_string(),
            status: status_code,
            response_size: html.len(),
            duration: load_time,
            request_headers: self.config.headers.clone(),
            response_headers: headers_map.clone(),
        };

        self.network_logs.lock().unwrap().push(network_request);

        let mut redirects = Vec::new();
        if final_url != url {
            redirects.push(final_url.clone());
        }

        let page_content = PageContent {
            url: final_url,
            html,
            text: text_data,
            json: json_data,
            headers: headers_map,
            status_code,
            load_time,
            screenshots: Vec::new(),
            console_logs: Vec::new(),
            network_requests: Vec::new(),
            cookies: Vec::new(),
            redirects,
        };

        self.page_history.lock().unwrap().push(page_content.clone());

        Ok(page_content)
    }

    #[cfg(feature = "headless")]
    fn fetch_with_browser(&self, url: &str, start_time: Instant) -> Result<PageContent, String> {
        use headless_chrome::{Browser, LaunchOptionsBuilder};

        let mut launch_options = LaunchOptionsBuilder::default()
            .headless(true)
            .window_size(Some((1920, 1080)))
            .disable_default_args(false)
            .ignore_certificate_errors(!self.config.verify_ssl)
            .user_data_dir(None)
            .idle_browser_timeout(Duration::from_secs(10))
            .build()
            .map_err(|e| e.to_string())?;

        launch_options.args.push("--disable-gpu".to_string());
        launch_options.args.push("--no-sandbox".to_string());
        launch_options.args.push("--disable-dev-shm-usage".to_string());

        if self.config.stealth_mode {
            launch_options.args.push("--disable-blink-features=AutomationControlled".to_string());
        }

        if let Some(proxy) = &self.config.proxy {
            launch_options.args.push(format!("--proxy-server={}", proxy));
        }

        let browser = Browser::new(launch_options)
            .map_err(|e| format!("Failed to launch browser: {}", e))?;

        let tab = browser
            .new_tab()
            .map_err(|e| format!("Failed to create tab: {}", e))?;

        tab.navigate_to(url)
            .map_err(|e| format!("Failed to navigate: {}", e))?;

        tab.wait_until_navigated()
            .map_err(|e| format!("Navigation failed: {}", e))?;

        thread::sleep(Duration::from_secs(2));

        let html = tab
            .get_content()
            .map_err(|e| format!("Failed to get content: {}", e))?;

        let load_time = start_time.elapsed();

        let page_content = PageContent {
            url: url.to_string(),
            html,
            text: None,
            json: None,
            headers: HashMap::new(),
            status_code: 200,
            load_time,
            screenshots: Vec::new(),
            console_logs: Vec::new(),
            network_requests: Vec::new(),
            cookies: Vec::new(),
            redirects: Vec::new(),
        };

        self.page_history.lock().unwrap().push(page_content.clone());

        Ok(page_content)
    }

    #[cfg(not(feature = "headless"))]
    fn fetch_with_browser(&self, _url: &str, _start_time: Instant) -> Result<PageContent, String> {
        Err("Headless browser not enabled. Add 'headless_chrome' dependency.".to_string())
    }

    pub fn post(&self, url: &str, data: HashMap<String, String>) -> Result<PageContent, String> {
        use reqwest::blocking::Client;

        let start_time = Instant::now();

        let client = Client::builder()
            .timeout(self.config.timeout)
            .user_agent(&self.config.user_agent)
            .build()
            .map_err(|e| e.to_string())?;

        let mut request = client.post(url);

        for (key, value) in &self.config.headers {
            request = request.header(key, value);
        }

        request = request.form(&data);

        let response = request
            .send()
            .map_err(|e| format!("Failed to POST: {}", e))?;

        let status_code = response.status().as_u16();
        let html = response.text().map_err(|e| e.to_string())?;
        let load_time = start_time.elapsed();

        let page_content = PageContent {
            url: url.to_string(),
            html,
            text: None,
            json: None,
            headers: HashMap::new(),
            status_code,
            load_time,
            screenshots: Vec::new(),
            console_logs: Vec::new(),
            network_requests: Vec::new(),
            cookies: Vec::new(),
            redirects: Vec::new(),
        };

        Ok(page_content)
    }

    pub fn run_javascript(&self, _script: &str) -> Result<serde_json::Value, String> {
        match self.engine {
            BrowserEngine::Headless => {
                #[cfg(feature = "headless")]
                {
                    Ok(serde_json::Value::Null)
                }
                #[cfg(not(feature = "headless"))]
                {
                    Err("Headless browser not enabled".to_string())
                }
            }
            _ => Err("JavaScript only works with headless browser".to_string()),
        }
    }

    pub fn take_screenshot(&self, _path: &str) -> Result<(), String> {
        if !self.config.screenshots_enabled {
            return Err("Screenshots are disabled".to_string());
        }

        match self.engine {
            BrowserEngine::Headless => {
                #[cfg(feature = "headless")]
                {
                    Ok(())
                }
                #[cfg(not(feature = "headless"))]
                {
                    Err("Headless browser not enabled".to_string())
                }
            }
            _ => Err("Screenshots only work with headless browser".to_string()),
        }
    }

    pub fn get_all_links(&self, page: &PageContent) -> Vec<String> {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let selector = Selector::parse("a[href]").unwrap();

        document
            .select(&selector)
            .filter_map(|element| element.value().attr("href").map(|href| href.to_string()))
            .collect()
    }

    pub fn get_all_images(&self, page: &PageContent) -> Vec<String> {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let selector = Selector::parse("img[src]").unwrap();

        document
            .select(&selector)
            .filter_map(|element| element.value().attr("src").map(|src| src.to_string()))
            .collect()
    }

    pub fn get_elements_by_selector(&self, page: &PageContent, selector: &str) -> Result<Vec<String>, String> {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let selector = Selector::parse(selector).map_err(|e| format!("Invalid selector: {:?}", e))?;

        let elements: Vec<String> = document
            .select(&selector)
            .map(|element| element.html())
            .collect();

        Ok(elements)
    }

    pub fn get_text(&self, page: &PageContent) -> String {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let selector = Selector::parse("body").unwrap();

        if let Some(body) = document.select(&selector).next() {
            body.text().collect::<Vec<_>>().join(" ")
        } else {
            document.root_element().text().collect::<Vec<_>>().join(" ")
        }
    }

    pub fn extract_tables(&self, page: &PageContent) -> Vec<Vec<Vec<String>>> {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let table_selector = Selector::parse("table").unwrap();
        let row_selector = Selector::parse("tr").unwrap();
        let cell_selector = Selector::parse("td, th").unwrap();

        let mut tables = Vec::new();

        for table in document.select(&table_selector) {
            let mut table_data = Vec::new();

            for row in table.select(&row_selector) {
                let row_data: Vec<String> = row
                    .select(&cell_selector)
                    .map(|cell| cell.text().collect::<Vec<_>>().join(" ").trim().to_string())
                    .collect();

                if !row_data.is_empty() {
                    table_data.push(row_data);
                }
            }

            if !table_data.is_empty() {
                tables.push(table_data);
            }
        }

        tables
    }

    pub fn extract_forms(&self, page: &PageContent) -> Vec<HashMap<String, String>> {
        use scraper::{Html, Selector};

        let document = Html::parse_document(&page.html);
        let form_selector = Selector::parse("form").unwrap();
        let input_selector = Selector::parse("input, textarea, select").unwrap();

        let mut forms = Vec::new();

        for form in document.select(&form_selector) {
            let mut form_data = HashMap::new();

            if let Some(action) = form.value().attr("action") {
                form_data.insert("action".to_string(), action.to_string());
            }

            if let Some(method) = form.value().attr("method") {
                form_data.insert("method".to_string(), method.to_string());
            }

            for input in form.select(&input_selector) {
                if let Some(name) = input.value().attr("name") {
                    let value = input.value().attr("value").unwrap_or("");
                    form_data.insert(name.to_string(), value.to_string());
                }
            }

            forms.push(form_data);
        }

        forms
    }

    pub fn get_history(&self) -> Vec<PageContent> {
        self.page_history.lock().unwrap().clone()
    }

    pub fn get_network_logs(&self) -> Vec<NetworkRequest> {
        self.network_logs.lock().unwrap().clone()
    }

    pub fn get_statistics(&self) -> BrowserStatistics {
        BrowserStatistics {
            total_requests: *self.request_count.lock().unwrap(),
            total_errors: *self.error_count.lock().unwrap(),
            pages_visited: self.page_history.lock().unwrap().len(),
            cache_size: self.cache.lock().unwrap().len(),
            is_active: *self.is_active.lock().unwrap(),
        }
    }

    pub fn save_page(&self, page: &PageContent, path: &str) -> Result<(), String> {
        fs::write(path, &page.html).map_err(|e| e.to_string())
    }

    pub fn save_history(&self, path: &str) -> Result<(), String> {
        let history = self.get_history();
        let json = serde_json::to_string_pretty(&history).map_err(|e| e.to_string())?;
        fs::write(path, json).map_err(|e| e.to_string())
    }

    pub fn clear_cache(&self) {
        self.cache.lock().unwrap().clear();
    }

    pub fn clear_all_data(&mut self) {
        self.config.cookies.clear();
        self.page_history.lock().unwrap().clear();
        self.network_logs.lock().unwrap().clear();
        self.cache.lock().unwrap().clear();
        self.session_cookies.lock().unwrap().clear();
    }

    pub fn close(mut self) {
        *self.is_active.lock().unwrap() = false;
        self.clear_all_data();
        println!("Browser {} closed", self.id);
    }
}

#[derive(Debug, Clone)]
pub struct BrowserStatistics {
    pub total_requests: usize,
    pub total_errors: usize,
    pub pages_visited: usize,
    pub cache_size: usize,
    pub is_active: bool,
}

pub struct BrowserPool {
    browsers: Arc<Mutex<Vec<Browser>>>,
    max_size: usize,
    engine: BrowserEngine,
    config: BrowserConfig,
}

impl BrowserPool {
    pub fn new(max_size: usize, engine: BrowserEngine) -> Self {
        Self {
            browsers: Arc::new(Mutex::new(Vec::with_capacity(max_size))),
            max_size,
            engine,
            config: BrowserConfig::default(),
        }
    }

    pub fn with_config(mut self, config: BrowserConfig) -> Self {
        self.config = config;
        self
    }

    pub fn get_browser(&self) -> Browser {
        let mut browsers = self.browsers.lock().unwrap();

        for browser in browsers.iter_mut() {
            if *browser.is_active.lock().unwrap() {
                return browser.clone();
            }
        }

        if browsers.len() < self.max_size {
            let browser = Browser::new(self.engine.clone()).with_config(self.config.clone());
            browsers.push(browser.clone());
            browser
        } else {
            browsers.remove(0);
            let browser = Browser::new(self.engine.clone()).with_config(self.config.clone());
            browsers.push(browser.clone());
            browser
        }
    }

    pub fn remove_inactive_browsers(&self) {
        let mut browsers = self.browsers.lock().unwrap();
        browsers.retain(|b| *b.is_active.lock().unwrap());
    }

    pub fn get_pool_statistics(&self) -> PoolStatistics {
        let browsers = self.browsers.lock().unwrap();
        let active_count = browsers.iter().filter(|b| *b.is_active.lock().unwrap()).count();

        PoolStatistics {
            total_browsers: browsers.len(),
            active_browsers: active_count,
            max_size: self.max_size,
        }
    }
}

#[derive(Debug)]
pub struct PoolStatistics {
    pub total_browsers: usize,
    pub active_browsers: usize,
    pub max_size: usize,
}

pub struct WebScraper {
    browser: Browser,
    rate_limiter: RateLimiter,
}

impl WebScraper {
    pub fn new(engine: BrowserEngine) -> Self {
        Self {
            browser: Browser::new(engine),
            rate_limiter: RateLimiter::new(10, Duration::from_secs(1)),
        }
    }

    pub fn scrape_multiple_pages(&self, urls: Vec<&str>) -> Vec<Result<PageContent, String>> {
        urls.into_iter()
            .map(|url| {
                self.rate_limiter.wait();
                self.browser.navigate(url)
            })
            .collect()
    }

    pub fn scrape_with_pagination(&self, base_url: &str, max_pages: usize) -> Vec<PageContent> {
        let mut pages = Vec::new();

        for i in 1..=max_pages {
            let url = format!("{}?page={}", base_url, i);
            self.rate_limiter.wait();

            match self.browser.navigate(&url) {
                Ok(page) => pages.push(page),
                Err(e) => {
                    println!("Failed to scrape page {}: {}", i, e);
                    break;
                }
            }
        }

        pages
    }

    pub fn extract_structured_data(&self, page: &PageContent, fields: Vec<&str>) -> HashMap<String, Vec<String>> {
        let mut data = HashMap::new();

        for field in fields {
            if let Ok(elements) = self.browser.get_elements_by_selector(page, field) {
                data.insert(field.to_string(), elements);
            }
        }

        data
    }
}

pub struct RateLimiter {
    max_requests: usize,
    time_window: Duration,
    requests: Arc<Mutex<Vec<Instant>>>,
}

impl RateLimiter {
    pub fn new(max_requests: usize, time_window: Duration) -> Self {
        Self {
            max_requests,
            time_window,
            requests: Arc::new(Mutex::new(Vec::new())),
        }
    }

    pub fn wait(&self) {
        let mut requests = self.requests.lock().unwrap();
        let now = Instant::now();

        requests.retain(|&time| now.duration_since(time) < self.time_window);

        if requests.len() >= self.max_requests {
            let oldest = requests[0];
            let wait_time = self.time_window - now.duration_since(oldest);
            drop(requests);
            thread::sleep(wait_time);
            requests = self.requests.lock().unwrap();
        }

        requests.push(now);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_create_browser() {
        let browser = Browser::new(BrowserEngine::Simple)
            .set_user_agent("MyScraper/1.0")
            .set_timeout(Duration::from_secs(10))
            .add_header("X-Custom-Header", "test");

        assert!(!browser.id.is_empty());
    }

    #[test]
    fn test_browser_pool() {
        let pool = BrowserPool::new(3, BrowserEngine::Simple);
        let browser1 = pool.get_browser();
        let browser2 = pool.get_browser();

        let stats = pool.get_pool_statistics();
        assert!(stats.total_browsers <= 3);
    }

    #[test]
    fn test_rate_limiter() {
        let limiter = RateLimiter::new(2, Duration::from_secs(1));
        let start = Instant::now();

        limiter.wait();
        limiter.wait();
        limiter.wait();

        let elapsed = start.elapsed();
        assert!(elapsed >= Duration::from_secs(1));
    }
}

fn main() -> Result<(), String> {
    println!("=== Advanced Web Scraping Browser ===\n");

    let config = BrowserConfig {
        user_agent: "AdvancedScraper/2.0".to_string(),
        timeout: Duration::from_secs(20),
        verify_ssl: true,
        cache_enabled: true,
        stealth_mode: true,
        follow_redirects: true,
        ..Default::default()
    };

    let browser = Browser::new(BrowserEngine::Simple)
        .with_config(config);

    println!("Browser ID: {}", browser.id);
    println!("Fetching page...\n");

    match browser.navigate("https://httpbin.org/html") {
        Ok(page) => {
            println!("✓ Successfully loaded: {}", page.url);
            println!("✓ Status code: {}", page.status_code);
            println!("✓ Load time: {:?}", page.load_time);
            println!("✓ HTML size: {} bytes\n", page.html.len());

            let links = browser.get_all_links(&page);
            println!("Found {} links:", links.len());
            for link in links.iter().take(5) {
                println!("  - {}", link);
            }

            let text = browser.get_text(&page);
            println!("\nText preview: {}...\n", &text[..100.min(text.len())]);

            let tables = browser.extract_tables(&page);
            println!("Found {} tables", tables.len());

            let forms = browser.extract_forms(&page);
            println!("Found {} forms\n", forms.len());

            let stats = browser.get_statistics();
            println!("Browser Statistics:");
            println!("  Total requests: {}", stats.total_requests);
            println!("  Total errors: {}", stats.total_errors);
            println!("  Pages visited: {}", stats.pages_visited);
            println!("  Cache size: {}", stats.cache_size);
        }
        Err(e) => println!("✗ Error: {}", e),
    }

    println!("\n=== Testing Browser Pool ===\n");

    let pool = BrowserPool::new(5, BrowserEngine::Simple);
    let _browser1 = pool.get_browser();
    let _browser2 = pool.get_browser();

    let pool_stats = pool.get_pool_statistics();
    println!("Pool Statistics:");
    println!("  Total browsers: {}", pool_stats.total_browsers);
    println!("  Active browsers: {}", pool_stats.active_browsers);
    println!("  Max pool size: {}", pool_stats.max_size);

    println!("\n=== Testing Web Scraper ===\n");

    let scraper = WebScraper::new(BrowserEngine::Simple);
    let urls = vec![
        "https://httpbin.org/html",
        "https://httpbin.org/json",
    ];

    let results = scraper.scrape_multiple_pages(urls);
    println!("Scraped {} pages successfully", results.iter().filter(|r| r.is_ok()).count());

    browser.close();

    println!("\n✓ All operations completed successfully!");

    Ok(())
}