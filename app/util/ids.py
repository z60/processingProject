"""ID 生成。"""

from __future__ import annotations

import uuid
from datetime import datetime


def new_trace_id() -> str:
    return f"t-{uuid.uuid4().hex[:12]}"


def new_session_id() -> str:
    return f"s-{uuid.uuid4().hex[:12]}"


def new_ticket_id() -> str:
    return f"TK{datetime.now():%Y%m%d}{uuid.uuid4().hex[:6].upper()}"


def new_handoff_id() -> str:
    return f"H-{datetime.now():%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
