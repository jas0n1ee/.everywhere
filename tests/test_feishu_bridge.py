from __future__ import annotations

import contextlib
import io
import json
import subprocess
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

import sys

repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

from everywhere import feishu_bridge as bridge  # noqa: E402


def completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr="")


def test_default_chat_resolution_priority(tmp_path: Path, monkeypatch) -> None:
    state = bridge.BridgeState(tmp_path)
    state.save_default_chat_id("oc_saved")
    assert state.get_default_chat_id() == "oc_saved"
    monkeypatch.setenv("FEISHU_BRIDGE_CHAT_ID", "oc_env")
    assert state.get_default_chat_id() == "oc_env"


def test_binding_lookup_by_root_or_thread(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    state.upsert_binding(bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root", thread_id="omt_1"))
    assert state.binding_for_message("oc_1", ["om_root"]).topic == "topic-a"
    assert state.binding_for_message("oc_1", ["omt_1"]).topic == "topic-a"
    assert state.binding_for_message("oc_other", ["om_root"]) is None


def test_inbound_event_dedupe(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    assert not state.seen_inbound("evt_1")
    state.mark_inbound("evt_1")
    assert state.seen_inbound("evt_1")


def test_outbound_message_dedupe(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    assert not state.seen_outbound("topic:turn")
    state.mark_outbound("topic:turn")
    assert state.seen_outbound("topic:turn")


def test_split_text_adds_ordered_prefixes() -> None:
    chunks = bridge.split_text("alpha beta gamma delta epsilon zeta eta theta", limit=25)
    assert len(chunks) == 2
    assert chunks[0].startswith("[1/2]\n")
    assert chunks[1].startswith("[2/2]\n")


def test_idempotency_key_stays_within_lark_limit() -> None:
    key = bridge.idempotency_key("feishu-bridge-claude-test", "root")
    assert len(key) <= 50


def test_runner_status_requires_live_pid_and_fresh_heartbeat() -> None:
    updated_at = "2026-05-08T12:00:00"
    updated_ts = bridge.parse_iso_timestamp(updated_at)
    assert updated_ts is not None

    with patch.object(bridge, "RUNNER_STALE_SECONDS", 10), patch.object(bridge, "process_exists", lambda pid: pid == 123):
        fresh = bridge.runner_status_payload({"pid": 123, "updated_at": updated_at}, now=updated_ts + 5)
        stale = bridge.runner_status_payload({"pid": 123, "updated_at": updated_at}, now=updated_ts + 20)
        dead = bridge.runner_status_payload({"pid": 456, "updated_at": updated_at}, now=updated_ts + 5)

    assert fresh["running"] is True
    assert stale["running"] is False
    assert dead["running"] is False


def test_state_runner_heartbeat_round_trip(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    state.save_runner_heartbeat(event_consumer_pid=456)

    raw = json.loads((tmp_path / "runner.json").read_text(encoding="utf-8"))
    assert raw["pid"] == bridge.os.getpid()
    assert raw["event_consumer_pid"] == 456
    assert raw["event_key"] == bridge.EVENT_KEY

    state.clear_runner_heartbeat()
    assert not (tmp_path / "runner.json").exists()


def test_tmux_paste_input_uses_bound_target_pane() -> None:
    calls: list[list[str]] = []
    inputs: list[str | None] = []

    def runner(command, **kwargs):
        calls.append(command)
        inputs.append(kwargs.get("input"))
        if command[:3] == ["tmux", "display-message", "-p"]:
            return completed("%7\n")
        return completed("")

    tmux = bridge.TmuxClient(runner=runner)
    binding = bridge.Binding.create(topic="my-topic", chat_id="oc_1", root_message_id="om_root", target_pane="%7")
    with patch.object(bridge, "SUBMIT_DELAY_SECONDS", 0):
        tmux.paste_input(binding, "hello\n")
    assert inputs[1] == "hello"
    assert ["tmux", "paste-buffer", "-b", calls[1][3], "-t", "%7"] in calls
    assert ["tmux", "send-keys", "-t", "%7", "Enter"] in calls


def test_tmux_paste_input_legacy_binding_falls_back_to_session_pane_zero() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return completed("%8\n")

    tmux = bridge.TmuxClient(runner=runner)
    binding = bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root")
    with patch.object(bridge, "SUBMIT_DELAY_SECONDS", 0):
        tmux.paste_input(binding, "hello")
    assert ["tmux", "paste-buffer", "-b", calls[1][3], "-t", "topic-a:0.0"] in calls


def test_tmux_current_pane_prefers_tmux_pane_env() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return completed("%7\n")

    tmux = bridge.TmuxClient(runner=runner)
    with patch.dict(bridge.os.environ, {"TMUX": "/tmp/tmux", "TMUX_PANE": "%7"}):
        assert tmux.current_pane() == "%7"
    assert calls == [["tmux", "display-message", "-p", "-t", "%7", "#{pane_id}"]]


def test_tmux_current_session_uses_tmux_pane_env_target() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        if command == ["tmux", "display-message", "-p", "-t", "%7", "#{pane_id}"]:
            return completed("%7\n")
        if command == ["tmux", "display-message", "-p", "-t", "%7", "#{session_name}"]:
            return completed("topic-a\n")
        raise AssertionError(command)

    tmux = bridge.TmuxClient(runner=runner)
    with patch.dict(bridge.os.environ, {"TMUX": "/tmp/tmux", "TMUX_PANE": "%7"}):
        assert tmux.current_session() == "topic-a"


def test_tmux_pane_cwd_uses_bound_target_pane() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        return completed("/repo\n")

    tmux = bridge.TmuxClient(runner=runner)
    binding = bridge.Binding.create(topic="my-topic", chat_id="oc_1", root_message_id="om_root", target_pane="%7")
    assert tmux.pane_cwd(binding) == "/repo"
    assert calls == [["tmux", "display-message", "-p", "-t", "%7", "#{pane_current_path}"]]


def test_extract_text_from_text_event() -> None:
    event = {"message_type": "text", "content": json.dumps({"text": "hello"})}
    assert bridge.extract_text(event) == "hello"


def test_extract_text_from_rendered_post_event() -> None:
    event = {"message_type": "post", "content": "我给你发一些markdown 格式再进行一下测试"}
    assert bridge.extract_text(event) == "我给你发一些markdown 格式再进行一下测试"


def test_ack_bootstrap_message_adds_reaction() -> None:
    calls: list[str] = []

    class FakeLark:
        def add_ack_reaction(self, message_id):
            calls.append(message_id)

    event = {"message_id": "om_bootstrap"}
    assert bridge.ack_bootstrap_message(FakeLark(), event)
    assert calls == ["om_bootstrap"]


def test_ack_bootstrap_message_without_message_id_is_noop() -> None:
    class FakeLark:
        def add_ack_reaction(self, message_id):
            raise AssertionError("should not react without message id")

    assert not bridge.ack_bootstrap_message(FakeLark(), {})


def test_attach_creates_binding_when_missing(tmp_path: Path, monkeypatch) -> None:
    state = bridge.BridgeState(tmp_path)
    state.save_default_chat_id("oc_default")
    sent: list[tuple[str, str]] = []

    class FakeLark:
        def send_text(self, chat_id, text, idempotency_key=None):
            sent.append((chat_id, text))
            return {"data": {"message_id": "om_new"}}

        def reply_text(self, root_message_id, text, idempotency_key=None):
            raise AssertionError("attach should create one root message only")

        def mget(self, message_id):
            return {}

    class FakeTmux:
        def current_session(self):
            return "topic-a"

        def current_pane(self):
            return "%7"

        def pane_cwd(self, binding):
            assert binding.target_pane == "%7"
            return str(tmp_path)

    binding = bridge.create_or_update_binding(state, FakeLark(), FakeTmux())
    assert binding.root_message_id == "om_new"
    assert binding.remote_control_active
    assert binding.target_pane == "%7"
    assert sent == [("oc_default", "topic-a\n\nRemote Control attached.")]
    assert state.binding_for_topic("topic-a").root_message_id == "om_new"


def test_detach_preserves_binding(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    state.upsert_binding(bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root"))
    binding = state.set_remote_control("topic-a", False)
    assert not binding.remote_control_active
    assert state.binding_for_topic("topic-a").root_message_id == "om_root"


def test_current_json_reports_current_binding(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    state.upsert_binding(bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root"))

    class FakeTmux:
        def current_session(self):
            return "topic-a"

    args = SimpleNamespace(state_dir=tmp_path, json=True)
    stdout = io.StringIO()
    with patch.object(bridge, "TmuxClient", return_value=FakeTmux()), contextlib.redirect_stdout(stdout):
        assert bridge.cmd_current(args) == 0
    payload = json.loads(stdout.getvalue())
    assert payload["bound"] is True
    assert payload["topic"] == "topic-a"
    assert payload["root_message_id"] == "om_root"


def test_parse_codex_task_complete_final_message() -> None:
    entry = {
        "timestamp": "2026-05-07T00:00:00Z",
        "type": "event_msg",
        "payload": {"type": "task_complete", "turn_id": "turn_1", "last_agent_message": "done"},
    }
    assert bridge.parse_codex_final_entry(entry) == ("turn_1", "done")


def test_read_codex_final_messages_from_offset(tmp_path: Path) -> None:
    path = tmp_path / "session.jsonl"
    first = json.dumps({"type": "session_meta", "payload": {"id": "s", "cwd": str(tmp_path)}}) + "\n"
    path.write_text(first, encoding="utf-8")
    offset = path.stat().st_size
    path.write_text(
        first
        + json.dumps({"timestamp": "t1", "type": "event_msg", "payload": {"type": "task_complete", "turn_id": "turn_1", "last_agent_message": "done"}})
        + "\n",
        encoding="utf-8",
    )
    messages, new_offset = bridge.read_codex_final_messages(path, offset)
    assert messages == [("turn_1", "done")]
    assert new_offset == path.stat().st_size


def test_parse_claude_assistant_text_entry() -> None:
    entry = {
        "type": "assistant",
        "uuid": "claude-turn-1",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hidden"},
                {"type": "text", "text": "visible final"},
                {"type": "tool_use", "name": "Bash"},
            ],
        },
    }
    assert bridge.parse_claude_final_entry(entry) == ("claude-turn-1", "visible final")


def test_parse_claude_end_turn_falls_back_to_thinking_without_text() -> None:
    entry = {
        "type": "assistant",
        "uuid": "claude-turn-1",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "fallback final"}],
        },
    }
    assert bridge.parse_claude_final_entry(entry) == ("claude-turn-1", "fallback final")


def test_parse_claude_tool_use_without_text_is_not_final() -> None:
    entry = {
        "type": "assistant",
        "uuid": "claude-turn-1",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "stop_reason": "tool_use",
            "content": [
                {"type": "thinking", "thinking": "about to run a tool"},
                {"type": "tool_use", "name": "Bash", "input": {"command": "pwd"}},
            ],
        },
    }
    assert bridge.parse_claude_final_entry(entry) == (None, None)


def test_read_claude_final_messages_from_offset(tmp_path: Path) -> None:
    path = tmp_path / "claude.jsonl"
    first = json.dumps({"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "hi"}}) + "\n"
    path.write_text(first, encoding="utf-8")
    offset = path.stat().st_size
    path.write_text(
        first
        + json.dumps(
            {
                "type": "assistant",
                "uuid": "claude-turn-1",
                "message": {"role": "assistant", "content": [{"type": "text", "text": "done"}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )
    messages, new_offset = bridge.read_claude_final_messages(path, offset)
    assert messages == [("claude-turn-1", "done")]
    assert new_offset == path.stat().st_size


def test_read_claude_final_messages_prefers_text_over_thinking_chunk(tmp_path: Path) -> None:
    path = tmp_path / "claude.jsonl"
    first = json.dumps({"type": "user", "cwd": str(tmp_path), "message": {"role": "user", "content": "hi"}}) + "\n"
    path.write_text(first, encoding="utf-8")
    offset = path.stat().st_size
    thinking_chunk = {
        "type": "assistant",
        "uuid": "claude-thinking",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "thinking", "thinking": "fallback final"}],
        },
    }
    text_chunk = {
        "type": "assistant",
        "uuid": "claude-text",
        "message": {
            "id": "msg_1",
            "role": "assistant",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "visible final"}],
        },
    }
    path.write_text(first + json.dumps(thinking_chunk) + "\n" + json.dumps(text_chunk) + "\n", encoding="utf-8")
    messages, new_offset = bridge.read_claude_final_messages(path, offset)
    assert messages == [("claude-text", "visible final")]
    assert new_offset == path.stat().st_size


def test_send_thread_text_uses_structured_post() -> None:
    sent: list[tuple[str, dict, str | None]] = []

    class FakeLark:
        def reply_post(self, root_message_id, content, idempotency_key=None):
            sent.append((root_message_id, content, idempotency_key))
            return {}

    binding = bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root")
    bridge.send_thread_text(FakeLark(), binding, "**done**", "turn_1")
    assert sent[0][0] == "om_root"
    assert sent[0][1]["zh_cn"]["content"] == [[{"tag": "md", "text": "**done**"}]]


def test_markdown_to_feishu_post_preserves_lines_and_code() -> None:
    content = bridge.markdown_to_feishu_post("1. 你在 Feishu thread 发一条：\n\n```bash\n./feishu-bridge detach\n```")
    assert content["zh_cn"]["content"] == [
        [{"tag": "md", "text": "1. 你在 Feishu thread 发一条："}],
        [{"tag": "text", "text": " "}],
        [{"tag": "md", "text": "```\n./feishu-bridge detach\n```"}],
    ]


def test_markdown_to_feishu_post_preserves_list_markers() -> None:
    content = bridge.markdown_to_feishu_post("- item\n2. numbered\nnormal **bold**")
    assert content["zh_cn"]["content"] == [
        [{"tag": "md", "text": "- item"}],
        [{"tag": "md", "text": "2. numbered"}],
        [{"tag": "md", "text": "normal **bold**"}],
    ]


def test_extract_image_resource_key() -> None:
    event = {"message_type": "image", "content": json.dumps({"image_key": "img_v3_1"})}
    assert bridge.extract_resource_key(event) == ("img_v3_1", "image")


def test_extract_file_resource_key_from_enriched() -> None:
    event = {"message_type": "file", "content": "{}"}
    enriched = {"data": {"items": [{"body": {"content": json.dumps({"file_key": "file_v3_1"})}}]}}
    assert bridge.extract_resource_key(event, enriched) == ("file_v3_1", "file")


def test_extract_resource_key_ignores_post_inline_code_key_fields() -> None:
    event = {
        "message_type": "post",
        "content": json.dumps(
            {
                "zh_cn": {
                    "content": [
                        [
                            {"tag": "text", "text": "PyPI 的正常升级， bump 到 "},
                            {"tag": "code_inline", "text": "0.1.1", "key": "file_not_an_attachment"},
                        ]
                    ]
                }
            }
        ),
    }
    assert bridge.extract_text(event) == "PyPI 的正常升级， bump 到 0.1.1"
    assert bridge.extract_resource_key(event) == (None, None)
