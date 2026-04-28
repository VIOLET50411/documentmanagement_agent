from app.api.v1.chat import _parse_resume_from_last_event_id


def test_parse_resume_from_last_event_id_ok():
    trace_id, sequence = _parse_resume_from_last_event_id("trace-123:45")
    assert trace_id == "trace-123"
    assert sequence == 45


def test_parse_resume_from_last_event_id_invalid():
    trace_id, sequence = _parse_resume_from_last_event_id("bad-format")
    assert trace_id is None
    assert sequence == 0
