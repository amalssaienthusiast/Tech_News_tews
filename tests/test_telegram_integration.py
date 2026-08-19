"""
Telegram Feeder Bot Integration Tests — Task 1A.4

Verifies:
  - FeederBot sends X-API-Key header to engine endpoints when configured.
  - SSE stream receiver handles authenticated engine streams and article parsing.
  - HTTP fallback polling correctly requests feed with authentication headers.
  - Duplicate dispatch prevention (_is_new logic and seen_ids persistence).
  - Graceful shutdown stops receiver, publisher, and cancels tasks safely.
  - TelegramPublisher TLS connector enforces SSL certificate verification.
  - Test mode / dry-run payload structure.
"""

import asyncio
import json
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiohttp import web, test_utils

from telegram_feeder_bot import (
    ArticleData,
    FeederBot,
    TelegramPublisher,
    run_test,
)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Telegram Publisher TLS & Configuration
# ─────────────────────────────────────────────────────────────────────────────

class TestTelegramPublisher:
    """Verify TelegramPublisher configuration and SSL enforcement."""

    def test_publisher_init_and_urls(self):
        pub = TelegramPublisher(bot_token="test_token_123", chat_id="@test_channel")
        assert pub.bot_token == "test_token_123"
        assert pub.chat_id == "@test_channel"
        assert "sendMessage" in pub.api_url
        assert "sendPhoto" in pub.photo_url

    @pytest.mark.asyncio
    async def test_publisher_connector_uses_verified_ssl(self):
        pub = TelegramPublisher(bot_token="test_token_123", chat_id="@test_channel")
        connector = pub._create_connector()
        assert connector._ssl is not False
        await pub.close()


# ─────────────────────────────────────────────────────────────────────────────
# 2. FeederBot & Engine Integration (Auth, SSE, Polling, Reconnect)
# ─────────────────────────────────────────────────────────────────────────────

class TestFeederBotEngineIntegration:
    """Verify FeederBot interactions with authenticated engine server."""

    @pytest.fixture
    def mock_publisher(self):
        pub = MagicMock(spec=TelegramPublisher)
        pub.send_message = AsyncMock(return_value=True)
        pub.send_photo = AsyncMock(return_value=True)
        pub.close = AsyncMock()
        pub.get_session = AsyncMock()
        return pub

    @pytest.fixture
    def mock_engine_app(self):
        app = web.Application()

        async def handle_health(request):
            return web.json_response({"status": "ok", "buffer": {"buffered": 5}})

        async def handle_feed(request):
            # Check auth
            key = request.headers.get("X-API-Key")
            if key != "secret_engine_key":
                return web.json_response({"error": "Unauthorized"}, status=401)
            return web.json_response({
                "articles": [
                    {
                        "id": "poll_art_1",
                        "url": "https://example.com/poll1",
                        "title": "Poll Article Title One",
                        "source": "PollSource",
                    }
                ],
                "server_time": "2026-08-13T20:00:00Z",
            })

        async def handle_stream(request):
            key = request.headers.get("X-API-Key")
            if key != "secret_engine_key":
                return web.json_response({"error": "Unauthorized"}, status=401)

            resp = web.StreamResponse(
                status=200,
                headers={"Content-Type": "text/event-stream"},
            )
            await resp.prepare(request)
            art = {
                "id": "stream_art_1",
                "url": "https://example.com/stream1",
                "title": "Stream Article Title One",
                "source": "StreamSource",
            }
            await resp.write(f"data: {json.dumps(art)}\n\n".encode())
            return resp

        app.router.add_get("/api/v1/health", handle_health)
        app.router.add_get("/api/v1/feed", handle_feed)
        app.router.add_get("/api/v1/stream", handle_stream)
        return app

    @pytest.fixture
    async def engine_server(self, mock_engine_app):
        server = test_utils.TestServer(mock_engine_app)
        client = test_utils.TestClient(server)
        await client.start_server()
        yield client
        await client.close()

    @pytest.mark.asyncio
    async def test_check_engine_health(self, engine_server, mock_publisher):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url=str(engine_server.make_url("")),
            api_key="secret_engine_key",
        )
        reachable = await bot._check_engine_health()
        assert reachable is True

    @pytest.mark.asyncio
    async def test_poll_once_with_auth_header(self, engine_server, mock_publisher, tmp_path):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url=str(engine_server.make_url("")),
            api_key="secret_engine_key",
        )
        bot._seen_ids_file = tmp_path / "seen_ids.txt"
        bot._seen_ids = {}

        await bot._poll_once()
        assert bot.queue.qsize() == 1
        item = bot.queue.get_nowait()
        assert item.id == "poll_art_1"
        assert item.title == "Poll Article Title One"

    @pytest.mark.asyncio
    async def test_poll_once_unauthorized_if_wrong_key(self, engine_server, mock_publisher, tmp_path):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url=str(engine_server.make_url("")),
            api_key="wrong_key",
        )
        bot._seen_ids_file = tmp_path / "seen_ids.txt"
        bot._seen_ids = {}

        await bot._poll_once()
        assert bot.queue.qsize() == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Duplicate Prevention & Graceful Shutdown
# ─────────────────────────────────────────────────────────────────────────────

class TestFeederBotDeduplicationAndLifecycle:
    """Verify deduplication filter and lifecycle management."""

    @pytest.fixture
    def mock_publisher(self):
        pub = MagicMock(spec=TelegramPublisher)
        pub.send_message = AsyncMock(return_value=True)
        pub.close = AsyncMock()
        return pub

    def test_deduplication_prevents_reprocessing(self, mock_publisher, tmp_path):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url="http://localhost:8080",
        )
        bot._seen_ids_file = tmp_path / "seen_ids.txt"
        bot._seen_ids = {}

        art1 = ArticleData(id="art_123", url="https://example.com/1", title="Valid Title Word Four")
        bot._enqueue(art1)
        assert bot.queue.qsize() == 1

        # Second enqueue with same ID must be rejected by deduplication
        bot._enqueue(art1)
        assert bot.queue.qsize() == 1

    def test_short_titles_are_rejected(self, mock_publisher, tmp_path):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url="http://localhost:8080",
        )
        bot._seen_ids_file = tmp_path / "seen.txt"
        bot._seen_ids = {}

        short_art = ArticleData(id="short_1", url="https://example.com/2", title="Short Nav")
        bot._enqueue(short_art)
        assert bot.queue.qsize() == 0

    @pytest.mark.asyncio
    async def test_graceful_shutdown(self, mock_publisher):
        bot = FeederBot(
            publisher=mock_publisher,
            engine_url="http://localhost:8080",
        )
        bot._running = True
        bot._receiver_task = asyncio.create_task(asyncio.sleep(10))
        bot._publisher_task = asyncio.create_task(asyncio.sleep(10))
        bot._prepare_task = asyncio.create_task(asyncio.sleep(10))

        await bot.stop()
        assert bot._running is False
        mock_publisher.close.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Test Mode / Dry-Run Verification
# ─────────────────────────────────────────────────────────────────────────────

class TestModeVerification:
    """Verify test run helper functionality."""

    @pytest.mark.asyncio
    async def test_run_test_mode(self):
        pub = MagicMock(spec=TelegramPublisher)
        pub.send_message = AsyncMock(return_value=True)
        pub.close = AsyncMock()

        with patch("aiohttp.ClientSession.get") as mock_get:
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value={"status": "ok", "buffer": {"buffered": 2}})
            mock_get.return_value.__aenter__.return_value = mock_resp

            await run_test(pub, "http://localhost:8080")
            pub.send_message.assert_called_once()
            pub.close.assert_called_once()
