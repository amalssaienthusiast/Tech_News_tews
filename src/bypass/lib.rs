use pyo3::prelude::*;
use std::collections::HashMap;
use std::time::Duration;

// Connect to the disposable_browser module
#[path = "Disposable_browser.rs"]
mod disposable_browser;

use disposable_browser::{Browser, BrowserEngine, PageContent, BrowserStatistics, BrowserPool};

// ----------------------------------------------------------------------------
// Custom Exceptions
// ----------------------------------------------------------------------------
pyo3::create_exception!(advanced_web_scraper, PyScrapeError, pyo3::exceptions::PyException);
pyo3::create_exception!(advanced_web_scraper, PyTimeoutError, pyo3::exceptions::PyTimeoutError);
pyo3::create_exception!(advanced_web_scraper, PyBrowserError, pyo3::exceptions::PyRuntimeError);

// ----------------------------------------------------------------------------
// PyPageContent: Structured Data Return
// ----------------------------------------------------------------------------
#[pyclass]
#[derive(Clone)]
struct PyPageContent {
    #[pyo3(get)]
    url: String,
    #[pyo3(get)]
    html: String,
    #[pyo3(get)]
    text: Option<String>,
    #[pyo3(get)]
    status_code: u16,
    #[pyo3(get)]
    load_time_ms: u64,
    #[pyo3(get)]
    headers: HashMap<String, String>,
    #[pyo3(get)]
    redirects: Vec<String>,
}

// Convert internal PageContent to PyPageContent
impl From<PageContent> for PyPageContent {
    fn from(content: PageContent) -> Self {
        PyPageContent {
            url: content.url,
            html: content.html,
            text: content.text,
            status_code: content.status_code,
            load_time_ms: content.load_time.as_millis() as u64,
            headers: content.headers,
            redirects: content.redirects,
        }
    }
}

// Internal conversion back to PageContent (minimal reconstruction for methods that need it)
impl PyPageContent {
    fn to_internal(&self) -> PageContent {
        PageContent {
            url: self.url.clone(),
            html: self.html.clone(),
            text: self.text.clone(),
            json: None,
            headers: self.headers.clone(),
            status_code: self.status_code,
            load_time: Duration::from_millis(self.load_time_ms),
            screenshots: Vec::new(), // Not passed back and forth to save memory
            console_logs: Vec::new(),
            network_requests: Vec::new(),
            cookies: Vec::new(),
            redirects: self.redirects.clone(),
        }
    }
}

// ----------------------------------------------------------------------------
// PyBrowserStatistics
// ----------------------------------------------------------------------------
#[pyclass]
#[derive(Clone)]
struct PyBrowserStatistics {
    #[pyo3(get)]
    total_requests: usize,
    #[pyo3(get)]
    total_errors: usize,
    #[pyo3(get)]
    pages_visited: usize,
    #[pyo3(get)]
    cache_size: usize,
    #[pyo3(get)]
    is_active: bool,
}

impl From<BrowserStatistics> for PyBrowserStatistics {
    fn from(stats: BrowserStatistics) -> Self {
        PyBrowserStatistics {
            total_requests: stats.total_requests,
            total_errors: stats.total_errors,
            pages_visited: stats.pages_visited,
            cache_size: stats.cache_size,
            is_active: stats.is_active,
        }
    }
}

// ----------------------------------------------------------------------------
// PyBrowser: The Main Scraper Class
// ----------------------------------------------------------------------------
#[pyclass]
struct PyBrowser {
    inner: Browser,
}

#[pymethods]
impl PyBrowser {
    #[new]
    #[pyo3(signature = (engine="simple", user_agent=None, timeout=30, cache_enabled=false, stealth_mode=true, verify_ssl=true))]
    fn new(
        engine: &str, 
        user_agent: Option<&str>,
        timeout: u64,
        cache_enabled: bool,
        stealth_mode: bool,
        verify_ssl: bool
    ) -> PyResult<Self> {
        let engine_enum = match engine.to_lowercase().as_str() {
            "headless" => BrowserEngine::Headless,
            "dynamic" => BrowserEngine::Dynamic,
            _ => BrowserEngine::Simple,
        };

        let mut browser = Browser::new(engine_enum);
        
        // Initial config setup
        // We use builder methods where possible, or default to config helper
        if let Some(ua) = user_agent {
            browser = browser.set_user_agent(ua);
        }
        browser = browser.set_timeout(Duration::from_secs(timeout));
        
        if cache_enabled {
            browser = browser.enable_cache();
        }
        if stealth_mode {
            browser = browser.enable_stealth_mode();
        }
        if !verify_ssl {
            browser = browser.disable_ssl_verification();
        }
        
        Ok(PyBrowser { inner: browser })
    }

    /// Navigate to a URL and return the page content
    /// Releases GIL to allow Python concurrency
    fn navigate(&self, py: Python<'_>, url: String) -> PyResult<PyPageContent> {
        // Clone for closure
        // Browser structs are not Clone, but they internally use Arc<Mutex> so they are cheap to clone?
        // Wait, checking Browser struct definition in Disposable_browser.rs...
        // #[derive(Debug)] pub struct Browser { ... } - NO Clone derive visible in snippet step 5, line 110.
        // Wait, line 110 says `#[derive(Debug)]`.
        // BUT the fields inside are mostly `Arc<Mutex<...>>` or simple types.
        // If `Browser` doesn't implement Clone, we can't move it into the closure if we want to keep `self`.
        // However, `navigate` takes `&self`.
        // The optimization guide says "Fixed Thread Safety... Proper Clone trait implementation".
        // I might need to implement Clone for Browser in Rust OR simply wrap the `navigate` logic.
        // `Browser` holds `Arc`s, so it *should* be Clone-able if we derive it.
        // Since I cannot modify Disposable_browser.rs easily to derive Clone without a full rewrite of that file,
        // and assuming the user *wanted* me to use the existing file + improvements.
        //
        // Workaround: `Browser` fields are Arc. 
        // We can't clone `Browser` if it doesn't derive Clone.
        // BUT `PyBrowser` wrapper holds `inner: Browser`.
        //
        // If I can't clone `inner`, I can't move it into `py.allow_threads` closure easily.
        // `py.allow_threads` requires `F: FnOnce() -> T + Send`.
        // `&self` is not enough if the close moves.
        //
        // ACTUALLY: The user provided `Disposable_browser.rs` in Step 5.
        // Line 110: `#[derive(Debug)]`
        // Line 111: `pub struct Browser`
        //
        // I will use `replace_file_content` on `Disposable_browser.rs` to add `Clone` to derives.
        // It is `Arc`-heavy, so cloning is cheap.
        
        let browser_clone = self.inner.clone(); 
        
        let result = py.allow_threads(move || {
            browser_clone.navigate(&url)
        });

        match result {
            Ok(content) => Ok(PyPageContent::from(content)),
            Err(e) => Err(PyScrapeError::new_err(e)),
        }
    }

    fn get_text(&self, page: &PyPageContent) -> String {
        self.inner.get_text(&page.to_internal())
    }

    fn get_all_links(&self, page: &PyPageContent) -> Vec<String> {
        self.inner.get_all_links(&page.to_internal())
    }

    fn get_all_images(&self, page: &PyPageContent) -> Vec<String> {
        self.inner.get_all_images(&page.to_internal())
    }

    fn extract_tables(&self, page: &PyPageContent) -> Vec<Vec<Vec<String>>> {
        self.inner.extract_tables(&page.to_internal())
    }

    fn extract_forms(&self, page: &PyPageContent) -> Vec<HashMap<String, String>> {
        self.inner.extract_forms(&page.to_internal())
    }

    fn get_statistics(&self) -> PyBrowserStatistics {
        PyBrowserStatistics::from(self.inner.get_statistics())
    }

    fn clear_cache(&self) {
        self.inner.clear_cache();
    }
}

// ----------------------------------------------------------------------------
// PyBrowserPool
// ----------------------------------------------------------------------------
#[pyclass]
struct PyBrowserPool {
    inner: BrowserPool
}

#[pymethods]
impl PyBrowserPool {
    #[new]
    fn new(max_size: usize, engine: &str) -> PyResult<Self> {
        let engine_enum = match engine.to_lowercase().as_str() {
            "headless" => BrowserEngine::Headless,
            "dynamic" => BrowserEngine::Dynamic,
            _ => BrowserEngine::Simple,
        };
        
        Ok(PyBrowserPool {
            inner: BrowserPool::new(max_size, engine_enum)
        })
    }

    fn get_browser(&self) -> PyBrowser {
        let browser = self.inner.get_browser();
        PyBrowser { inner: browser }
    }
    
    // Missing cleanup in Rust definition? 
    // The snippet showed `remove_inactive_browsers` on Line 703.
    fn cleanup(&self) {
        self.inner.remove_inactive_browsers();
    }
}

// ----------------------------------------------------------------------------
// Module definition
// ----------------------------------------------------------------------------
#[pymodule]
fn advanced_web_scraper(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<PyBrowser>()?;
    m.add_class::<PyPageContent>()?;
    m.add_class::<PyBrowserStatistics>()?;
    m.add_class::<PyBrowserPool>()?;
    m.add("PyScrapeError", _py.get_type::<PyScrapeError>())?;
    m.add("PyTimeoutError", _py.get_type::<PyTimeoutError>())?;
    
    // Add free functions if needed
    #[pyfn(m)]
    fn scrape_url(py: Python, url: String, engine: Option<String>) -> PyResult<PyPageContent> {
        let engine_str = engine.unwrap_or_else(|| "simple".to_string());
        // Create a temporary browser
        let browser = PyBrowser::new(&engine_str, None, 30, false, true, true)?;
        browser.navigate(py, url)
    }

    // Version
    m.add("__version__", "2.0.0")?;

    Ok(())
}
