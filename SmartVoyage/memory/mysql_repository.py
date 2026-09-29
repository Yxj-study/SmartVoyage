from __future__ import annotations

import json
from collections.abc import Callable

from SmartVoyage.memory.models import PreferenceCandidate, PreferenceRecord
from SmartVoyage.memory.policy import validate_candidate
from SmartVoyage.memory.repository import (
    validate_identity,
    validate_preference_key,
)


class MySqlPreferenceRepository:
    def __init__(self, connection_factory: Callable):
        self._connection_factory = connection_factory

    def list_active(self, user_id: str) -> list[PreferenceRecord]:
        validate_identity(user_id)
        connection = self._connection_factory()
        cursor = connection.cursor(dictionary=True)
        try:
            cursor.execute(
                """
                SELECT user_id, preference_key, value_json, confidence,
                       source_session_id, source_text, status, created_at, updated_at
                FROM travel_user_preferences
                WHERE user_id = %s AND status = %s
                ORDER BY preference_key
                """,
                (user_id, "active"),
            )
            records = []
            for row in cursor.fetchall():
                item = dict(row)
                raw_value = item.pop("value_json")
                item["value"] = (
                    json.loads(raw_value) if isinstance(raw_value, str) else raw_value
                )
                records.append(PreferenceRecord.model_validate(item))
            return records
        finally:
            cursor.close()
            connection.close()

    def upsert(
        self,
        user_id: str,
        session_id: str,
        candidate: PreferenceCandidate,
    ) -> PreferenceRecord:
        validate_identity(user_id, session_id)
        candidate = validate_candidate(candidate)
        if candidate.operation != "upsert" or candidate.scope != "stable":
            raise ValueError("仓储只接受稳定的 upsert 偏好")

        connection = self._connection_factory()
        cursor = connection.cursor(dictionary=True)
        try:
            connection.start_transaction()
            cursor.execute(
                """
                SELECT value_json FROM travel_user_preferences
                WHERE user_id = %s AND preference_key = %s
                FOR UPDATE
                """,
                (user_id, candidate.preference_key),
            )
            old_row = cursor.fetchone()
            old_value_json = old_row.get("value_json") if old_row else None
            value_json = json.dumps(candidate.value, ensure_ascii=False)
            cursor.execute(
                """
                INSERT INTO travel_user_preferences
                    (user_id, preference_key, value_json, confidence,
                     source_session_id, source_text, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    value_json = VALUES(value_json),
                    confidence = VALUES(confidence),
                    source_session_id = VALUES(source_session_id),
                    source_text = VALUES(source_text),
                    status = VALUES(status),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user_id,
                    candidate.preference_key,
                    value_json,
                    candidate.confidence,
                    session_id,
                    candidate.source_text,
                    "active",
                ),
            )
            cursor.execute(
                """
                INSERT INTO travel_preference_events
                    (user_id, session_id, preference_key, operation,
                     old_value_json, new_value_json, source_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    session_id,
                    candidate.preference_key,
                    "upsert",
                    old_value_json,
                    value_json,
                    candidate.source_text,
                ),
            )
            connection.commit()
            return PreferenceRecord(
                user_id=user_id,
                preference_key=candidate.preference_key,
                value=candidate.value,
                confidence=candidate.confidence,
                source_session_id=session_id,
                source_text=candidate.source_text,
                status="active",
            )
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def delete(
        self,
        user_id: str,
        session_id: str,
        key: str,
        source_text: str,
    ) -> None:
        validate_identity(user_id, session_id)
        validate_preference_key(key)
        connection = self._connection_factory()
        cursor = connection.cursor(dictionary=True)
        try:
            connection.start_transaction()
            cursor.execute(
                """
                SELECT value_json FROM travel_user_preferences
                WHERE user_id = %s AND preference_key = %s
                FOR UPDATE
                """,
                (user_id, key),
            )
            old_row = cursor.fetchone()
            old_value_json = old_row.get("value_json") if old_row else None
            cursor.execute(
                """
                UPDATE travel_user_preferences
                SET status = %s, source_session_id = %s, source_text = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE user_id = %s AND preference_key = %s
                """,
                ("deleted", session_id, source_text, user_id, key),
            )
            cursor.execute(
                """
                INSERT INTO travel_preference_events
                    (user_id, session_id, preference_key, operation,
                     old_value_json, new_value_json, source_text)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, session_id, key, "delete", old_value_json, None, source_text),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()
