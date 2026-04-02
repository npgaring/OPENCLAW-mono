"""Regression guard for governed v2 DB model types."""

from uuid import UUID

from app.models.governed_v2_db import StageEventRecordV2


def test_stage_event_id_is_uuid_not_string():
    row = StageEventRecordV2(
        trace_id="11111111-1111-1111-1111-111111111111",
        stage="RAW_INTENT",
        event_type="RAW_INTENT_RECEIVED",
        status="draft",
        artifact_hash="abc",
        metadata_={"k": "v"},
    )
    assert isinstance(row.id, UUID)
