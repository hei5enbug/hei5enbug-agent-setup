"""Append-only log of every stock movement."""

from __future__ import annotations

from .clock import Clock
from .models import AuditEntry, Database

KIND_RECEIVE = "receive"
KIND_ADJUST = "adjust"
KIND_ALLOCATE = "allocate"
KIND_RELEASE = "release"


def record(
    db: Database,
    clock: Clock,
    *,
    kind: str,
    sku: str,
    warehouse: str,
    delta: int,
    reference: str,
) -> AuditEntry:
    entry = AuditEntry(at=clock(), kind=kind, sku=sku, warehouse=warehouse, delta=delta, reference=reference)
    db.audit.append(entry)
    return entry


def entries_for(db: Database, *, sku: str | None = None, reference: str | None = None) -> list[AuditEntry]:
    return [
        entry
        for entry in db.audit
        if (sku is None or entry.sku == sku) and (reference is None or entry.reference == reference)
    ]


def net_movement(db: Database, sku: str) -> int:
    return sum(entry.delta for entry in db.audit if entry.sku == sku)
