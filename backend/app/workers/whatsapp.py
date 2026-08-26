"""WhatsApp extraction worker.

    python -m app.workers.whatsapp            # run continuously
    python -m app.workers.whatsapp --once     # drain the backlog and exit
    python -m app.workers.whatsapp --dry-run  # show what would be extracted

ARCHITECTURE.md asks for a task queue here. This is a database-backed queue and
a polling worker rather than Celery or RQ, deliberately:

* the queue table has to exist anyway -- the owner's feed screen shows per
  message status, retry counts and errors, which means the job state is
  product data, not just infrastructure state;
* it removes Redis and a broker from a deployment that config.py already
  describes as a single process for one small brokerage;
* claiming uses ``SELECT ... FOR UPDATE SKIP LOCKED``, so scaling out is
  "start a second worker", not a rewrite.

If throughput ever outgrows this, the swap is confined to :func:`main` --
``run_batch`` is already the unit of work a Celery task would wrap.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from types import FrameType

from app.db import SessionLocal, system_scope
from app.extraction import Extractor, ExtractionInput, ExtractionUnavailable
from app.heartbeat import describe_process, touch
from app.ingestion import BATCH_SIZE, IngestionStats, pending_count, run_batch
from app.models import EXTRACTION_WORKER, INGEST_PENDING, WhatsAppMessage

log = logging.getLogger("balaji.worker")

# How long to wait when the queue is empty. Group traffic is bursty and nothing
# here is latency-critical -- a listing that reaches inventory five seconds
# later is indistinguishable to an agent searching it.
IDLE_SLEEP_SECONDS = 5.0

# Backoff after a failed batch, so an API outage does not turn into a tight
# retry loop against a service that is already unhappy.
ERROR_SLEEP_SECONDS = 30.0

_shutdown = False


def _handle_signal(signum: int, _frame: FrameType | None) -> None:
    """Finish the batch in flight, then stop.

    Killing a worker mid-batch is safe (the transaction rolls back and the
    messages return to pending), but draining cleanly avoids inflating
    `attempts` on messages that were never actually the problem.
    """
    global _shutdown
    _shutdown = True
    log.info("received signal %s, finishing current batch then exiting", signum)


def request_worker_shutdown() -> None:
    """Ask the loop to stop at its next batch boundary.

    The signal handlers cannot be used when the loop runs inside the API: those
    belong to uvicorn, and a worker thread cannot install its own. This is the
    same flag by another door.
    """
    global _shutdown
    _shutdown = True


def run_forever(extractor: Extractor, batch_size: int, kind: str = "standalone") -> None:
    totals = IngestionStats()
    note = describe_process(kind)
    while not _shutdown:
        db = SessionLocal()
        try:
            # Before the batch, not after: a worker stuck on a slow or hanging
            # extraction call is still running, and going quiet mid-batch would
            # report it as dead at exactly the moment someone is looking to
            # find out why nothing is moving.
            touch(db, EXTRACTION_WORKER, note)
            stats = run_batch(db, extractor, limit=batch_size)
        except Exception:
            log.exception("worker loop error")
            db.rollback()
            time.sleep(ERROR_SLEEP_SECONDS)
            continue
        finally:
            db.close()

        _accumulate(totals, stats)
        if stats.messages_processed == 0 and stats.failures == 0:
            time.sleep(IDLE_SLEEP_SECONDS)
        elif stats.failures:
            time.sleep(ERROR_SLEEP_SECONDS)

    log.info("worker stopped. totals: %s", totals.as_dict())


def run_once(extractor: Extractor, batch_size: int) -> IngestionStats:
    """Drain the backlog, then return. Used by --once and by tests."""
    totals = IngestionStats()
    while not _shutdown:
        db = SessionLocal()
        try:
            stats = run_batch(db, extractor, limit=batch_size)
        finally:
            db.close()
        if stats.messages_processed == 0 and stats.failures == 0:
            break
        _accumulate(totals, stats)
        if stats.failures:
            break
    return totals


def _accumulate(totals: IngestionStats, stats: IngestionStats) -> None:
    totals.messages_processed += stats.messages_processed
    totals.listings_found += stats.listings_found
    totals.properties_created += stats.properties_created
    totals.duplicates_merged += stats.duplicates_merged
    totals.not_listings += stats.not_listings
    totals.failures += stats.failures


def dry_run(extractor: Extractor, batch_size: int) -> None:
    """Extract pending messages and print the result without writing anything.

    The point of a dry run here is prompt work: it shows exactly what the model
    made of real group traffic, without creating inventory that then has to be
    cleaned up.
    """
    from app.ingestion import build_facts

    db = SessionLocal()
    try:
        with system_scope():
            messages = (
                db.execute(
                    WhatsAppMessage.__table__.select()
                    .where(WhatsAppMessage.status == INGEST_PENDING)
                    .order_by(WhatsAppMessage.received_at.asc())
                    .limit(batch_size)
                )
                .mappings()
                .all()
            )
        if not messages:
            print("Nothing pending.")
            return

        items = [
            ExtractionInput(ref=str(m["id"]), body=m["body"], sender_name=m["sender_name"])
            for m in messages
        ]
        for result in extractor.extract(items):
            body = next(
                (m["body"] for m in messages if str(m["id"]) == result.message_ref), ""
            )
            print("=" * 72)
            print(body.strip()[:400])
            print(f"-> is_listing={result.is_listing} ({result.reason})")
            for listing in result.listings:
                facts = build_facts(listing)
                if facts is None:
                    print("   [dropped: no locality or no listing type]")
                    continue
                print(
                    f"   [{facts.listing_type}] {facts.title}\n"
                    f"       building={facts.building!r} location={facts.location!r} "
                    f"bhk={facts.bhk} price={facts.price} area={facts.area_sqft} "
                    f"confidence={facts.confidence}"
                )
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once", action="store_true", help="drain the backlog and exit"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="extract and print without writing anything",
    )
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    extractor = Extractor()
    try:
        extractor._ensure_client()
    except ExtractionUnavailable as exc:
        # Fail on startup with an actionable message rather than burning
        # through the backlog marking everything failed.
        print(f"Cannot start extraction worker: {exc}", file=sys.stderr)
        return 2

    log.info(
        "worker starting (model=%s effort=%s batch=%d), %d message(s) pending",
        extractor.model,
        extractor.effort,
        args.batch_size,
        _safe_pending(),
    )

    if args.dry_run:
        dry_run(extractor, args.batch_size)
        return 0
    if args.once:
        totals = run_once(extractor, args.batch_size)
        print(totals.as_dict())
        return 0
    run_forever(extractor, args.batch_size)
    return 0


def _safe_pending() -> int:
    db = SessionLocal()
    try:
        return pending_count(db)
    except Exception:
        return -1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
