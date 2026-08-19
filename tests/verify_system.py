
import asyncio
import os
import sys
import logging

# Add project root to path
sys.path.append(os.getcwd())

from src.scrapers.factory import ScraperFactory
from src.feed_generator.live_feed import LiveFeedGenerator
from src.storage.sqlite_engine import SqliteEngine
from src.storage.sqlite_article_repository import SqliteArticleRepository
from src.domain.models import NormalizedArticle
from src.domain.enums import SourceTier, ZombieSpecies
from config.config import load_config
import hashlib
from datetime import datetime, UTC

async def verify_system():
    print("Verifying Real-Time Aggregator System...")
    
    # 1. Config Loading
    config = load_config()
    print(f"✅ Config loaded. Found {len(config.get('sources', []))} sources.")
    
    # 2. Database Init
    engine = SqliteEngine("test_live_feed.db")
    await engine.initialize_schema()
    repo = SqliteArticleRepository(engine=engine)
    print("✅ Database initialized.")
    
    # 3. Scraper Factory
    factory = ScraperFactory()
    scrapers = []
    for source in config['sources']:
        if source.get('enabled'):
            scraper = factory.create_scraper(source)
            if scraper:
                scrapers.append(scraper)
    print(f"✅ Scrapers created: {[s.name for s in scrapers]}")
    
    # 4. Run Scrapers (Limit to 1 concurrent for test stability)
    print("running scrapers...")
    articles_list = []
    for scraper in scrapers:
        try:
            print(f"  Scraping {scraper.name}...")
            articles = await scraper.scrape()
            print(f"  -> Found {len(articles)} articles.")
            articles_list.append(articles)
        except Exception as e:
            print(f"  ❌ Error scraping {scraper.name}: {e}")
            
    # 5. Feed Generation
    feed_gen = LiveFeedGenerator()
    feed = await feed_gen.generate_feed(articles_list)
    print(f"✅ Feed Generated. Total unique articles: {feed['total_articles']}")
    
    # 6. Store in DB
    now = datetime.now(UTC)
    domain_articles = []
    for raw in feed.get("articles", []):
        url = raw.get("url") or raw.get("link") or ""
        if not url:
            continue
        aid = hashlib.sha256(url.encode()).hexdigest()[:16]
        domain_articles.append(
            NormalizedArticle(
                id=aid,
                canonical_url=url,
                original_url=url,
                title=raw.get("title") or "Untitled",
                clean_text=raw.get("content") or raw.get("summary") or "",
                summary=raw.get("summary"),
                source_id=raw.get("source") or "scraper",
                source_name=raw.get("source") or "Scraper",
                source_tier=SourceTier.TIER_3_COMMUNITY,
                zombie_species=ZombieSpecies.RAW_HTTP,
                discovered_at=now,
                published_at=raw.get("published_at") if isinstance(raw.get("published_at"), datetime) else now,
                language="en",
                image_url=raw.get("image_url"),
                authors=tuple(raw.get("authors") or ()),
                tags=tuple(raw.get("tags") or ()),
                metadata={},
            )
        )
    if domain_articles:
        await repo.save_articles(domain_articles)
    print("✅ Feed stored in DB.")
    
    # 7. Retrieve from DB
    stored = await repo.get_recent_articles(limit=5)
    print(f"✅ Retrieved {len(stored)} articles from DB.")
    if stored:
        print(f"   Sample: {stored[0].title}")
        
    await engine.aclose()
    for scraper in scrapers:
        await scraper.close()

if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR) # Quiet logs
    asyncio.run(verify_system())
