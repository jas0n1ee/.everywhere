from __future__ import annotations

import json
import subprocess
from pathlib import Path

import sys

repo_root = Path(__file__).resolve().parents[1]
scripts_dir = repo_root / "scripts"
if not scripts_dir.exists():
    scripts_dir = repo_root / ".codex" / "scripts"
sys.path.insert(0, str(scripts_dir))

import feishu_bridge as bridge  # noqa: E402


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


def test_tmux_paste_input_uses_current_session_target() -> None:
    calls: list[list[str]] = []

    def runner(command, **kwargs):
        calls.append(command)
        if command[:3] == ["tmux", "display-message", "-p"]:
            return completed("orchestrator\n")
        return completed("")

    tmux = bridge.TmuxClient(runner=runner)
    tmux.paste_input("my-topic", "hello")
    assert ["tmux", "paste-buffer", "-b", calls[1][3], "-t", "my-topic:0"] in calls
    assert ["tmux", "send-keys", "-t", "my-topic:0", "Enter"] in calls


def test_extract_text_from_text_event() -> None:
    event = {"message_type": "text", "content": json.dumps({"text": "hello"})}
    assert bridge.extract_text(event) == "hello"


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

        def validate_orchestrator(self, session):
            assert session == "topic-a"

        def pane_cwd(self, session):
            return str(tmp_path)

    binding = bridge.create_or_update_binding(state, FakeLark(), FakeTmux())
    assert binding.root_message_id == "om_new"
    assert binding.remote_control_active
    assert sent == [("oc_default", "topic-a\n\nRemote Control attached.")]
    assert state.binding_for_topic("topic-a").root_message_id == "om_new"


def test_detach_preserves_binding(tmp_path: Path) -> None:
    state = bridge.BridgeState(tmp_path)
    state.upsert_binding(bridge.Binding.create(topic="topic-a", chat_id="oc_1", root_message_id="om_root"))
    binding = state.set_remote_control("topic-a", False)
    assert not binding.remote_control_active
    assert state.binding_for_topic("topic-a").root_message_id == "om_root"


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


def test_extract_post_image_placeholder_resource_key() -> None:
    event = {"message_type": "post", "content": "[Image: img_v3_abc-123]"}
    assert bridge.extract_resource_key(event) == ("img_v3_abc-123", "image")
