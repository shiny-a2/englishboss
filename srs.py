from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Leitner configuration (can be tuned per user later)
BOX_INTERVALS_DAYS = {1: 0, 2: 1, 3: 3, 4: 7, 5: 14}

@dataclass
class ReviewOutcome:
    new_box: int
    next_due: datetime

def schedule_next(box: int, success: bool, now: datetime | None = None) -> ReviewOutcome:
    """Return next box and due date given result."""
    now = now or datetime.now(timezone.utc)
    if success:
        new_box = min(box + 1, 5)
    else:
        new_box = 1
    days = BOX_INTERVALS_DAYS.get(new_box, 7)
    return ReviewOutcome(new_box=new_box, next_due=now + timedelta(days=days))
