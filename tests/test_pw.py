import asyncio
from playwright.async_api import async_playwright
import urllib.parse

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://lite.duckduckgo.com/lite/")
        html = await page.content()
        print(html[:500])
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
