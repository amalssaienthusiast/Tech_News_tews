"""
Tech News Scraper v5.0 - AI-Powered Interactive TUI

A CPU-Z style terminal interface with:
- Live system stats and performance metrics
- AI-powered query processing
- Real-time article discovery
- Interactive navigation with keyboard shortcuts
"""

import asyncio
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt
    from rich import box
except ImportError:
    raise SystemExit(
        "Missing dependency 'rich'. Install project dependencies first with "
        "'pip install -r requirements.txt'."
    )

from src.engine import TechNewsOrchestrator, SearchResult
from src.core import NonTechQueryError, InvalidQueryError
from src.core.types import Article

# Import bypass module for protected content
try:
    from src.bypass import AntiBotBypass, PaywallBypass, ContentPlatformBypass, ContentPlatform
    BYPASS_AVAILABLE = True
except ImportError:
    BYPASS_AVAILABLE = False

# Import Markdown for rich formatting
try:
    from rich.markdown import Markdown
except ImportError:
    Markdown = None

console = Console()


class AINewsAgent:
    """
    AI-powered news agent that autonomously discovers tech news.
    """
    
    AUTO_QUERIES = [
        "latest artificial intelligence news",
        "cybersecurity vulnerabilities",
        "startup funding announcements",
        "new programming frameworks",
        "cloud computing updates",
    ]
    
    def __init__(self, orchestrator: TechNewsOrchestrator):
        self.orchestrator = orchestrator
        self.current_query_index = 0
    
    async def auto_discover(self) -> Optional[SearchResult]:
        """Automatically discover news using rotating queries."""
        query = self.AUTO_QUERIES[self.current_query_index]
        self.current_query_index = (self.current_query_index + 1) % len(self.AUTO_QUERIES)
        
        try:
            return await self.orchestrator.search(query, max_articles=10)
        except Exception:
            return None
    
    def get_current_topic(self) -> str:
        """Get the current auto-discovery topic."""
        return self.AUTO_QUERIES[self.current_query_index]


class TechNewsTUI:
    """
    CPU-Z style interactive terminal UI for Tech News Scraper.
    """
    
    def __init__(self):
        self.console = Console()
        self.orchestrator: Optional[TechNewsOrchestrator] = None
        self.ai_agent: Optional[AINewsAgent] = None
        self.articles: List[Article] = []
        self.selected_index = 0
        self.running = True
        self.status = "Initializing..."
        self.last_search_time = 0.0
        self.current_query = ""
        self.mode = "SEARCH"  # SEARCH, ARTICLES, ANALYSIS
        
        # Performance metrics
        self.metrics = {
            "requests": 0,
            "successes": 0,
            "failures": 0,
            "cache_hits": 0,
            "articles_found": 0,
            "queries_processed": 0,
            "uptime_start": time.time(),
        }
    
    def create_header(self) -> Panel:
        """Create the header panel."""
        title = Text()
        title.append("🔍 ", style="bold blue")
        title.append("TECH NEWS SCRAPER v5.0", style="bold white")
        title.append(" | ", style="dim")
        title.append("Enterprise Edition", style="italic cyan")
        title.append(" | ", style="dim")
        title.append("AI-Powered", style="bold green")
        
        return Panel(
            title,
            box=box.DOUBLE,
            style="white on black",
            padding=(0, 2),
        )
    
    def create_stats_panel(self) -> Panel:
        """Create CPU-Z style stats panel."""
        if self.orchestrator:
            stats = self.orchestrator.stats
            scraper_stats = stats.get('scraper_stats', {})
            self.metrics.update({
                "requests": scraper_stats.get('requests', 0),
                "successes": scraper_stats.get('successes', 0),
                "failures": scraper_stats.get('failures', 0),
                "cache_hits": scraper_stats.get('cached_hits', 0),
                "articles_found": stats.get('total_articles', 0),
                "queries_processed": stats.get('queries_processed', 0),
            })
        
        uptime = time.time() - self.metrics["uptime_start"]
        uptime_str = f"{int(uptime // 60)}m {int(uptime % 60)}s"
        
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="cyan", width=12)
        table.add_column(style="bold white", width=8)
        table.add_column(style="cyan", width=12)
        table.add_column(style="bold white", width=8)
        
        table.add_row(
            "📡 Requests:", str(self.metrics["requests"]),
            "✓ Success:", str(self.metrics["successes"]),
        )
        table.add_row(
            "❌ Failed:", str(self.metrics["failures"]),
            "💾 Cache:", str(self.metrics["cache_hits"]),
        )
        table.add_row(
            "📰 Articles:", str(self.metrics["articles_found"]),
            "🔍 Queries:", str(self.metrics["queries_processed"]),
        )
        table.add_row(
            "⏱️ Uptime:", uptime_str,
            "🤖 AI Mode:", "Active" if self.ai_agent else "Off",
        )
        
        return Panel(
            table,
            title="[bold white]📊 PERFORMANCE STATS[/]",
            box=box.ROUNDED,
            style="cyan on black",
        )
    
    def create_cache_panel(self) -> Panel:
        """Create cache stats panel."""
        if self.orchestrator:
            stats = self.orchestrator.stats
            cache_stats = stats.get('scraper_stats', {}).get('cache_stats', {})
            dedup_stats = stats.get('scraper_stats', {}).get('dedup_stats', {})
        else:
            cache_stats = {}
            dedup_stats = {}
        
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
        table.add_column(style="yellow", width=16)
        table.add_column(style="bold white", width=10)
        
        table.add_row("LRU Cache Size:", f"{cache_stats.get('size', 0)}/{cache_stats.get('max_size', 0)}")
        table.add_row("Hit Rate:", f"{cache_stats.get('hit_rate', 0):.1%}")
        table.add_row("Bloom Filter:", f"{dedup_stats.get('count', 0)} URLs")
        table.add_row("Memory:", f"{dedup_stats.get('size_kb', 0):.1f} KB")
        
        return Panel(
            table,
            title="[bold white]💾 CACHE & MEMORY[/]",
            box=box.ROUNDED,
            style="yellow on black",
        )
    
    def create_articles_panel(self) -> Panel:
        """Create articles list panel."""
        if not self.articles:
            content = Text("No articles yet. Press [S] to search or wait for AI discovery.", style="dim")
        else:
            table = Table(box=box.SIMPLE, show_header=True, padding=(0, 1))
            table.add_column("#", style="dim", width=3)
            table.add_column("Score", style="green", width=6)
            table.add_column("Title", style="white", width=60, overflow="ellipsis")
            table.add_column("Source", style="cyan", width=15)
            
            start = max(0, self.selected_index - 4)
            end = min(len(self.articles), start + 10)
            
            for i, article in enumerate(self.articles[start:end], start=start):
                score = article.tech_score.score if article.tech_score else 0
                style = "bold white on blue" if i == self.selected_index else ""
                title = article.title[:55] + "..." if len(article.title) > 55 else article.title
                source = article.source[:12] + "..." if len(article.source) > 12 else article.source
                
                table.add_row(
                    str(i + 1),
                    f"[green]{score:.2f}[/]",
                    f"[{style}]{title}[/]",
                    source,
                )
            
            content = table
        
        return Panel(
            content,
            title=f"[bold white]📰 ARTICLES ({len(self.articles)})[/]",
            subtitle=f"[dim]Query: {self.current_query or 'None'}[/]",
            box=box.ROUNDED,
            style="white on black",
        )
    
    def create_ai_panel(self) -> Panel:
        """Create AI agent status panel."""
        if self.ai_agent:
            topic = self.ai_agent.get_current_topic()
            status = "🟢 Active - Auto-discovering"
        else:
            topic = "Not initialized"
            status = "🔴 Inactive"
        
        content = Text()
        content.append("Status: ", style="dim")
        content.append(status + "\n", style="bold")
        content.append("Next Topic: ", style="dim")
        content.append(topic[:40], style="cyan")
        
        return Panel(
            content,
            title="[bold white]🤖 AI AGENT[/]",
            box=box.ROUNDED,
            style="magenta on black",
        )
    
    def create_help_panel(self) -> Panel:
        """Create keyboard shortcuts panel."""
        shortcuts = """[bold cyan]S[/] Search  [bold cyan]R[/] Refresh  [bold cyan]A[/] Analyze  [bold cyan]↑↓[/] Navigate  [bold cyan]Enter[/] Select  [bold cyan]Q[/] Quit"""
        
        return Panel(
            shortcuts,
            box=box.ROUNDED,
            style="dim white on black",
        )
    
    def create_status_bar(self) -> Panel:
        """Create status bar."""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        status_text = Text()
        status_text.append(f"⏰ {now}", style="dim")
        status_text.append(" | ", style="dim")
        status_text.append(self.status, style="bold green" if "Ready" in self.status else "bold yellow")
        
        if self.last_search_time > 0:
            status_text.append(" | ", style="dim")
            status_text.append(f"Last search: {self.last_search_time:.1f}s", style="dim")
        
        return Panel(status_text, box=box.SIMPLE, style="white on black")
    
    def create_layout(self) -> Layout:
        """Create the main layout."""
        layout = Layout()
        
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main", ratio=1),
            Layout(name="help", size=3),
            Layout(name="status", size=3),
        )
        
        layout["main"].split_row(
            Layout(name="left", ratio=2),
            Layout(name="right", size=35),
        )
        
        layout["right"].split_column(
            Layout(name="stats"),
            Layout(name="cache"),
            Layout(name="ai"),
        )
        
        # Update panels
        layout["header"].update(self.create_header())
        layout["left"].update(self.create_articles_panel())
        layout["stats"].update(self.create_stats_panel())
        layout["cache"].update(self.create_cache_panel())
        layout["ai"].update(self.create_ai_panel())
        layout["help"].update(self.create_help_panel())
        layout["status"].update(self.create_status_bar())
        
        return layout
    
    async def initialize(self):
        """Initialize the orchestrator."""
        self.status = "Initializing AI-powered orchestrator..."
        self.orchestrator = TechNewsOrchestrator()
        self.ai_agent = AINewsAgent(self.orchestrator)
        self.status = "Ready - Press S to search"
    
    async def search(self, query: str):
        """Perform a search."""
        self.status = f"Searching: {query}..."
        self.current_query = query
        start = time.time()
        
        try:
            result = await self.orchestrator.search(query)
            self.articles = list(result.articles)
            self.selected_index = 0
            self.last_search_time = time.time() - start
            self.status = f"Found {len(self.articles)} articles"
        except NonTechQueryError as e:
            self.status = f"Rejected: {e.message[:50]}"
            self.articles = []
        except Exception as e:
            self.status = f"Error: {str(e)[:50]}"
    
    async def auto_discover(self):
        """Perform AI auto-discovery."""
        if not self.ai_agent:
            return
        
        self.status = f"AI discovering: {self.ai_agent.get_current_topic()}"
        result = await self.ai_agent.auto_discover()
        
        if result and result.articles:
            self.articles = list(result.articles)
            self.current_query = f"[AI] {self.ai_agent.AUTO_QUERIES[self.ai_agent.current_query_index - 1]}"
            self.selected_index = 0
            self.status = f"AI found {len(self.articles)} articles"
    
    async def run(self):
        """Run the TUI."""
        await self.initialize()
        
        # Initial auto-discovery
        await self.auto_discover()
        
        with Live(self.create_layout(), console=self.console, refresh_per_second=2) as live:
            while self.running:
                # Update display
                live.update(self.create_layout())
                
                # Check for input (non-blocking)
                await asyncio.sleep(0.5)
                
                # Auto-refresh every 60 seconds
                if time.time() - self.metrics["uptime_start"] % 60 < 1:
                    pass  # Could trigger auto-refresh here


async def interactive_mode():
    """Run in interactive command mode."""
    console = Console()
    
    console.print("\n[bold blue]🔍 TECH NEWS SCRAPER v5.0[/] - [italic cyan]AI-Powered Enterprise Edition[/]\n")
    
    with console.status("[bold green]Initializing AI-powered orchestrator..."):
        orchestrator = TechNewsOrchestrator()
        ai_agent = AINewsAgent(orchestrator)
    
    console.print("[green]✓[/] Orchestrator initialized\n")
    
    # Show initial stats
    console.print(Panel(
        "[bold cyan]Commands:[/]\n"
        "  [cyan]search <query>[/] - Search for tech news\n"
        "  [cyan]analyze <url>[/]  - Deep analyze a URL with detailed output\n"
        "  [cyan]url <url>[/]      - Shorthand for analyze\n"
        "  [cyan]auto[/]           - AI auto-discovery\n"
        "  [cyan]stats[/]          - Show statistics\n"
        "  [cyan]latest[/]         - Show latest articles\n"
        "  [cyan]quit[/]           - Exit\n\n"
        "[bold yellow]Flags:[/]\n"
        "  [yellow]--bypass[/]       - Force bypass mode for protected URLs\n"
        "                   Example: analyze https://example.com --bypass",
        title="[bold white]📚 Help[/]",
        box=box.ROUNDED,
    ))
    
    articles = []
    
    while True:
        try:
            command = Prompt.ask("\n[bold blue]🔎[/]")
            
            if not command:
                continue
            
            parts = command.split(maxsplit=1)
            cmd = parts[0].lower()
            args = parts[1] if len(parts) > 1 else ""
            
            if cmd in ("quit", "exit", "q"):
                console.print("\n[bold green]👋 Goodbye![/]")
                break
            
            elif cmd == "search" or cmd == "s":
                if not args:
                    args = Prompt.ask("[dim]Enter search query[/]")
                
                with console.status(f"[bold green]Searching: {args}..."):
                    start = time.time()
                    try:
                        result = await orchestrator.search(args)
                        elapsed = time.time() - start
                        articles = list(result.articles)
                        
                        console.print(f"\n[green]✓[/] Found [bold]{len(articles)}[/] articles in [cyan]{elapsed:.1f}s[/]\n")
                        
                        table = Table(box=box.ROUNDED, title="📰 Results")
                        table.add_column("#", style="dim", width=3)
                        table.add_column("Score", style="green", width=6)
                        table.add_column("Title", style="white", max_width=60)
                        table.add_column("Source", style="cyan", width=15)
                        
                        for i, article in enumerate(articles[:15], 1):
                            score = article.tech_score.score if article.tech_score else 0
                            table.add_row(
                                str(i),
                                f"{score:.2f}",
                                article.title[:55] + "..." if len(article.title) > 55 else article.title,
                                article.source[:12],
                            )
                        
                        console.print(table)
                        
                    except NonTechQueryError as e:
                        console.print(f"\n[red]❌ Rejected:[/] {e.message}\n")
                        console.print("[dim]💡 Suggestions:[/]")
                        for s in orchestrator.suggest_queries(args):
                            console.print(f"  [cyan]• {s}[/]")
            
            elif cmd == "auto" or cmd == "a":
                with console.status("[bold green]AI auto-discovering..."):
                    result = await ai_agent.auto_discover()
                    if result and result.articles:
                        articles = list(result.articles)
                        console.print(f"\n[green]✓[/] AI found [bold]{len(articles)}[/] articles about [cyan]{ai_agent.AUTO_QUERIES[ai_agent.current_query_index - 1]}[/]\n")
                        
                        for i, article in enumerate(articles[:5], 1):
                            console.print(f"  [dim]{i}.[/] [white]{article.title[:60]}[/]")
            
            elif cmd == "stats":
                stats = orchestrator.stats
                
                table = Table(title="📊 Performance Statistics", box=box.ROUNDED)
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="bold white")
                
                table.add_row("Queries Processed", str(stats.get('queries_processed', 0)))
                table.add_row("Queries Rejected", str(stats.get('queries_rejected', 0)))
                table.add_row("Total Articles", str(stats.get('total_articles', 0)))
                table.add_row("Sources Scraped", str(stats.get('sources_scraped', 0)))
                
                scraper_stats = stats.get('scraper_stats', {})
                table.add_row("HTTP Requests", str(scraper_stats.get('requests', 0)))
                table.add_row("Cache Hits", str(scraper_stats.get('cached_hits', 0)))
                
                console.print(table)
            
            elif cmd == "latest" or cmd == "l":
                latest = orchestrator.get_latest_articles(10)
                if latest:
                    console.print("\n[bold]📰 Latest Articles:[/]\n")
                    for i, article in enumerate(latest, 1):
                        score = article.tech_score.score if article.tech_score else 0
                        console.print(f"  [dim]{i}.[/] [green][{score:.2f}][/] [white]{article.title[:60]}[/]")
                else:
                    console.print("[dim]No articles yet. Try searching first.[/]")
            
            elif cmd == "analyze" or cmd == "url":
                if not args:
                    args = Prompt.ask("[dim]Enter URL to analyze[/]")
                
                # Check for --bypass flag
                use_bypass = "--bypass" in args
                url = args.replace("--bypass", "").strip()
                
                bypass_used = None
                content = None
                
                with console.status(f"[bold green]Analyzing: {url}..."):
                    result = None
                    
                    # Try normal analysis first
                    result = await orchestrator.analyze_url(url)
                    
                    # If failed and bypass requested/available, try bypass
                    if (not result or use_bypass) and BYPASS_AVAILABLE:
                        console.print("[yellow]Attempting bypass...[/]")
                        
                        # Try content platform bypass first for Medium, Substack, Ghost
                        content_platform = ContentPlatformBypass()
                        platform = content_platform.detect_platform(url)
                        
                        if platform != ContentPlatform.UNKNOWN:
                            console.print(f"[cyan]Detected {platform.value} platform, using smart bypass...[/]")
                            cp_result = await content_platform.bypass(url, strategy="auto")
                            if cp_result.success:
                                content = cp_result.content
                                bypass_used = f"Content Platform ({platform.value})"
                                console.print(f"[green]✓ Fetched {cp_result.content_length} chars ({cp_result.metadata.get('word_count', 'N/A')} words)[/]")
                            await content_platform.close()
                        
                        # Fall back to generic bypass if content platform bypass failed
                        if not content:
                            anti_bot = AntiBotBypass()
                            paywall = PaywallBypass()
                            
                            bypass_result = await anti_bot.fetch_with_bypass(url)
                            if bypass_result.success:
                                content = bypass_result.content
                                bypass_used = f"Anti-bot ({bypass_result.protection_type.value})"
                                
                                # Check for paywall
                                if paywall.detect_paywall(content):
                                    pw_result = await paywall.bypass_paywall(url)
                                    if pw_result.success:
                                        content = pw_result.content
                                        bypass_used = f"Paywall ({pw_result.method_used.value})"
                            else:
                                pw_result = await paywall.bypass_paywall(url)
                                if pw_result.success:
                                    content = pw_result.content
                                    bypass_used = f"Paywall ({pw_result.method_used.value})"
                        
                        # Re-try analysis
                        if content:
                            result = await orchestrator.analyze_url(url)
                    
                    if result:
                        # Create rich output
                        score = result.article.tech_score.score if result.article.tech_score else 0
                        
                        # Header panel
                        header_content = f"[bold]{result.article.title}[/bold]"
                        console.print(Panel(header_content, title="🔗 URL Analysis", 
                                           border_style="blue", padding=(1, 2)))
                        
                        # Meta info table
                        meta_table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
                        meta_table.add_column(style="cyan")
                        meta_table.add_column(style="white")
                        meta_table.add_row("📊 Tech Score", f"[green]{score:.2f}[/]")
                        meta_table.add_row("📰 Source", result.article.source)
                        meta_table.add_row("⏱️ Reading Time", f"{result.reading_time_min} min")
                        meta_table.add_row("💭 Sentiment", result.sentiment.capitalize())
                        if bypass_used:
                            meta_table.add_row("🔓 Bypass Used", f"[green]{bypass_used}[/]")
                        else:
                            meta_table.add_row("🔓 Bypass", "[dim]Not needed[/]")
                        
                        console.print(Panel(meta_table, title="📋 Details", border_style="dim"))
                        
                        # Summary
                        if result.article.summary:
                            console.print(Panel(result.article.summary, title="📋 AI Summary", 
                                               border_style="cyan", padding=(1, 2)))
                        
                        # Key Points
                        if result.key_points:
                            kp_content = ""
                            for i, point in enumerate(result.key_points[:6], 1):
                                kp_content += f"[cyan]{i}.[/] {point.text}\n"
                            console.print(Panel(kp_content.strip(), title="📌 Key Points", 
                                               border_style="yellow"))
                        
                        # Entities
                        if result.entities:
                            entity_parts = []
                            if result.entities.companies:
                                entity_parts.append(f"[bold]🏢 Companies:[/] {', '.join(result.entities.companies[:5])}")
                            if result.entities.technologies:
                                entity_parts.append(f"[bold]🔧 Technologies:[/] {', '.join(result.entities.technologies[:5])}")
                            if hasattr(result.entities, 'people') and result.entities.people:
                                entity_parts.append(f"[bold]👤 People:[/] {', '.join(result.entities.people[:5])}")
                            
                            if entity_parts:
                                console.print(Panel("\\n".join(entity_parts), title="🏢 Entities", 
                                                   border_style="magenta"))
                        
                        console.print()
                    elif content:
                        # Display raw content if analysis failed
                        console.print(Panel(f"[green]✓ Content retrieved via {bypass_used}[/]", 
                                           title="🔓 Bypass Success", border_style="green"))
                        console.print(Panel(content[:15000] + "..." if len(content) > 15000 else content,
                                           title="📄 Content Preview", border_style="dim"))
                    else:
                        console.print("[red]❌ Could not analyze URL[/]")
                        if BYPASS_AVAILABLE:
                            console.print("[yellow]💡 Tip: Use 'analyze <url> --bypass' to force bypass mode[/]")
            
            
            else:
                # Treat as search query
                with console.status(f"[bold green]Searching: {command}..."):
                    try:
                        result = await orchestrator.search(command)
                        articles = list(result.articles)
                        console.print(f"\n[green]✓[/] Found [bold]{len(articles)}[/] articles\n")
                        
                        for i, article in enumerate(articles[:10], 1):
                            score = article.tech_score.score if article.tech_score else 0
                            console.print(f"  [dim]{i}.[/] [green][{score:.2f}][/] [white]{article.title[:55]}[/]")
                    
                    except NonTechQueryError as e:
                        console.print(f"\n[red]❌ Rejected:[/] {e.message}")
        
        except KeyboardInterrupt:
            console.print("\n\n[bold green]👋 Goodbye![/]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/]")


def main():
    """Main entry point."""
    console.print("\n[bold cyan]Starting Tech News Scraper v5.0...[/]\n")
    asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
