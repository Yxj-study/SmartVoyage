from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Protocol

from SmartVoyage.memory.models import PreferenceCandidate, PreferenceRecord
from SmartVoyage.memory.policy import SUPPORTED_PREFERENCE_KEYS, validate_candidate


class PreferenceRepository(Protocol):
    def list_active(self, user_id: str) -> list[PreferenceRecord]: ...

    def upsert(
        self,
        user_id: str,
        session_id: str,
        candidate: PreferenceCandidate,
    ) -> PreferenceRecord: ...

    def delete(
        self,
        user_id: str,
        session_id: str,
        key: str,
        source_text: str,
    ) -> None: ...


def validate_identity(user_id: str, session_id: str | None = None) -> None:
    if not isinstance(user_id, str) or not user_id.strip():
        raise ValueError("user_id 不能为空")
    if session_id is not None and (
        not isinstance(session_id, str) or not session_id.strip()
    ):
        raise ValueError("session_id 不能为空")


def validate_preference_key(key: str) -> None:
    if key not in SUPPORTED_PREFERENCE_KEYS:
        raise ValueError(f"不支持的偏好字段: {key}")


class InMemoryPreferenceRepository:
    def __init__(self):
        self._records: dict[tuple[str, str], PreferenceRecord] = {}
        self.events: list[dict] = []

    def list_active(self, user_id: str) -> list[PreferenceRecord]:
        validate_identity(user_id)
        records = [
            record
            for (record_user_id, _), record in self._records.items()
            if record_user_id == user_id and record.status == "active"
        ]
        records.sort(key=lambda item: item.preference_key)
        return deepcopy(records)

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

        storage_key = (user_id, candidate.preference_key)
        old_record = self._records.get(storage_key)
        now = datetime.now().astimezone()
        record = PreferenceRecord(
            user_id=user_id,
            preference_key=candidate.preference_key,
            value=deepcopy(candidate.value),
            confidence=candidate.confidence,
            source_session_id=session_id,
            source_text=candidate.source_text,
            status="active",
            created_at=old_record.created_at if old_record else now,
            updated_at=now,
        )
        self._records[storage_key] = record
        self.events.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "preference_key": candidate.preference_key,
                "operation": "upsert",
                "old_value": deepcopy(old_record.value) if old_record else None,
                "new_value": deepcopy(candidate.value),
                "source_text": candidate.source_text,
            }
        )
        return deepcopy(record)

    def delete(
        self,
        user_id: str,
        session_id: str,
        key: str,
        source_text: str,
    ) -> None:
        validate_identity(user_id, session_id)
        validate_preference_key(key)
        storage_key = (user_id, key)
        old_record = self._records.get(storage_key)
        if old_record:
            self._records[storage_key] = old_record.model_copy(
                update={
                    "status": "deleted",
                    "source_session_id": session_id,
                    "source_text": source_text,
                    "updated_at": datetime.now().astimezone(),
                },
                deep=True,
            )
        self.events.append(
            {
                "user_id": user_id,
                "session_id": session_id,
                "preference_key": key,
                "operation": "delete",
                "old_value": deepcopy(old_record.value) if old_record else None,
                "new_value": None,
                "source_text": source_text,
            }
        )
