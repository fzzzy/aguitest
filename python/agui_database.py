"""Database module for message persistence"""

import sqlite3
import json
from pathlib import Path
from typing import Optional


# Database setup
DB_PATH = Path(__file__).parent / "var" / "db.sqlite"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def init_db():
    """Initialize the database schema"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Drop the old table if it exists and create new one
    cursor.execute("DROP TABLE IF EXISTS messages")
    cursor.execute("""
        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            previous_id TEXT,
            content TEXT NOT NULL,
            events JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def save_message(content: str, events: list, previous_id: Optional[str] = None) -> str:
    """Save a message to the database and return its UUID"""
    import uuid

    message_id = str(uuid.uuid4())
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    events_json = json.dumps(events)
    cursor.execute(
        "INSERT INTO messages (id, previous_id, content, events) VALUES (?, ?, ?, ?)",
        (message_id, previous_id, content, events_json),
    )
    conn.commit()
    conn.close()
    return message_id


def get_message(message_id: str) -> Optional[dict]:
    """Retrieve a message by its ID"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def reconstruct_history(message_id: str) -> list[dict]:
    """Reconstruct chat history by following the chain of previous_id links"""
    history = []
    current_id = message_id

    while current_id:
        message = get_message(current_id)
        if not message:
            break
        history.append(message)
        current_id = message["previous_id"]

    # Reverse to get chronological order (oldest first)
    history.reverse()
    return history
