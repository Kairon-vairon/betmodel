"""The worker process.

Milestone 1 jobs: heartbeat, drawdown stop, signal expiry. Data ingestion (Milestone 2),
the value finder run (M3), alerts (M4) and settlement (M5) are added here as they land.
"""

from __future__ import annotations

import logging
import signal
from collections.abc import Callable
from datetime import UTC, datetime
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy.orm import Session, sessionmaker

from edgewise import __version__
from edgewise.config import Settings, get_settings
from edgewise.db.models import WorkerHeartbeat
from edgewise.db.session import make_engine, make_session_factory, transaction
from edgewise.domain.limits import DEFAULT_LIMITS
from edgewise.services import limits as limits_service
from edgewise.services import portfolio, signals

log = logging.getLogger("edgewise.worker")

Clock = Callable[[], datetime]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Worker:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        *,
        clock: Clock = _utcnow,
        name: str | None = None,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.clock = clock
        # One worker per stack; a stable name means redeploys update the same heartbeat row.
        self.name = name or "worker"
        self.started_at = clock()

    def heartbeat(self) -> None:
        now = self.clock()
        with transaction(self.session_factory) as session:
            beat = session.get(WorkerHeartbeat, self.name)
            if beat is None:
                beat = WorkerHeartbeat(
                    worker=self.name,
                    started_at=self.started_at,
                    last_beat_at=now,
                    version=__version__,
                    details={},
                )
                session.add(beat)
            beat.last_beat_at = now
            beat.version = __version__
            beat.details = {
                "stack": self.settings.app_env.value,
                "alerts": self.settings.can_send_alerts,
            }

    def safety_checks(self) -> None:
        """Drawdown stop first, then expire signals that are no longer valid."""
        now = self.clock()
        with transaction(self.session_factory) as session:
            try:
                limits = limits_service.current_limits(session)
            except ValueError:
                log.error("Stored safety limits are invalid; using defaults for expiry checks")
                limits = DEFAULT_LIMITS
            if portfolio.enforce_drawdown_stop(session, now=now, limits=limits):
                log.warning("Drawdown stop reached: alerts paused until the owner resumes them")
            expired = signals.expire_due(session, now=now, limits=limits)
            if expired:
                log.info("Expired %d signal(s)", len(expired))

    def run_job(self, job: Callable[[], None]) -> None:
        try:
            job()
        except Exception:
            log.exception("Job %s failed", getattr(job, "__name__", job))


def build_scheduler(worker: Worker) -> BlockingScheduler:
    scheduler = BlockingScheduler(
        timezone=UTC,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 30},
    )
    scheduler.add_job(
        worker.run_job,
        "interval",
        seconds=30,
        args=[worker.heartbeat],
        name="heartbeat",
        id="heartbeat",
        next_run_time=worker.clock(),
    )
    scheduler.add_job(
        worker.run_job,
        "interval",
        seconds=60,
        args=[worker.safety_checks],
        name="safety_checks",
        id="safety_checks",
        next_run_time=worker.clock(),
    )
    return scheduler


def run_worker() -> None:
    settings = get_settings()
    logging.getLogger("apscheduler").setLevel(logging.WARNING)  # no line per job run
    worker = Worker(settings, make_session_factory(make_engine(settings.database_url)))
    scheduler = build_scheduler(worker)

    def stop(signum: int, frame: FrameType | None) -> None:
        log.info("Stopping worker (signal %s)", signum)
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGTERM, stop)
    log.info(
        "Worker %s starting: stack=%s, alerts %s",
        worker.name,
        settings.app_env.value,
        "enabled" if settings.can_send_alerts else "DISABLED",
    )
    scheduler.start()
