import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Direct search query in URL for html.duckduckgo.com
        await page.goto("https://html.duckduckgo.com/html/?q=test")
        
        html = await page.content()
        print("Got HTML length:", len(html))
        
        titles = await page.eval_on_selector_all('.result__title', 'elements => elements.map(e => e.innerText)')
        print("Titles:", titles)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
