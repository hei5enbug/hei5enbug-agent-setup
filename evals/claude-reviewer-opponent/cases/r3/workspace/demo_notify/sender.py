"""Webhook sender of demo-notify."""

from __future__ import annotations

import logging
import sqlite3
import time
import urllib.error
import urllib.request

log = logging.getLogger("demo_notify")


def log_attempt(db: sqlite3.Connection, event_id: str, outcome: str) -> None:
    db.execute(
        "INSERT INTO delivery_log (event_id, at, outcome) VALUES (?, ?, ?)",
        (event_id, time.time(), outcome),
    )
    db.commit()


def deliver(db: sqlite3.Connection, event_id: str, url: str, body: bytes) -> bool:
    request = urllib.request.Request(url, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            log_attempt(db, event_id, str(response.status))
            return True
    except urllib.error.HTTPError as error:
        log_attempt(db, event_id, str(error.code))
        log.warning("delivery of %s failed with %s", event_id, error.code)
    except OSError as error:
        log_attempt(db, event_id, repr(error))
        log.warning("delivery of %s failed: %s", event_id, error)
    return False
