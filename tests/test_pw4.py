import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # Direct search query in URL for duckduckgo.com
        await page.goto("https://duckduckgo.com/?q=test&t=h_&ia=web", wait_until="domcontentloaded")
        
        try:
            await page.wait_for_selector('[data-testid="result-title-a"]', timeout=5000)
        except:
            pass
            
        html = await page.content()
        print("Got HTML length:", len(html))
        
        titles = await page.eval_on_selector_all('[data-testid="result-title-a"]', 'elements => elements.map(e => e.innerText)')
        print("Titles:", titles)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
