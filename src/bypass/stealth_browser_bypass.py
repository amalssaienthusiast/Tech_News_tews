import asyncio
from playwright.async_api import async_playwright, BrowserContext, Page
from typing import Optional, Dict, Any
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class StealthBrowserBypass:
    """
    Advanced browser automation with stealth evasion and interactive paywall bypassing.
    Uses Playwright with enhanced stealth configurations.
    """

    # Paywall interaction selectors (site-specific)
    PAYWALL_SELECTORS = {
        "medium.com": {
            "continue_button": 'button:has-text("Continue reading")',
            "dismiss_modal": 'button[aria-label="Close"]',
            "scroll_trigger": True,
        },
        "analyticsindiamag.com": {
            "login_wall": 'div:has-text("Subscribe or log in")',
            "scroll_to_content": True,
        },
    }

    # Enhanced stealth headers
    STEALTH_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
    }

    def __init__(self):
        self.browser: Optional[BrowserContext] = None

    async def _apply_stealth(self, page: Page):
        """Apply multiple stealth evasion techniques"""

        # Override navigator.webdriver
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Mock plugins and languages
        await page.add_init_script("""
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
        """)

        # Mock chrome property
        await page.add_init_script("""
            window.chrome = {
                runtime: {}
            };
        """)

        # Remove automation痕迹
        await page.add_init_script("""
            delete navigator.__proto__.connection;
        """)

        # Set viewport to common resolution
        await page.set_viewport_size({"width": 1920, "height": 1080})

        logger.info("Stealth measures applied to browser context")

    async def _interact_with_paywall(self, page: Page, domain: str) -> bool:
        """Attempt to interactively bypass paywall buttons/modals"""

        selectors = self.PAYWALL_SELECTORS.get(domain, {})

        try:
            # Wait for potential paywall elements
            await page.wait_for_timeout(2000)

            # Click continue reading buttons
            if "continue_button" in selectors:
                button = await page.query_selector(selectors["continue_button"])
                if button and await button.is_visible():
                    logger.info(f"Found continue button, clicking...")
                    await button.click()
                    await page.wait_for_timeout(1500)
                    return True

            # Dismiss modals
            if "dismiss_modal" in selectors:
                close_btn = await page.query_selector(selectors["dismiss_modal"])
                if close_btn and await close_btn.is_visible():
                    logger.info("Found modal close button, dismissing...")
                    await close_btn.click()
                    await page.wait_for_timeout(1000)
                    return True

            # Scroll to trigger lazy loading/content unlocking
            if selectors.get("scroll_trigger"):
                logger.info("Scrolling to trigger content load...")
                await page.evaluate(
                    "window.scrollTo(0, document.body.scrollHeight / 2)"
                )
                await page.wait_for_timeout(2000)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(2000)

            return False

        except Exception as e:
            logger.warning(f"Interactive bypass failed: {e}")
            return False

    async def fetch_with_interaction(
        self, url: str, timeout: int = 30000
    ) -> Optional[str]:
        """
        Fetch page using stealth browser with interactive paywall bypassing
        """
        async with async_playwright() as p:
            browser = None
            context = None
            try:
                # Launch browser in stealth mode with headless=True for server compatibility.
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                        "--disable-extensions",
                        "--disable-gpu",
                    ],
                )

                context = await browser.new_context(
                    user_agent=self.STEALTH_HEADERS["User-Agent"],
                    viewport={"width": 1920, "height": 1080},
                    ignore_https_errors=False,
                )

                page = await context.new_page()
                await self._apply_stealth(page)

                # Set extra headers
                await page.set_extra_http_headers(self.STEALTH_HEADERS)

                # Enable request/response interception for API sniffing
                api_responses = {}

                async def intercept_response(response):
                    try:
                        # Capture JSON API responses that might contain article content
                        if "application/json" in response.headers.get(
                            "content-type", ""
                        ):
                            url = response.url
                            if any(
                                keyword in url.lower()
                                for keyword in [
                                    "api",
                                    "content",
                                    "article",
                                    "post",
                                    "data",
                                ]
                            ):
                                api_responses[url] = await response.json()
                    except Exception as e:
                        logger.debug(f"intercept_response: suppressed {type(e).__name__}: {e}")
                        pass

                page.on("response", intercept_response)

                # Navigate to page
                logger.info(f"Stealth browser navigating to: {url}")
                response = await page.goto(
                    url, wait_until="networkidle", timeout=timeout
                )

                if not response or response.status != 200:
                    logger.error(
                        f"Failed to load page: {response.status if response else 'No response'}"
                    )
                    return None

                # Get domain for site-specific logic
                domain = urlparse(url).netloc.replace("www.", "")

                # Attempt interactive bypass
                await self._interact_with_paywall(page, domain)

                # Wait for any dynamic content to load
                await page.wait_for_timeout(3000)

                # Extract content
                content = await page.content()

                # Check for API-sourced content (captured during page load)
                if api_responses:
                    logger.info(f"Captured {len(api_responses)} API responses")
                    import json

                    script = f"<script id='__CAPTURED_API_RESPONSES__' type='application/json'>{json.dumps(api_responses)}</script>"
                    content += script

                return content

            except Exception as e:
                logger.error(f"Stealth browser fetch failed: {e}")
                return None
            finally:
                if context is not None:
                    try:
                        await context.close()
                    except Exception as e:
                        logger.debug(f"intercept_response: suppressed {type(e).__name__}: {e}")
                if browser is not None:
                    try:
                        await browser.close()
                    except Exception as e:
                        logger.debug(f"intercept_response: suppressed {type(e).__name__}: {e}")
