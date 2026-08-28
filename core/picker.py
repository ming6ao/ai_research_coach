from typing import Optional

from core.session import Session


def next_task(session: Session) -> Optional[dict]:
    if session.index >= len(session.tasks):
        return None
    return session.tasks[session.index]
