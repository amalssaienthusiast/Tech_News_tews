import asyncio
from src.engine.url_analyzer import URLAnalyzer

async def main():
    analyzer = URLAnalyzer()
    result = await analyzer.analyze("https://example.com/article")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
