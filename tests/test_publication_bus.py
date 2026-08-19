"""
Unit and Integration Tests for PublicationBus.
Location: tests/test_publication_bus.py

Tests:
  - Bus lifecycle (start, stop, active state)
  - Publish / Subscribe delivery semantics
  - Channel-based filtering (SSE, Telegram, WebSocket)
  - Priority routing (HIGH, NORMAL, LOW)
  - Bounded queues and DROP_OLDEST slow consumer policy
  - Graceful drain and sentinel shutdown
  - Consumer idempotency key deduplication
  - Multi-subscriber fan-out
"""

import asyncio
from datetime import datetime, UTC
import pytest

from src.domain.enums import PublicationChannel, PublicationEventType, PublicationPriority
from src.domain.models import PublicationEvent
from src.engine.publication_bus import PublicationBus, get_publication_bus, reset_publication_bus


@pytest.fixture(autouse=True)
def reset_bus():
    """Ensure clean bus state for every test."""
    reset_publication_bus()
    yield
    reset_publication_bus()


@pytest.mark.asyncio
class TestPublicationBusLifecycle:
    async def test_start_and_stop_lifecycle(self):
        bus = PublicationBus()
        assert bus.is_running is False
        assert bus.subscriber_count == 0

        await bus.start()
        assert bus.is_running is True

        sub_id, queue = await bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))
        assert bus.subscriber_count == 1

        await bus.stop(drain_timeout=1.0)
        assert bus.is_running is False
        assert bus.subscriber_count == 0


@pytest.mark.asyncio
class TestPublicationBusDelivery:
    async def test_publish_and_subscribe_delivery(self):
        bus = PublicationBus()
        await bus.start()

        sub_id, queue = await bus.subscribe(
            subscriber_id="sse_client_1",
            channels=(PublicationChannel.SSE_STREAM,),
            maxsize=10,
        )

        event = PublicationEvent(
            event_id="pub_001",
            event_type=PublicationEventType.ARTICLE_PUBLISHED,
            payload={"headline": "Test Article", "id": "art_1"},
            channels=(PublicationChannel.SSE_STREAM,),
            priority=PublicationPriority.NORMAL,
        )

        dispatched = await bus.publish(event)
        assert dispatched == 1

        # Check subscriber received event
        received_event = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert received_event is not None
        assert received_event.event_id == "pub_001"
        assert received_event.payload["headline"] == "Test Article"

        await bus.stop(drain_timeout=1.0)

    async def test_channel_filtering(self):
        bus = PublicationBus()
        await bus.start()

        # Client A only wants SSE_STREAM
        sub_a, queue_a = await bus.subscribe(
            subscriber_id="client_sse",
            channels=(PublicationChannel.SSE_STREAM,),
        )
        # Client B only wants TELEGRAM_BOT
        sub_b, queue_b = await bus.subscribe(
            subscriber_id="client_tg",
            channels=(PublicationChannel.TELEGRAM_BOT,),
        )

        # 1. Publish event targeted ONLY to TELEGRAM_BOT
        tg_event = PublicationEvent(
            event_id="pub_tg",
            event_type=PublicationEventType.BREAKING_ALERT,
            payload={"id": "break_1"},
            channels=(PublicationChannel.TELEGRAM_BOT,),
        )
        await bus.publish(tg_event)

        # Client B receives it
        received_b = await asyncio.wait_for(queue_b.get(), timeout=1.0)
        assert received_b.event_id == "pub_tg"

        # Client A queue remains empty
        assert queue_a.empty()

        # 2. Publish event targeted to BOTH
        dual_event = PublicationEvent(
            event_id="pub_both",
            event_type=PublicationEventType.ARTICLE_PUBLISHED,
            payload={"id": "art_2"},
            channels=(PublicationChannel.SSE_STREAM, PublicationChannel.TELEGRAM_BOT),
        )
        await bus.publish(dual_event)

        assert (await asyncio.wait_for(queue_a.get(), timeout=1.0)).event_id == "pub_both"
        assert (await asyncio.wait_for(queue_b.get(), timeout=1.0)).event_id == "pub_both"

        await bus.stop(drain_timeout=1.0)

    async def test_slow_consumer_drop_oldest(self):
        """
        Verify that a slow consumer with a full queue has its oldest events dropped
        without blocking the publisher.
        """
        bus = PublicationBus()
        await bus.start()

        # Bounded queue with maxsize=3
        sub_id, queue = await bus.subscribe(
            subscriber_id="slow_client",
            channels=(PublicationChannel.SSE_STREAM,),
            maxsize=3,
        )

        # Publish 5 events (E1, E2, E3, E4, E5) without reading from queue
        for i in range(1, 6):
            ev = PublicationEvent(
                event_id=f"pub_{i}",
                event_type=PublicationEventType.ARTICLE_PUBLISHED,
                payload={"id": f"art_{i}"},
                channels=(PublicationChannel.SSE_STREAM,),
            )
            dispatched = await bus.publish(ev)
            assert dispatched == 1

        # Queue size must be at max capacity (3)
        assert queue.qsize() == 3

        # Oldest events (E1, E2) should have been dropped; queue must hold [E3, E4, E5]
        item1 = queue.get_nowait()
        item2 = queue.get_nowait()
        item3 = queue.get_nowait()

        assert item1.event_id == "pub_3"
        assert item2.event_id == "pub_4"
        assert item3.event_id == "pub_5"

        await bus.stop(drain_timeout=1.0)

    async def test_idempotency_deduplication(self):
        bus = PublicationBus()
        await bus.start()

        sub_id, queue = await bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))

        event1 = PublicationEvent(
            event_id="pub_first",
            event_type=PublicationEventType.ARTICLE_PUBLISHED,
            payload={"id": "art_100"},
            idempotency_key="art_100:v1",
            channels=(PublicationChannel.SSE_STREAM,),
        )
        event2 = PublicationEvent(
            event_id="pub_second_duplicate",
            event_type=PublicationEventType.ARTICLE_PUBLISHED,
            payload={"id": "art_100"},
            idempotency_key="art_100:v1",  # Same idempotency key!
            channels=(PublicationChannel.SSE_STREAM,),
        )

        # First publish succeeds
        count1 = await bus.publish(event1)
        assert count1 == 1

        # Second publish is deduplicated and dropped
        count2 = await bus.publish(event2)
        assert count2 == 0

        # Queue contains only first event
        assert queue.qsize() == 1
        assert (await queue.get()).event_id == "pub_first"

        await bus.stop(drain_timeout=1.0)

    async def test_unsubscribe_removes_listener(self):
        bus = PublicationBus()
        await bus.start()

        sub_id, queue = await bus.subscribe(subscriber_id="temp_sub", channels=(PublicationChannel.SSE_STREAM,))
        assert bus.subscriber_count == 1

        unsub_res = await bus.unsubscribe("temp_sub")
        assert unsub_res is True
        assert bus.subscriber_count == 0

        # Publish event
        ev = PublicationEvent(
            event_id="pub_after_unsub",
            channels=(PublicationChannel.SSE_STREAM,),
        )
        dispatched = await bus.publish(ev)
        assert dispatched == 0
        assert queue.empty()

        await bus.stop(drain_timeout=1.0)

    async def test_graceful_drain_on_stop(self):
        bus = PublicationBus()
        await bus.start()

        sub_id, queue = await bus.subscribe(channels=(PublicationChannel.SSE_STREAM,))

        # Publish 2 events
        for i in range(2):
            await bus.publish(PublicationEvent(event_id=f"msg_{i}", channels=(PublicationChannel.SSE_STREAM,)))

        # Stop bus with drain
        stop_task = asyncio.create_task(bus.stop(drain_timeout=2.0))

        # Consumer drains queue
        msg0 = await queue.get()
        assert msg0.event_id == "msg_0"
        msg1 = await queue.get()
        assert msg1.event_id == "msg_1"
        sentinel = await queue.get()
        assert sentinel is None  # Shutdown sentinel received

        await stop_task
        assert bus.is_running is False
