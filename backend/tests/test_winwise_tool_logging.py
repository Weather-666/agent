import logging

from app.services.chat_service import _acp_reasoning_text, _log_acp_tool_failure


def test_failed_tool_logs_context_without_sensitive_payload(caplog):
    data = {"data": {"status": "failed", "kind": "read", "title": "SECRET_TITLE",
                     "rawInput": {"url": "https://example.com?token=SECRET_TOKEN"},
                     "rawOutput": "PRIVATE_FILE_BODY"}}
    with caplog.at_level(logging.WARNING):
        _log_acp_tool_failure(data, session_id="session", turn_id="turn", expert_id="expert")
    assert "session=session turn=turn expert=expert action=read result=failed" in caplog.text
    assert "SECRET" not in caplog.text
    assert "PRIVATE_FILE_BODY" not in caplog.text


def test_normal_tool_and_model_refusal_do_not_create_risk_events(caplog):
    for payload in ({"status": "completed"}, {"text": "I cannot help with that"}, {}):
        _log_acp_tool_failure({"data": payload}, session_id="s", turn_id="t", expert_id="e")
    assert not caplog.records


def test_tool_history_omits_arguments_outputs_and_command_titles():
    assert _acp_reasoning_text("tool_call", {"data": {
        "title": "curl https://example.com?token=PRIVATE", "kind": "execute",
        "rawInput": {"command": "echo FILE_BODY"}, "rawOutput": "PRIVATE_DATA",
    }}) == "Processing your request.\n"
    assert _acp_reasoning_text("tool_call", {"data": {
        "title": "Tool: expert_knowledge/search_expert_knowledge",
        "rawInput": {"query": "PRIVATE_QUERY", "turnId": "INTERNAL_TURN"},
    }}) == "Processing your request.\n"


def test_public_progress_excludes_raw_reasoning_and_reports_failure():
    assert _acp_reasoning_text("reasoning", {"text": "bwrap: uid map denied"}) == (
        "Processing your request.\n"
    )
    assert _acp_reasoning_text("tool_call", {"data": {
        "status": "failed", "name": "exec_command", "rawOutput": "sandbox denied",
    }}) == "A requested operation could not be completed.\n"


def test_legacy_reasoning_is_private():
    from app.services.chat_service import _public_reasoning

    assert _public_reasoning("[tool] Tool: personal_library/find_personal_file") == (
        "Processing your request.\n"
    )
    assert _public_reasoning("") == ""
