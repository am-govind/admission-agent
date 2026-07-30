"""Ingestion orchestrator.

One source per run, chosen explicitly by DATA_SOURCE. There is no fallback chain: if
the configured source fails, the refresh fails and is recorded as failed, leaving the
previous good data in place. The old behaviour — try Excel, then Sheets, then
synthesise random data, swallowing every exception on the way — could not be
distinguished from success.

Tables are replaced, not versioned; trends come from the joining_date column.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from dataclasses import dataclass, field

from ..core import appdb
from ..core.config import settings
from . import availability, tabular
from .schema import ANALYTICS_TABLES, TABLE_RD26
from .sources import SourceError, get_source

log = logging.getLogger(__name__)


@dataclass
class RefreshResult:
    source: str
    counts: dict[str, int] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    failed: dict[str, str] = field(default_factory=dict)

    @property
    def status(self) -> str:
        if self.failed or self.skipped:
            return "partial"
        return "success"

    @property
    def note(self) -> str | None:
        parts = [f"{t}: {why}" for t, why in {**self.skipped, **self.failed}.items()]
        return "; ".join(parts) if parts else None


def refresh(source_name: str | None = None) -> RefreshResult:
    """Load every available table from the configured source.

    Raises if the source cannot be built, or if the primary rd26 table fails. A
    secondary table that is absent or malformed is recorded and skipped so the rest
    of the app keeps working, with those metrics reporting themselves unavailable.
    """
    source = get_source(source_name)
    result = RefreshResult(source=source.name)
    try:
        for table in ANALYTICS_TABLES:
            try:
                read = source.read_table(table)
            except SourceError:
                raise
            if read is None:
                result.skipped[table] = "source tab not present"
                log.warning("%s: no source tab, leaving previous data in place", table)
                continue
            try:
                result.counts[table] = tabular.load_table(table, read.header, read.windows)
            except Exception as e:  # noqa: BLE001 - one bad tab must not lose the others
                if table == TABLE_RD26:
                    raise
                result.failed[table] = str(e)
                log.error("%s: load failed: %s", table, e)
    finally:
        source.close()

    if TABLE_RD26 not in result.counts and not availability.is_available(TABLE_RD26):
        raise SourceError(
            f"Source {source.name!r} produced no {TABLE_RD26} data, which every metric "
            "depends on. Check DATA_SOURCE and the tab names.")
    return result


def run_refresh(trigger: str = "manual", source_name: str | None = None) -> dict:
    """Audited refresh: records the attempt, alerts on failure, never raises."""
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    started = dt.datetime.now(dt.timezone.utc)
    source = (source_name or settings.data_source).strip().lower()

    appdb.execute(
        "INSERT INTO refresh_runs (run_id, trigger, source, started_at, status) "
        "VALUES (?, ?, ?, ?, ?)",
        [run_id, trigger, source, started.isoformat(), "running"])
    appdb.set_meta(availability.META_LAST_ATTEMPT, started.isoformat())

    try:
        result = refresh(source_name)
    except Exception as e:  # noqa: BLE001 - the scheduler must survive any failure
        finished = dt.datetime.now(dt.timezone.utc)
        message = f"{type(e).__name__}: {e}"
        log.exception("Refresh %s failed", run_id)
        appdb.execute(
            "UPDATE refresh_runs SET finished_at = ?, status = ?, error = ? WHERE run_id = ?",
            [finished.isoformat(), "failed", message, run_id])
        appdb.set_meta(availability.META_LAST_ERROR, message)
        _alert(f"Data refresh failed ({trigger})", message)
        return {"runId": run_id, "ok": False, "status": "failed", "error": message,
                "counts": {}}

    finished = dt.datetime.now(dt.timezone.utc)
    counts_json = json.dumps(result.counts)
    appdb.execute(
        "UPDATE refresh_runs SET finished_at = ?, status = ?, row_counts = ?, error = ? "
        "WHERE run_id = ?",
        [finished.isoformat(), result.status, counts_json, result.note, run_id])
    appdb.set_meta(availability.META_LAST_SUCCESS, finished.isoformat())
    appdb.set_meta(availability.META_SOURCE, result.source)
    appdb.set_meta(availability.META_ROW_COUNTS, counts_json)
    appdb.set_meta(availability.META_LAST_ERROR, result.note or "")
    availability.statuses(refresh=True)

    log.info("Refresh %s %s from %s: %s", run_id, result.status, result.source,
             result.counts)
    if result.failed:
        _alert("Data refresh partially failed", result.note or "")
    return {"runId": run_id, "ok": True, "status": result.status,
            "counts": result.counts, "skipped": result.skipped, "failed": result.failed}


def _alert(subject: str, body: str) -> None:
    if not settings.alert_email_enabled or not settings.alert_email_to:
        return
    import smtplib
    from email.message import EmailMessage

    msg = EmailMessage()
    msg["Subject"] = f"[admission-agent] {subject}"
    msg["From"] = settings.smtp_from
    msg["To"] = settings.alert_email_to
    msg.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            if settings.smtp_user:
                smtp.starttls()
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
    except Exception as e:  # noqa: BLE001 - a broken mailer must not mask the real error
        log.error("Could not send alert email: %s", e)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    print(json.dumps(run_refresh(trigger="cli"), indent=2))
