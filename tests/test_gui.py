import asyncio
from unittest.mock import MagicMock
from gui_qt.app_qt_migrated import TechNewsApp
from src.engine.url_analyzer import URLAnalyzer
from PyQt6.QtWidgets import QApplication
import sys

async def main():
    app = QApplication(sys.argv)
    window = TechNewsApp()
    analyzer = URLAnalyzer()
    res = await analyzer.analyze("https://news.ycombinator.com")
    
    # simulate on_complete
    def on_complete(result):
        if result and getattr(result, "article", None):
            article = window._convert_article_to_dict(result.article)
            print("Convert successful")
            try:
                window._on_article_click(article)
                print("Click successful")
            except Exception as e:
                import traceback
                traceback.print_exc()
        else:
            print("No article")

    on_complete(res)

if __name__ == "__main__":
    asyncio.run(main())
