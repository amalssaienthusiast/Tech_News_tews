"""
Playwright-based stealth browser engine.

This module provides browser automation for advanced bypass scenarios
that require JavaScript execution and real browser behavior:
- Cloudflare JavaScript challenges
- Complex paywall removal
- Dynamic content loading
- CAPTCHA challenge presentation

Uses Playwright with stealth patches to avoid detection.
"""

import asyncio
import logging
import random
from typing import Any, Dict, List, Optional

from src.bypass.stealth import StealthConfig, get_random_user_agent
from src.bypass.paywall import PAYWALL_SELECTORS

logger = logging.getLogger(__name__)

# Try to import Playwright
try:
    from playwright.async_api import async_playwright, Browser, Page, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Browser automation disabled.")


class StealthBrowser:
    """
    Playwright-based stealth browser engine.
    
    Provides headless browser automation with stealth patches
    to avoid bot detection.
    
    Attributes:
        headless: Run browser in headless mode.
        stealth_config: Stealth configuration.
        timeout: Default timeout in milliseconds.
    
    Example:
        browser = StealthBrowser()
        await browser.initialize()
        
        content = await browser.fetch_with_bypass(url, "cloudflare")
        
        await browser.close()
    """
    
    def __init__(
        self,
        headless: bool = True,
        stealth_config: Optional[StealthConfig] = None,
        timeout: int = 30000
    ):
        """
        Initialize stealth browser.
        
        Args:
            headless: Run in headless mode.
            stealth_config: Stealth configuration.
            timeout: Default timeout in ms.
        """
        if not PLAYWRIGHT_AVAILABLE:
            raise ImportError(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            )
        
        self.headless = headless
        self.stealth_config = stealth_config or StealthConfig()
        self.timeout = timeout
        
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
    
    async def initialize(self) -> None:
        """Initialize the browser instance."""
        if self._browser is not None:
            return
        
        self._playwright = await async_playwright().start()
        
        # Launch Chromium with stealth args
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--no-first-run",
                "--no-zygote",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1920,1080",
            ],
        )
        
        # Create context with stealth settings
        context_args = self.stealth_config.get_playwright_context_args()
        
        # Add Google referer and extra headers for HTTPS bypass
        context_args['extra_http_headers'] = {
            'Referer': 'https://www.google.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'cross-site',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }
        
        self._context = await self._browser.new_context(**context_args)
        
        # Add stealth scripts to all pages
        await self._context.add_init_script(self._get_stealth_script())
        
        logger.info("Stealth browser initialized with Google referer spoofing")
    
    async def close(self) -> None:
        """Close the browser instance."""
        if self._context:
            await self._context.close()
            self._context = None
        
        if self._browser:
            await self._browser.close()
            self._browser = None
        
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        
        logger.info("Stealth browser closed")
    
    async def new_page(self) -> "Page":
        """
        Create a new page.
        
        Returns:
            New Playwright page.
        """
        if not self._context:
            await self.initialize()
        
        return await self._context.new_page()
    
    async def fetch_with_bypass(
        self,
        url: str,
        bypass_type: str = "auto",
        wait_for_selector: Optional[str] = None
    ) -> str:
        """
        Fetch URL content with bypass.
        
        Args:
            url: URL to fetch.
            bypass_type: Type of bypass ("cloudflare", "paywall", "auto").
            wait_for_selector: CSS selector to wait for.
        
        Returns:
            Page HTML content.
        """
        page = await self.new_page()
        
        # Safety guard: SSRF & PDF validation
        from src.security.ssrf_guard import SSRFGuard, SSRFSecurityError
        try:
            SSRFGuard().validate_url(url)
        except SSRFSecurityError as e:
            logger.warning(f"Browser bypass rejected prohibited URL '{url}': {e}")
            await page.close()
            return ""

        if url.lower().endswith('.pdf') or '.pdf?' in url.lower():
            logger.warning(f"Browser bypass rejected PDF URL: {url}")
            await page.close()
            return ""
        
        try:
            # Navigate to URL with faster strategy
            logger.info(f"Browser navigating to: {url}")
            try:
                # Try fast domcontentloaded first
                response = await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(1)
                
                # Optionally wait for networkidle with short timeout
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception as e:
                    logger.debug(f"fetch_with_bypass: suppressed {type(e).__name__}: {e}")
                    
            except Exception as nav_error:
                logger.warning(f"Fast navigation failed: {nav_error}")
                response = await page.goto(url, wait_until="commit", timeout=self.timeout)
                await asyncio.sleep(2)
            
            # Log response status
            if response:
                logger.info(f"Browser received HTTP {response.status} from {url}")
                if response.status >= 400:
                    logger.warning(f"Browser received error status {response.status}")
            
            if bypass_type == "cloudflare" or bypass_type == "auto":
                await self._wait_for_cloudflare(page)
            
            if bypass_type == "paywall" or bypass_type == "auto":
                await self._remove_paywall_elements(page)
            
            # Wait for optional selector
            if wait_for_selector:
                try:
                    await page.wait_for_selector(
                        wait_for_selector,
                        timeout=10000
                    )
                except Exception as e:
                    logger.debug(f"fetch_with_bypass: suppressed {type(e).__name__}: {e}")
            
            # Simulate human behavior
            await self._simulate_human(page)
            
            # Get content
            content = await page.content()
            logger.info(f"Browser fetched {len(content)} chars from {url}")
            return content
            
        except Exception as e:
            logger.error(f"Browser fetch failed for {url}: {e}")
            raise
        finally:
            await page.close()
    
    async def _wait_for_cloudflare(self, page: "Page") -> None:
        """
        Wait for Cloudflare challenge to complete.
        
        Detects both element selectors and text patterns.
        
        Args:
            page: Playwright page.
        """
        # Check for Cloudflare challenge by selectors
        cf_selectors = [
            "#challenge-form",
            ".cf-browser-verification",
            "#cf-challenge-running",
            "#challenge-running",
            "#turnstile-wrapper",
        ]
        
        # Also check for text-based Cloudflare patterns
        cf_text_patterns = [
            "checking your browser",
            "just a moment",
            "enable javascript",
            "please wait",
            "ddos protection",
        ]
        
        # First check by selector
        for selector in cf_selectors:
            try:
                element = await page.query_selector(selector)
                if element:
                    logger.info(f"Cloudflare challenge detected (selector: {selector}), waiting...")
                    await self._wait_cloudflare_completion(page)
                    return
            except Exception as e:
                logger.debug(f"Cloudflare selector check error: {e}")
        
        # Then check by text content
        try:
            page_text = await page.inner_text("body")
            page_text_lower = page_text.lower()
            
            for pattern in cf_text_patterns:
                if pattern in page_text_lower:
                    logger.info(f"Cloudflare challenge detected (text: '{pattern}'), waiting...")
                    await self._wait_cloudflare_completion(page)
                    return
        except Exception as e:
            logger.debug(f"Cloudflare text check error: {e}")
    
    async def _wait_cloudflare_completion(self, page: "Page") -> None:
        """Wait for Cloudflare challenge to complete with retries."""
        max_wait_seconds = 15
        poll_interval = 1.0
        
        for i in range(int(max_wait_seconds / poll_interval)):
            await asyncio.sleep(poll_interval)
            
            try:
                # Check if challenge elements are gone
                challenge_gone = await page.evaluate("""
                    () => {
                        const selectors = ['#challenge-form', '.cf-browser-verification', 
                                          '#cf-challenge-running', '#challenge-running'];
                        const hasChallenge = selectors.some(s => document.querySelector(s));
                        const bodyText = document.body?.innerText?.toLowerCase() || '';
                        const hasBlockingText = bodyText.includes('checking your browser') ||
                                               bodyText.includes('just a moment');
                        return !hasChallenge && !hasBlockingText;
                    }
                """)
                
                if challenge_gone:
                    logger.info(f"Cloudflare challenge completed after {i+1}s")
                    await asyncio.sleep(1)  # Extra wait for page load
                    return
                    
            except Exception as e:
                logger.debug(f"Cloudflare completion check error: {e}")
        
        logger.warning(f"Cloudflare challenge did not complete within {max_wait_seconds}s")
    
    async def _smart_paywall_bypass(self, page: "Page") -> None:
        """
        Execute 'Neural DOM Eraser' logic to remove paywalls.
        
        Uses heuristic analysis of the DOM (z-index, coverage, semantics)
        to identify and remove blocking elements programmatically.
        
        Args:
            page: Playwright page.
        """
        eraser_script = """
        () => {
            const KEYWORDS = ['subscribe', 'plan', 'member', 'unlock', 'register', 'limit', 'access', 'premium', 'account', 'login'];
            const HIGH_Z_INDEX = 10;
            const COVERAGE_THRESHOLD = 0.25; // 25% of viewport
            
            logger = (msg) => console.log('[NeuralDOM] ' + msg);
            
            function getVisibleCoverage(el) {
                try {
                    const rect = el.getBoundingClientRect();
                    const viewportArea = window.innerWidth * window.innerHeight;
                    
                    if (viewportArea === 0) return 0;
                    
                    const intersectionLeft = Math.max(0, rect.left);
                    const intersectionRight = Math.min(window.innerWidth, rect.right);
                    const intersectionTop = Math.max(0, rect.top);
                    const intersectionBottom = Math.min(window.innerHeight, rect.bottom);
                    
                    if (intersectionLeft < intersectionRight && intersectionTop < intersectionBottom) {
                        const visibleArea = (intersectionRight - intersectionLeft) * (intersectionBottom - intersectionTop);
                        return visibleArea / viewportArea;
                    }
                } catch(e) {}
                return 0;
            }

            function isSemanticMatch(el) {
                if (!el.innerText) return false;
                const text = el.innerText.toLowerCase().trim();
                if (text.length > 800) return false; // Likely content if too long
                if (text.length < 3) return false;   // Too short
                return KEYWORDS.some(kw => text.includes(kw));
            }

            // 1. Identification Phase
            const candidates = [];
            document.querySelectorAll('div, section, aside, footer, header, dialog-renderer, [role="dialog"]').forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;

                const isFixedOrAbs = ['fixed', 'absolute', 'sticky'].includes(style.position);
                const zIndex = parseInt(style.zIndex, 10);
                
                if (isFixedOrAbs && !isNaN(zIndex) && zIndex > HIGH_Z_INDEX) {
                    const coverage = getVisibleCoverage(el);
                    const hasKeywords = isSemanticMatch(el);
                    
                    // Filter logic: Must block significant view OR be a semantic match
                    if (coverage > COVERAGE_THRESHOLD || (coverage > 0.05 && hasKeywords)) {
                        let score = zIndex + (coverage * 1000);
                        if (hasKeywords) score += 5000; // Boost semantic matches
                        candidates.push({el, score, hasKeywords, coverage});
                    }
                }
            });

            // 2. Surgical Removal Phase
            candidates.sort((a, b) => b.score - a.score);
            candidates.forEach(c => {
                logger(`Removing blocker: z=${c.el.style.zIndex} score=${c.score} keywords=${c.hasKeywords}`);
                c.el.remove();
            });
            
            // 3. Attribute Scrubbing Phase
            // Reset body/html scrolling
            document.body.style.overflow = 'visible';
            document.documentElement.style.overflow = 'visible';
            document.body.style.position = 'static';
            
            // Remove anti-content patterns
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                
                // Unblur
                if (style.filter.includes('blur')) {
                   el.style.filter = 'none';
                }
                
                // Allow selection
                if (style.userSelect === 'none') {
                    el.style.userSelect = 'text';
                }
                
                // Fix pointers
                if (style.pointerEvents === 'none') {
                    el.style.pointerEvents = 'auto';
                }
            });
            
            // 4. Content Rehydration (Basic)
            // Sometimes content is just set to display:none
            document.querySelectorAll('article, .article-body, .content').forEach(el => {
                if (window.getComputedStyle(el).display === 'none') {
                    el.style.display = 'block';
                }
            });
        }
        """
        
        try:
            await page.evaluate(eraser_script)
            logger.info("Neural DOM Eraser executed")
            
            # Wait a moment for layout to settle
            await asyncio.sleep(0.5)
            
        except Exception as e:
            logger.warning(f"Neural DOM Eraser failed: {e}")

    async def _remove_paywall_elements(self, page: "Page") -> None:
        """
        Remove paywall using both static selectors and neural eraser.
        """
        # Run the sophisticated eraser
        await self._smart_paywall_bypass(page)
        
        # Also run static legacy cleanup as backup
        remove_script = """
        () => {
            const selectors = %s;
            selectors.forEach(selector => {
                try {
                    document.querySelectorAll(selector).forEach(el => el.remove());
                } catch (e) {}
            });
        }
        """ % str(PAYWALL_SELECTORS)
        
        try:
            await page.evaluate(remove_script)
        except Exception as e:
            logger.debug(f"_remove_paywall_elements: suppressed {type(e).__name__}: {e}")
    
    async def _clear_metered_storage(self, page: "Page") -> None:
        """
        Clear cookies and localStorage to reset metered paywall counters.
        
        Many soft paywalls track article counts via:
        - Cookies (e.g., articleCount, visitCount)
        - localStorage (e.g., readArticles, accessCount)
        - sessionStorage
        
        Clearing these resets the "free articles remaining" counter.
        
        Args:
            page: Playwright page.
        """
        clear_script = """
        () => {
            // Clear all cookies for current domain
            document.cookie.split(';').forEach(c => {
                const name = c.split('=')[0].trim();
                // Target meter/paywall related cookies
                if (name.match(/meter|count|article|visit|payload|access|read|free|limit|paywall/i)) {
                    document.cookie = name + '=;expires=Thu, 01 Jan 1970 00:00:00 GMT;path=/';
                    console.log('[MeterReset] Cleared cookie:', name);
                }
            });
            
            // Clear localStorage items
            const keysToRemove = [];
            for (let i = 0; i < localStorage.length; i++) {
                const key = localStorage.key(i);
                if (key && key.match(/meter|count|article|visit|payload|access|read|free|limit|paywall|subscriber/i)) {
                    keysToRemove.push(key);
                }
            }
            keysToRemove.forEach(k => {
                localStorage.removeItem(k);
                console.log('[MeterReset] Cleared localStorage:', k);
            });
            
            // Clear sessionStorage items
            const sessionKeysToRemove = [];
            for (let i = 0; i < sessionStorage.length; i++) {
                const key = sessionStorage.key(i);
                if (key && key.match(/meter|count|article|visit|payload|access|read|free|limit|paywall/i)) {
                    sessionKeysToRemove.push(key);
                }
            }
            sessionKeysToRemove.forEach(k => {
                sessionStorage.removeItem(k);
                console.log('[MeterReset] Cleared sessionStorage:', k);
            });
            
            return keysToRemove.length + sessionKeysToRemove.length;
        }
        """
        
        try:
            cleared = await page.evaluate(clear_script)
            logger.info(f"Metered storage cleared: {cleared} items removed")
        except Exception as e:
            logger.debug(f"Storage clear error: {e}")
    
    async def _install_mutation_observer_defense(self, page: "Page") -> None:
        """
        Install Mutation Observer to counter dynamic paywall re-injection.
        
        Many paywalls use JavaScript to continuously re-inject overlay elements.
        This observer removes them as soon as they're added.
        
        Security Research Technique: Mutation Observer Defense
        
        Args:
            page: Playwright page.
        """
        observer_script = """
        () => {
            const PAYWALL_PATTERNS = [
                /paywall/i, /subscribe/i, /premium/i, /membership/i,
                /overlay/i, /modal/i, /blocker/i, /gate/i, /meter/i
            ];
            
            const isPaywallElement = (el) => {
                if (!el || !el.nodeType || el.nodeType !== 1) return false;
                
                // Check class names
                const className = el.className || '';
                if (typeof className === 'string' && PAYWALL_PATTERNS.some(p => p.test(className))) {
                    return true;
                }
                
                // Check ID
                const id = el.id || '';
                if (PAYWALL_PATTERNS.some(p => p.test(id))) {
                    return true;
                }
                
                // Check if it's a high z-index overlay
                const style = window.getComputedStyle(el);
                const zIndex = parseInt(style.zIndex) || 0;
                const isFixed = ['fixed', 'absolute'].includes(style.position);
                
                if (isFixed && zIndex > 1000) {
                    // Check coverage
                    const rect = el.getBoundingClientRect();
                    const coverage = (rect.width * rect.height) / (window.innerWidth * window.innerHeight);
                    if (coverage > 0.3) {
                        return true;
                    }
                }
                
                return false;
            };
            
            // Install permanent observer
            const observer = new MutationObserver((mutations) => {
                mutations.forEach(m => {
                    m.addedNodes.forEach(node => {
                        if (isPaywallElement(node)) {
                            console.log('[MutationDefense] Removed re-injected paywall:', node.className || node.id);
                            node.remove();
                        }
                    });
                });
            });
            
            observer.observe(document.body, { 
                childList: true, 
                subtree: true 
            });
            
            console.log('[MutationDefense] Observer installed');
            return true;
        }
        """
        
        try:
            await page.evaluate(observer_script)
            logger.info("Mutation Observer defense installed")
        except Exception as e:
            logger.debug(f"Mutation Observer error: {e}")
    
    async def _block_paywall_scripts(self, page: "Page") -> None:
        """
        Block known paywall-related scripts from executing.
        
        Intercepts script loading and blocks scripts matching paywall patterns.
        
        Security Research Technique: Script Blocking
        
        Args:
            page: Playwright page.
        """
        # Define patterns to block
        blocked_patterns = [
            "**/paywall*",
            "**/meter*",
            "**/piano*",
            "**/tinypass*",
            "**/subscriber*",
            "**/premium*",
            "**/access-control*",
            "**/regwall*",
        ]
        
        try:
            async def _handler(route):
                await route.abort()

            # Use Playwright's route interception
            for pattern in blocked_patterns:
                await page.route(pattern, _handler)
            
            logger.info(f"Script blocking enabled for {len(blocked_patterns)} patterns")
        except Exception as e:
            logger.debug(f"Script blocking error: {e}")
    
    async def _comprehensive_css_scrub(self, page: "Page") -> None:
        """
        Comprehensive CSS property scrubbing to reveal hidden content.
        
        Removes all CSS properties that could hide or obstruct content:
        - blur filters
        - overflow: hidden
        - user-select: none
        - pointer-events: none
        - opacity: 0
        - clip-path
        - mask
        
        Security Research Technique: CSS Property Scrubbing
        
        Args:
            page: Playwright page.
        """
        scrub_script = """
        () => {
            let scrubbed = 0;
            
            // Scrub document body and html
            ['body', 'html'].forEach(sel => {
                const el = document.querySelector(sel);
                if (el) {
                    el.style.overflow = 'visible';
                    el.style.position = 'static';
                    el.style.height = 'auto';
                }
            });
            
            // Scrub all elements
            document.querySelectorAll('*').forEach(el => {
                const style = window.getComputedStyle(el);
                
                // Remove blur
                if (style.filter && style.filter.includes('blur')) {
                    el.style.filter = 'none';
                    scrubbed++;
                }
                
                // Enable text selection
                if (style.userSelect === 'none') {
                    el.style.userSelect = 'text';
                    el.style.webkitUserSelect = 'text';
                    scrubbed++;
                }
                
                // Enable pointer events
                if (style.pointerEvents === 'none') {
                    el.style.pointerEvents = 'auto';
                    scrubbed++;
                }
                
                // Reveal hidden overflow content
                if (style.overflow === 'hidden' && el.scrollHeight > el.clientHeight) {
                    el.style.overflow = 'visible';
                    el.style.maxHeight = 'none';
                    el.style.height = 'auto';
                    scrubbed++;
                }
                
                // Remove masks and clips
                if (style.clipPath && style.clipPath !== 'none') {
                    el.style.clipPath = 'none';
                    scrubbed++;
                }
                if (style.mask && style.mask !== 'none') {
                    el.style.mask = 'none';
                    el.style.webkitMask = 'none';
                    scrubbed++;
                }
                
                // Reveal low opacity content
                if (parseFloat(style.opacity) < 0.5) {
                    // Check if it's likely content
                    if (el.tagName.match(/^(P|ARTICLE|SECTION|DIV|SPAN)$/i) && el.textContent.length > 100) {
                        el.style.opacity = '1';
                        scrubbed++;
                    }
                }
            });
            
            console.log('[CSSScrub] Scrubbed', scrubbed, 'properties');
            return scrubbed;
        }
        """
        
        try:
            count = await page.evaluate(scrub_script)
            logger.info(f"CSS scrubbing complete: {count} properties modified")
        except Exception as e:
            logger.debug(f"CSS scrub error: {e}")
    
    async def full_bypass_suite(
        self,
        url: str,
        wait_for_selector: Optional[str] = None
    ) -> str:
        """
        Execute the complete bypass suite with all research techniques.
        
        Applies ALL bypass techniques in optimal order:
        1. Script blocking (before navigation)
        2. Navigation with stealth
        3. Cloudflare challenge wait
        4. Metered storage clearing
        5. Mutation Observer defense installation
        6. Neural DOM Eraser
        7. Comprehensive CSS scrubbing
        8. Human behavior simulation
        
        This is the most comprehensive bypass method for research.
        
        Args:
            url: URL to fetch.
            wait_for_selector: Optional CSS selector to wait for.
        
        Returns:
            Fully processed page HTML content.
        """
        page = await self.new_page()
        
        try:
            # 1. Block paywall scripts before navigation
            await self._block_paywall_scripts(page)
            
            # 2. Navigate with stealth - use domcontentloaded first (faster, more reliable)
            # then optionally wait for network to settle
            logger.info(f"[FullBypass] Navigating to: {url}")
            try:
                # Try fast domcontentloaded first with 15s timeout
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                
                # Give additional time for dynamic content to load
                await asyncio.sleep(2)
                
                # Optionally wait for network to settle (with short timeout)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    logger.debug("Network not idle after 5s, proceeding anyway")
                    
            except Exception as nav_error:
                # Fallback: try with longer timeout and no strict wait
                logger.warning(f"Fast navigation failed, retrying with extended timeout: {nav_error}")
                await page.goto(url, wait_until="commit", timeout=self.timeout)
                await asyncio.sleep(3)  # Manual wait for content
            
            # 3. Wait for Cloudflare if present
            await self._wait_for_cloudflare(page)
            
            # 4. Clear metered storage
            await self._clear_metered_storage(page)
            
            # 5. Install Mutation Observer defense
            await self._install_mutation_observer_defense(page)
            
            # 6. Execute Neural DOM Eraser
            await self._smart_paywall_bypass(page)
            
            # 7. Apply comprehensive CSS scrubbing
            await self._comprehensive_css_scrub(page)
            
            # 8. Wait for optional selector
            if wait_for_selector:
                try:
                    await page.wait_for_selector(wait_for_selector, timeout=5000)
                except Exception as e:
                    logger.debug(f"full_bypass_suite: suppressed {type(e).__name__}: {e}")
            
            # 9. Simulate human behavior
            await self._simulate_human(page)
            
            # Get final content
            content = await page.content()
            logger.info(f"[FullBypass] Complete: {len(content)} chars from {url}")
            
            return content
            
        except Exception as e:
            logger.error(f"[FullBypass] Failed for {url}: {e}")
            raise
        finally:
            await page.close()
    
    async def _simulate_human(self, page: "Page") -> None:
        """
        Simulate human-like behavior on the page.
        
        Args:
            page: Playwright page.
        """
        try:
            # Random mouse movements
            for _ in range(random.randint(2, 4)):
                x = random.randint(100, 800)
                y = random.randint(100, 600)
                await page.mouse.move(x, y)
                await asyncio.sleep(random.uniform(0.1, 0.3))
            
            # Random scrolling
            scroll_amount = random.randint(100, 400)
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            await asyncio.sleep(random.uniform(0.5, 1.5))
            
            # Scroll back sometimes
            if random.random() > 0.5:
                await page.evaluate("window.scrollTo(0, 0)")
                await asyncio.sleep(random.uniform(0.3, 0.8))
                
        except Exception as e:
            logger.debug(f"Human simulation error: {e}")
    
    async def take_screenshot(
        self,
        page: "Page",
        path: str,
        full_page: bool = False
    ) -> None:
        """
        Take a screenshot of the page.
        
        Args:
            page: Playwright page.
            path: File path to save screenshot.
            full_page: Capture full page or viewport.
        """
        await page.screenshot(path=path, full_page=full_page)
        logger.info(f"Screenshot saved: {path}")
    
    def _get_stealth_script(self) -> str:
        """
        Get comprehensive JavaScript to inject for stealth.
        
        Implements all major puppeteer-extra-stealth features:
        - navigator.webdriver removal
        - iframe contentWindow patch
        - WebRTC leak prevention
        - WebGL fingerprint spoofing
        - Media codec emulation
        - sourceurl hiding
        - Chrome runtime object enhancement
        - Comprehensive automation marker removal
        
        Returns:
            JavaScript code string.
        """
        nav_overrides = self.stealth_config.get_navigator_overrides()
        webgl_info = nav_overrides.get("webgl", {})
        
        return """
        (function() {
            'use strict';
            
            // 1. Override webdriver property
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
                configurable: true,
            });
            delete navigator.__proto__.webdriver;
            
            // 2. Override hardware concurrency
            Object.defineProperty(navigator, 'hardwareConcurrency', {
                get: () => %d,
                configurable: true,
            });
            
            // 3. Override device memory
            Object.defineProperty(navigator, 'deviceMemory', {
                get: () => %d,
                configurable: true,
            });
            
            // 4. Override plugins with proper PluginArray
            Object.defineProperty(navigator, 'plugins', {
                get: () => {
                    const pluginNames = %s;
                    const plugins = [];
                    pluginNames.forEach((name) => {
                        plugins.push({
                            name: name,
                            description: name + ' Plugin',
                            filename: name.toLowerCase().replace(/ /g, '_') + '.dll',
                            length: 1,
                        });
                    });
                    return plugins;
                },
                configurable: true,
            });
            
            // 5. Override languages
            Object.defineProperty(navigator, 'languages', {
                get: () => %s,
                configurable: true,
            });
            
            // 6. Override permissions query
            if (navigator.permissions) {
                const originalQuery = navigator.permissions.query;
                navigator.permissions.query = function(parameters) {
                    if (parameters.name === 'notifications') {
                        return Promise.resolve({ state: Notification.permission });
                    }
                    return originalQuery.call(this, parameters);
                };
            }
            
            // 7. Enhanced chrome runtime object
            window.chrome = {
                app: { isInstalled: false },
                csi: function() {},
                loadTimes: function() {
                    return {
                        commitLoadTime: Date.now() / 1000,
                        connectionInfo: 'http/1.1',
                        finishDocumentLoadTime: Date.now() / 1000,
                        finishLoadTime: Date.now() / 1000,
                    };
                },
                runtime: {
                    connect: function() { return { onDisconnect: { addListener: function() {} } }; },
                    sendMessage: function() {},
                    onConnect: { addListener: function() {} },
                    onMessage: { addListener: function() {} },
                },
            };
            
            // 8. WebGL fingerprint spoofing
            const webglVendor = "%s";
            const webglRenderer = "%s";
            
            const getParameterProxyHandler = {
                apply: function(target, thisArg, args) {
                    if (args[0] === 37445) return webglVendor;
                    if (args[0] === 37446) return webglRenderer;
                    return Reflect.apply(target, thisArg, args);
                }
            };
            
            ['WebGLRenderingContext', 'WebGL2RenderingContext'].forEach(ctx => {
                if (window[ctx] && window[ctx].prototype.getParameter) {
                    window[ctx].prototype.getParameter = new Proxy(
                        window[ctx].prototype.getParameter, getParameterProxyHandler
                    );
                }
            });
            
            // 9. iframe contentWindow patch
            try {
                const origCW = Object.getOwnPropertyDescriptor(HTMLIFrameElement.prototype, 'contentWindow');
                if (origCW) {
                    Object.defineProperty(HTMLIFrameElement.prototype, 'contentWindow', {
                        get: function() {
                            const win = origCW.get.call(this);
                            if (!win) return win;
                            try {
                                win.document;
                                return new Proxy(win, {
                                    get: (t, p) => p === 'navigator' ? 
                                        new Proxy(t.navigator, { get: (n, np) => np === 'webdriver' ? undefined : n[np] }) 
                                        : t[p]
                                });
                            } catch (e) { return win; }
                        },
                        configurable: true,
                    });
                }
            } catch (e) {}
            
            // 10. WebRTC leak prevention
            if (window.RTCPeerConnection) {
                const origRTC = window.RTCPeerConnection;
                window.RTCPeerConnection = function(c, cs) {
                    if (c && c.iceServers) c.iceServers = [];
                    return new origRTC(c, cs);
                };
                window.RTCPeerConnection.prototype = origRTC.prototype;
            }
            
            // 11. Media codec emulation
            if (navigator.mediaCapabilities) {
                const origDI = navigator.mediaCapabilities.decodingInfo;
                navigator.mediaCapabilities.decodingInfo = async function(cfg) {
                    const r = await origDI.call(this, cfg);
                    return { supported: true, smooth: true, powerEfficient: true, ...r };
                };
            }
            
            // 12. Notification override
            if (window.Notification) {
                const origN = window.Notification;
                window.Notification = function(t, o) { return new origN(t, o); };
                window.Notification.prototype = origN.prototype;
                window.Notification.permission = 'default';
                window.Notification.requestPermission = async () => 'default';
            }
            
            // 13. Remove automation indicators
            ['cdc_adoQpoasnfa76pfcZLmcfl_Array', 'cdc_adoQpoasnfa76pfcZLmcfl_Promise',
             'cdc_adoQpoasnfa76pfcZLmcfl_Symbol', '__webdriver_script_fn', '__driver_evaluate',
             '__webdriver_evaluate', '__selenium_evaluate', '_selenium', 'calledSelenium',
             '$cdc_asdjflasutopfhvcZLmcfl_', 'webdriver'].forEach(p => {
                try { if (p in window) delete window[p]; } catch (e) {}
            });
            
            // 14. Hide sourceurl
            const origEval = window.eval;
            window.eval = function(c) {
                if (typeof c === 'string') c = c.replace(/\\/\\/[#@] sourceURL=.*/g, '');
                return origEval.call(window, c);
            };
            
            // 15. Navigator connection
            if (navigator.connection) {
                try {
                    Object.defineProperties(navigator.connection, {
                        rtt: { value: 100 }, downlink: { value: 10 },
                        effectiveType: { value: '4g' }, saveData: { value: false },
                    });
                } catch (e) {}
            }
            
            // 16. outerWidth/outerHeight fix
            if (window.outerWidth === 0) {
                Object.defineProperty(window, 'outerWidth', { value: window.innerWidth });
                Object.defineProperty(window, 'outerHeight', { value: window.innerHeight + 85 });
            }
        })();
        """ % (
            nav_overrides.get("hardwareConcurrency", 8),
            nav_overrides.get("deviceMemory", 8),
            str(nav_overrides.get("plugins", [])),
            str(nav_overrides.get("languages", ["en-US", "en"])),
            webgl_info.get("vendor", "Google Inc. (NVIDIA)"),
            webgl_info.get("renderer", "ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
        )


async def fetch_with_stealth_browser(
    url: str,
    bypass_type: str = "auto",
    headless: bool = True
) -> str:
    """
    Convenience function to fetch URL with stealth browser.
    
    Args:
        url: URL to fetch.
        bypass_type: Type of bypass.
        headless: Run headless.
    
    Returns:
        Page HTML content.
    """
    browser = StealthBrowser(headless=headless)
    await browser.initialize()
    
    try:
        return await browser.fetch_with_bypass(url, bypass_type)
    finally:
        await browser.close()
