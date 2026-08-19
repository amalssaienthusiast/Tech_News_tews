import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://duckduckgo.com/?q=test&t=h_&ia=web", wait_until="domcontentloaded")
        await page.wait_for_timeout(3000) # wait 3 seconds
        html = await page.content()
        with open("ddg_html.html", "w") as f:
            f.write(html)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
