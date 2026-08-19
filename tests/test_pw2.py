import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://lite.duckduckgo.com/lite/")
        await page.fill('input[name="q"]', 'test')
        await page.click('input[type="submit"]')
        await page.wait_for_selector('.result-snippet')
        html = await page.content()
        print(html[:500])
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
