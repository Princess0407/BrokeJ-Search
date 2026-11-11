from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from brokej_search.discovery.service import DiscoveryService


class DiscoveryScheduler:
    def __init__(
        self, service: DiscoveryService, interval_minutes: int, timezone: str = "UTC"
    ) -> None:
        self.service = service
        self.interval_minutes = interval_minutes
        self.scheduler = BlockingScheduler(timezone=timezone)

    def _run(self) -> None:
        try:
            asyncio.run(self._run_async())
        except Exception:
            logging.getLogger(__name__).exception("Scheduled discovery run failed")

    async def _run_async(self) -> None:
        await self.service.run_due_retries()
        await self.service.run(trigger="scheduled")

    def start(self) -> None:
        self.scheduler.add_job(
            self._run,
            "interval",
            minutes=self.interval_minutes,
            id="daily-discovery",
            max_instances=1,
            coalesce=True,
        )
        self._run()
        self.scheduler.start()
