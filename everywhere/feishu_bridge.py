#!/usr/bin/env python3
"""Remote-control bridge between Feishu threads and local tmux agent sessions.

The bridge is transport-only. A Feishu thread is bound to one tmux session, the
session name is the topic, and attach records the current tmux pane as the
remote-control target. While attached, human text replies are pasted into that
pane and assistant final replies from provider transcripts are sent back to the
thread.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable


EVENT_KEY = "im.message.receive_v1"
DEFAULT_STATE_DIR = Path("~/.everywhere/feishu-bridge").expanduser()
MAX_TEXT_CHARS = int(os.environ.get("FEISHU_BRIDGE_MAX_TEXT_CHARS", "3500"))
ACK_REACTION = os.environ.get("FEISHU_BRIDGE_ACK_REACTION", "OnIt")
SUBMIT_DELAY_SECONDS = float(os.environ.get("FEISHU_BRIDGE_SUBMIT_DELAY_SECONDS", "0.1"))
CODEX_SESSIONS_DIR = Path(os.environ.get("FEISHU_BRIDGE_CODEX_SESSIONS", "~/.codex/sessions")).expanduser()
CLAUDE_PROJECTS_DIR = Path(os.environ.get("FEISHU_BRIDGE_CLAUDE_PROJECTS", "~/.claude/projects")).expanduser()
RUNNER_STALE_SECONDS = float(os.environ.get("FEISHU_BRIDGE_RUNNER_STALE_SECONDS", "10"))

Runner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass
class Binding:
    topic: str
    chat_id: str
    root_message_id: str
    thread_id: str | None = None
    title: str | None = None
    active: bool = True
    remote_control_active: bool = False
    target_pane: str | None = None
    default: bool = False
    transcript_path: str | None = None
    transcript_offset: int = 0
    created_at: str = ""
    updated_at: str = ""

    @classmethod
    def create(
        cls,
        *,
        topic: str,
        chat_id: str,
        root_message_id: str,
        thread_id: str | None = None,
        target_pane: str | None = None,
        default: bool = False,
    ) -> "Binding":
        now = datetime.now().isoformat()
        return cls(
            topic=topic,
            chat_id=chat_id,
            root_message_id=root_message_id,
            thread_id=thread_id,
            title=topic,
            active=True,
            remote_control_active=True,
            target_pane=target_pane,
            default=default,
            created_at=now,
            updated_at=now,
        )


class BridgeState:
    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        self.state_dir = state_dir.expanduser()
        self.config_path = self.state_dir / "config.json"
        self.bindings_path = self.state_dir / "bindings.json"
        self.inbound_seen_path = self.state_dir / "inbound-events.json"
        self.outbound_seen_path = self.state_dir / "outbound-messages.json"
        self.runner_path = self.state_dir / "runner.json"
        self.log_path = self.state_dir / "bridge.log"

    def ensure(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def load_config(self) -> dict[str, Any]:
        return self._read_json(self.config_path, {})

    def save_config(self, payload: dict[str, Any]) -> None:
        self._write_json(self.config_path, payload)

    def get_default_chat_id(self) -> str | None:
        env_chat = os.environ.get("FEISHU_BRIDGE_CHAT_ID")
        if env_chat:
            return env_chat
        value = self.load_config().get("default_chat_id")
        return value if isinstance(value, str) and value else None

    def save_default_chat_id(self, chat_id: str) -> None:
        config = self.load_config()
        config["default_chat_id"] = chat_id
        config["updated_at"] = datetime.now().isoformat()
        self.save_config(config)

    def load_bindings(self) -> list[Binding]:
        raw = self._read_json(self.bindings_path, [])
        bindings: list[Binding] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            item.setdefault("remote_control_active", bool(item.get("active", False)))
            item.setdefault("target_pane", None)
            item.setdefault("transcript_path", None)
            item.setdefault("transcript_offset", 0)
            bindings.append(Binding(**item))
        return bindings

    def save_bindings(self, bindings: list[Binding]) -> None:
        self._write_json(self.bindings_path, [asdict(binding) for binding in bindings])

    def upsert_binding(self, binding: Binding) -> None:
        bindings = [existing for existing in self.load_bindings() if existing.topic != binding.topic]
        binding.updated_at = datetime.now().isoformat()
        bindings.append(binding)
        self.save_bindings(bindings)

    def binding_for_topic(self, topic: str, *, require_active: bool = True) -> Binding | None:
        for binding in self.load_bindings():
            if binding.topic != topic:
                continue
            if require_active and not binding.active:
                continue
            return binding
        return None

    def binding_for_message(self, chat_id: str, message_ids: Iterable[str | None]) -> Binding | None:
        candidates = {item for item in message_ids if item}
        for binding in self.load_bindings():
            if not binding.active or binding.chat_id != chat_id:
                continue
            if binding.root_message_id in candidates or (binding.thread_id and binding.thread_id in candidates):
                return binding
        return None

    def set_remote_control(self, topic: str, enabled: bool) -> Binding:
        binding = self.binding_for_topic(topic)
        if not binding:
            raise RuntimeError(f"No binding for tmux session '{topic}'")
        binding.remote_control_active = enabled
        binding.updated_at = datetime.now().isoformat()
        self.upsert_binding(binding)
        return binding

    def seen_inbound(self, event_id: str) -> bool:
        return event_id in self._load_set(self.inbound_seen_path)

    def mark_inbound(self, event_id: str) -> None:
        values = self._load_set(self.inbound_seen_path)
        values.add(event_id)
        self._save_set(self.inbound_seen_path, values)

    def seen_outbound(self, message_id: str) -> bool:
        return message_id in self._load_set(self.outbound_seen_path)

    def mark_outbound(self, message_id: str) -> None:
        values = self._load_set(self.outbound_seen_path)
        values.add(message_id)
        self._save_set(self.outbound_seen_path, values)

    def save_runner_heartbeat(self, *, event_consumer_pid: int | None = None) -> None:
        payload = {
            "pid": os.getpid(),
            "event_consumer_pid": event_consumer_pid,
            "event_key": EVENT_KEY,
            "updated_at": datetime.now().isoformat(),
        }
        self._write_json(self.runner_path, payload)

    def load_runner_status(self) -> dict[str, Any]:
        return runner_status_payload(self._read_json(self.runner_path, {}), now=time.time())

    def clear_runner_heartbeat(self) -> None:
        try:
            self.runner_path.unlink()
        except FileNotFoundError:
            pass

    def log(self, message: str) -> None:
        self.ensure()
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{datetime.now().isoformat()}] {message}\n")

    def _read_json(self, path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return default

    def _write_json(self, path: Path, payload: Any) -> None:
        self.ensure()
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _load_set(self, path: Path) -> set[str]:
        raw = self._read_json(path, [])
        return {str(item) for item in raw}

    def _save_set(self, path: Path, values: set[str]) -> None:
        self._write_json(path, sorted(values))


class LarkClient:
    def __init__(self, runner: Runner = subprocess.run) -> None:
        self.runner = runner

    def check(self) -> tuple[bool, str]:
        if not shutil.which("lark-cli"):
            return False, "lark-cli not found on PATH"
        result = self.runner(["lark-cli", "event", "--help"], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            return False, "lark-cli event help failed"
        return True, "ok"

    def send_text(self, chat_id: str, text: str, idempotency_key: str | None = None) -> dict[str, Any]:
        command = ["lark-cli", "im", "+messages-send", "--chat-id", chat_id, "--text", text, "--as", "bot"]
        if idempotency_key:
            command.extend(["--idempotency-key", idempotency_key])
        return self._json(command)

    def send_post(self, chat_id: str, content: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        command = [
            "lark-cli",
            "im",
            "+messages-send",
            "--chat-id",
            chat_id,
            "--msg-type",
            "post",
            "--content",
            json.dumps(content, ensure_ascii=False),
            "--as",
            "bot",
        ]
        if idempotency_key:
            command.extend(["--idempotency-key", idempotency_key])
        return self._json(command)

    def reply_text(self, root_message_id: str, text: str, idempotency_key: str | None = None) -> dict[str, Any]:
        command = [
            "lark-cli",
            "im",
            "+messages-reply",
            "--message-id",
            root_message_id,
            "--text",
            text,
            "--reply-in-thread",
            "--as",
            "bot",
        ]
        if idempotency_key:
            command.extend(["--idempotency-key", idempotency_key])
        return self._json(command)

    def reply_post(self, root_message_id: str, content: dict[str, Any], idempotency_key: str | None = None) -> dict[str, Any]:
        command = [
            "lark-cli",
            "im",
            "+messages-reply",
            "--message-id",
            root_message_id,
            "--msg-type",
            "post",
            "--content",
            json.dumps(content, ensure_ascii=False),
            "--reply-in-thread",
            "--as",
            "bot",
        ]
        if idempotency_key:
            command.extend(["--idempotency-key", idempotency_key])
        return self._json(command)

    def add_ack_reaction(self, message_id: str, emoji_type: str = ACK_REACTION) -> None:
        self._json(
            [
                "lark-cli",
                "im",
                "reactions",
                "create",
                "--params",
                json.dumps({"message_id": message_id}),
                "--data",
                json.dumps({"reaction_type": {"emoji_type": emoji_type}}),
                "--as",
                "bot",
                "--format",
                "json",
            ]
        )

    def mget(self, message_id: str) -> dict[str, Any]:
        return self._json(
            [
                "lark-cli",
                "im",
                "+messages-mget",
                "--message-ids",
                message_id,
                "--as",
                "bot",
                "--format",
                "json",
            ]
        )

    def download_resource(self, message_id: str, file_key: str, resource_type: str, output: Path) -> Path:
        output.parent.mkdir(parents=True, exist_ok=True)
        command = [
            "lark-cli",
            "im",
            "+messages-resources-download",
            "--message-id",
            message_id,
            "--file-key",
            file_key,
            "--type",
            resource_type,
            "--output",
            output.name,
            "--as",
            "bot",
        ]
        result = self.runner(command, text=True, capture_output=True, check=False, cwd=str(output.parent))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "lark-cli resource download failed")
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError:
            payload = {}
        saved_path = payload.get("data", {}).get("saved_path") if isinstance(payload, dict) else None
        return Path(saved_path) if isinstance(saved_path, str) and saved_path else output

    def _json(self, command: list[str]) -> dict[str, Any]:
        result = self.runner(command, text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "lark-cli command failed")
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)


class TmuxClient:
    def __init__(self, runner: Runner = subprocess.run) -> None:
        self.runner = runner

    def current_session(self) -> str:
        target_pane = self.current_pane()
        return self._tmux(["display-message", "-p", "-t", target_pane, "#{session_name}"]).strip()

    def current_pane(self) -> str:
        if not os.environ.get("TMUX"):
            raise RuntimeError("feishu-bridge attach/detach must run inside the target tmux session")
        env_pane = os.environ.get("TMUX_PANE")
        if env_pane:
            self._tmux(["display-message", "-p", "-t", env_pane, "#{pane_id}"])
            return env_pane
        return self._tmux(["display-message", "-p", "#{pane_id}"]).strip()


    def legacy_pane_target(self, session: str) -> str:
        return f"{session}:0.0"

    def target_for_binding(self, binding: Binding) -> str:
        return binding.target_pane or self.legacy_pane_target(binding.topic)

    def pane_cwd(self, binding: Binding) -> str:
        return self._tmux(["display-message", "-p", "-t", self.target_for_binding(binding), "#{pane_current_path}"]).strip()

    def ensure_pane_exists(self, binding: Binding) -> None:
        self._tmux(["display-message", "-p", "-t", self.target_for_binding(binding), "#{pane_id}"])

    def paste_input(self, binding: Binding, text: str) -> None:
        self.ensure_pane_exists(binding)
        buffer_name = f"feishu-bridge-{os.getpid()}"
        target = self.target_for_binding(binding)
        payload = text.rstrip("\n")
        load = self.runner(["tmux", "load-buffer", "-b", buffer_name, "-"], input=payload, text=True, capture_output=True, check=False)
        if load.returncode != 0:
            raise RuntimeError(load.stderr.strip() or "tmux load-buffer failed")
        paste = self.runner(["tmux", "paste-buffer", "-b", buffer_name, "-t", target], text=True, capture_output=True, check=False)
        self.runner(["tmux", "delete-buffer", "-b", buffer_name], text=True, capture_output=True, check=False)
        if paste.returncode != 0:
            raise RuntimeError(paste.stderr.strip() or "tmux paste-buffer failed")
        if SUBMIT_DELAY_SECONDS > 0:
            time.sleep(SUBMIT_DELAY_SECONDS)
        submit = self.runner(["tmux", "send-keys", "-t", target, "Enter"], text=True, capture_output=True, check=False)
        if submit.returncode != 0:
            raise RuntimeError(submit.stderr.strip() or "tmux send-keys Enter failed")

    def _tmux(self, args: list[str]) -> str:
        result = self.runner(["tmux", *args], text=True, capture_output=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "tmux command failed")
        return result.stdout


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in value)[:80] or "topic"


def idempotency_key(*parts: str) -> str:
    digest = hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:20]
    prefix = safe_name(parts[0])[:20] if parts else "bridge"
    return f"fb-{prefix}-{digest}"


def process_exists(pid: Any) -> bool:
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parse_iso_timestamp(value: Any) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return None


def runner_status_payload(raw: Any, *, now: float | None = None) -> dict[str, Any]:
    payload = raw if isinstance(raw, dict) else {}
    updated_at = payload.get("updated_at")
    updated_ts = parse_iso_timestamp(updated_at)
    age_seconds = None if updated_ts is None else max(0.0, (time.time() if now is None else now) - updated_ts)
    pid = payload.get("pid")
    event_consumer_pid = payload.get("event_consumer_pid")
    pid_alive = process_exists(pid)
    fresh = age_seconds is not None and age_seconds <= RUNNER_STALE_SECONDS
    running = pid_alive and fresh
    return {
        "running": running,
        "pid": pid if isinstance(pid, int) else None,
        "pid_alive": pid_alive,
        "event_consumer_pid": event_consumer_pid if isinstance(event_consumer_pid, int) else None,
        "event_consumer_pid_alive": process_exists(event_consumer_pid),
        "event_key": payload.get("event_key") if isinstance(payload.get("event_key"), str) else None,
        "updated_at": updated_at if isinstance(updated_at, str) else None,
        "age_seconds": age_seconds,
        "stale_after_seconds": RUNNER_STALE_SECONDS,
    }


def split_text(text: str, limit: int = MAX_TEXT_CHARS) -> list[str]:
    if limit <= 20:
        raise ValueError("limit is too small")
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        cut = remaining.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = remaining.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    total = len(chunks)
    return [f"[{index}/{total}]\n{chunk}" for index, chunk in enumerate(chunks, start=1)]


def extract_event_id(event: dict[str, Any]) -> str:
    return str(event.get("event_id") or event.get("uuid") or event.get("message_id") or "")


def event_chat_id(event: dict[str, Any]) -> str:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    return str(event.get("chat_id") or message.get("chat_id") or "")


def event_message_id(event: dict[str, Any]) -> str:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    return str(event.get("message_id") or message.get("message_id") or "")


def event_message_type(event: dict[str, Any]) -> str:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    return str(event.get("message_type") or message.get("message_type") or "")


def event_sender_is_bot(event: dict[str, Any]) -> bool:
    sender = event.get("sender") if isinstance(event.get("sender"), dict) else {}
    sender_id = event.get("sender_id")
    if isinstance(sender_id, dict) and sender_id.get("sender_type") == "bot":
        return True
    return sender.get("sender_type") == "bot"


def candidate_message_ids(event: dict[str, Any], enriched: dict[str, Any] | None = None) -> list[str | None]:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    ids: list[str | None] = [
        str(event.get("root_id") or "") or None,
        str(event.get("parent_id") or "") or None,
        str(event.get("thread_id") or "") or None,
        str(message.get("root_id") or "") or None,
        str(message.get("parent_id") or "") or None,
        str(message.get("thread_id") or "") or None,
        event_message_id(event),
    ]
    if enriched:
        ids.extend(_walk_ids(enriched))
    return ids


def _walk_ids(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"message_id", "root_id", "parent_id", "thread_id"} and isinstance(item, str):
                found.append(item)
            else:
                found.extend(_walk_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_ids(item))
    return found


def extract_text(event: dict[str, Any]) -> str | None:
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    msg_type = event_message_type(event)
    content = event.get("content", message.get("content", ""))
    if isinstance(content, str):
        try:
            content_obj: Any = json.loads(content)
        except json.JSONDecodeError:
            content_obj = {"text": content}
    else:
        content_obj = content
    if msg_type == "text":
        if isinstance(content_obj, dict):
            return str(content_obj.get("text", "")).strip()
        return str(content_obj).strip()
    if msg_type == "post":
        if isinstance(content_obj, dict) and isinstance(content_obj.get("text"), str):
            return content_obj["text"].strip()
        if isinstance(content_obj, str):
            return content_obj.strip()
        return flatten_post_text(content_obj).strip()
    return None


def extract_resource_key(event: dict[str, Any], enriched: dict[str, Any] | None = None) -> tuple[str | None, str | None]:
    msg_type = event_message_type(event)
    if msg_type not in {"image", "file"}:
        return None, None
    content = event.get("content")
    message = event.get("message") if isinstance(event.get("message"), dict) else {}
    candidates: list[Any] = [content, message.get("content")]
    if enriched:
        candidates.extend(_walk_content_values(enriched))
    for value in candidates:
        placeholder_key, placeholder_type = extract_resource_key_from_string(value, msg_type)
        if placeholder_key and placeholder_type:
            return placeholder_key, placeholder_type
        parsed = parse_content_object(value)
        if not isinstance(parsed, dict):
            continue
        image_key = parsed.get("image_key") or parsed.get("imageKey")
        if isinstance(image_key, str) and image_key:
            return image_key, "image"
        file_key = parsed.get("file_key") or parsed.get("fileKey") or parsed.get("key")
        if isinstance(file_key, str) and file_key:
            return file_key, "file" if msg_type != "image" else "image"
    return None, None


def extract_resource_key_from_string(value: Any, msg_type: str) -> tuple[str | None, str | None]:
    if not isinstance(value, str):
        return None, None
    image_match = re.search(r"(?:\[Image:\s*|image_key[\"'=:\s]+)(img_[A-Za-z0-9_\\-]+)", value)
    if image_match:
        return image_match.group(1), "image"
    file_match = re.search(r"(?:file_key[\"'=:\s]+|key=[\"']?)(file_[A-Za-z0-9_\\-]+)", value)
    if file_match:
        return file_match.group(1), "file"
    if msg_type == "image":
        raw_image = re.search(r"(img_[A-Za-z0-9_\\-]+)", value)
        if raw_image:
            return raw_image.group(1), "image"
    return None, None


def parse_content_object(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _walk_content_values(value: Any) -> list[Any]:
    found: list[Any] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "content":
                found.append(item)
            found.extend(_walk_content_values(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_walk_content_values(item))
    return found


def flatten_post_text(content: Any) -> str:
    if not isinstance(content, dict):
        return ""
    locale = content.get("zh_cn") or content.get("en_us") or next(iter(content.values()), {})
    pieces: list[str] = []
    for line in locale.get("content", []) if isinstance(locale, dict) else []:
        line_text = ""
        for item in line:
            if isinstance(item, dict) and item.get("tag") in {"text", "md", "at", "code_inline"}:
                line_text += str(item.get("text", ""))
        if line_text:
            pieces.append(line_text)
    return "\n".join(pieces)


def find_message_id(payload: dict[str, Any]) -> str | None:
    for key in ("message_id", "messageId"):
        if isinstance(payload.get(key), str):
            return payload[key]
    data = payload.get("data")
    if isinstance(data, dict):
        return find_message_id(data)
    return None


def find_thread_id(payload: dict[str, Any]) -> str | None:
    if isinstance(payload.get("thread_id"), str):
        return payload["thread_id"]
    data = payload.get("data")
    if isinstance(data, dict):
        found = find_thread_id(data)
        if found:
            return found
    for value in payload.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    found = find_thread_id(item)
                    if found:
                        return found
    return None


def create_or_update_binding(state: BridgeState, lark: LarkClient, tmux: TmuxClient) -> Binding:
    topic = tmux.current_session()
    target_pane = tmux.current_pane()
    binding = state.binding_for_topic(topic)
    if not binding:
        chat_id = state.get_default_chat_id()
        if not chat_id:
            raise RuntimeError("No default chat configured. Run feishu-bridge bootstrap-chat first.")
        root_text = f"{topic}\n\nRemote Control attached."
        result = lark.send_text(chat_id, root_text, idempotency_key=idempotency_key(topic, "root"))
        root_id = find_message_id(result)
        if not root_id:
            raise RuntimeError("Could not read root message_id from lark-cli response")
        thread_id = find_thread_id(result)
        if not thread_id:
            try:
                thread_id = find_thread_id(lark.mget(root_id))
            except Exception:
                thread_id = None
        binding = Binding.create(topic=topic, chat_id=chat_id, root_message_id=root_id, thread_id=thread_id, target_pane=target_pane, default=True)
    else:
        binding.target_pane = target_pane
    binding.remote_control_active = True
    transcript = discover_transcript(tmux.pane_cwd(binding))
    if transcript:
        binding.transcript_path = str(transcript)
        binding.transcript_offset = transcript.stat().st_size
    state.upsert_binding(binding)
    return binding


def handle_inbound_event(state: BridgeState, lark: LarkClient, tmux: TmuxClient, event: dict[str, Any]) -> bool:
    event_id = extract_event_id(event)
    if not event_id or state.seen_inbound(event_id):
        return False
    if event_sender_is_bot(event):
        state.mark_inbound(event_id)
        return False
    chat_id = event_chat_id(event)
    message_id = event_message_id(event)
    enriched: dict[str, Any] | None = None
    binding = state.binding_for_message(chat_id, candidate_message_ids(event))
    if not binding and message_id:
        try:
            enriched = lark.mget(message_id)
            binding = state.binding_for_message(chat_id, candidate_message_ids(event, enriched))
        except Exception as exc:
            state.log(f"inbound mget failed event_id={event_id} chat_id={chat_id} error={exc}")
    if not binding:
        state.mark_inbound(event_id)
        return False
    if not binding.remote_control_active:
        state.log(f"inbound ignored detached event_id={event_id} chat_id={chat_id} topic={binding.topic}")
        state.mark_inbound(event_id)
        return False
    text = extract_text(event)
    if not text:
        resource_key, resource_type = extract_resource_key(event, enriched)
        if not resource_key and message_id and enriched is None:
            try:
                enriched = lark.mget(message_id)
                resource_key, resource_type = extract_resource_key(event, enriched)
            except Exception as exc:
                state.log(f"attachment mget failed event_id={event_id} chat_id={chat_id} topic={binding.topic} error={exc}")
        if resource_key and resource_type and message_id:
            try:
                target = state.state_dir / "attachments" / safe_name(binding.topic) / f"{safe_name(message_id)}-{safe_name(resource_key)}"
                path = lark.download_resource(message_id, resource_key, resource_type, target)
                text = f"Attached {resource_type} from Feishu: {path}"
            except Exception as exc:
                lark.reply_text(binding.root_message_id, "feishu-bridge could not download this attachment. Check bridge logs.")
                state.log(f"attachment download failed event_id={event_id} chat_id={chat_id} topic={binding.topic} error={exc}")
                return False
    if not text:
        lark.reply_text(binding.root_message_id, "feishu-bridge v1 only supports text replies.")
        state.log(f"unsupported inbound event_id={event_id} chat_id={chat_id} topic={binding.topic} message_type={event_message_type(event)}")
        state.mark_inbound(event_id)
        return False
    try:
        tmux.paste_input(binding, text)
    except Exception as exc:
        lark.reply_text(binding.root_message_id, "feishu-bridge could not deliver this reply to the local tmux session. Check bridge logs.")
        state.log(f"delivery failed event_id={event_id} chat_id={chat_id} topic={binding.topic} error={exc}")
        return False
    lark.add_ack_reaction(message_id)
    state.mark_inbound(event_id)
    state.log(f"delivered inbound event_id={event_id} chat_id={chat_id} topic={binding.topic}")
    return True


def discover_codex_transcript(cwd: str) -> Path | None:
    if not CODEX_SESSIONS_DIR.is_dir():
        return None
    resolved_cwd = str(Path(cwd).resolve())
    candidates: list[tuple[float, Path]] = []
    for path in CODEX_SESSIONS_DIR.rglob("*.jsonl"):
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True)[:40]:
        meta = read_codex_session_meta(path)
        if not meta:
            continue
        if str(meta.get("originator") or "") == "codex_exec":
            continue
        source = meta.get("source")
        if isinstance(source, dict) and "subagent" in source:
            continue
        file_cwd = meta.get("cwd")
        if isinstance(file_cwd, str) and str(Path(file_cwd).resolve()) == resolved_cwd:
            return path
    return None


def discover_claude_transcript(cwd: str) -> Path | None:
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None
    resolved_cwd = str(Path(cwd).resolve())
    candidates: list[tuple[float, Path]] = []
    for path in CLAUDE_PROJECTS_DIR.rglob("*.jsonl"):
        if "/subagents/" in str(path):
            continue
        try:
            candidates.append((path.stat().st_mtime, path))
        except OSError:
            continue
    for _, path in sorted(candidates, reverse=True)[:80]:
        file_cwd = read_claude_transcript_cwd(path)
        if isinstance(file_cwd, str) and str(Path(file_cwd).resolve()) == resolved_cwd:
            return path
    return None


def discover_transcript(cwd: str) -> Path | None:
    return discover_codex_transcript(cwd) or discover_claude_transcript(cwd)


def read_codex_session_meta(path: Path) -> dict[str, Any] | None:
    try:
        first_line = path.open(encoding="utf-8").readline()
    except OSError:
        return None
    try:
        data = json.loads(first_line)
    except json.JSONDecodeError:
        return None
    if data.get("type") != "session_meta":
        return None
    payload = data.get("payload")
    return payload if isinstance(payload, dict) else None


def read_claude_transcript_cwd(path: Path, max_lines: int = 80) -> str | None:
    try:
        with path.open(encoding="utf-8") as handle:
            for index, line in enumerate(handle):
                if index >= max_lines:
                    return None
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cwd = data.get("cwd")
                if isinstance(cwd, str) and cwd:
                    return cwd
    except OSError:
        return None
    return None


def poll_outbound_once(state: BridgeState, lark: LarkClient, tmux: TmuxClient) -> int:
    sent = 0
    bindings = state.load_bindings()
    changed = False
    for binding in bindings:
        if not binding.active or not binding.remote_control_active:
            continue
        try:
            tmux.ensure_pane_exists(binding)
            transcript = Path(binding.transcript_path).expanduser() if binding.transcript_path else discover_transcript(tmux.pane_cwd(binding))
            if not transcript or not transcript.exists():
                continue
            if str(transcript) != binding.transcript_path:
                binding.transcript_path = str(transcript)
                binding.transcript_offset = transcript.stat().st_size
                changed = True
                continue
            messages, new_offset = read_final_messages(transcript, binding.transcript_offset)
            binding.transcript_offset = new_offset
            changed = True
            for message_id, text in messages:
                outbound_id = f"{binding.topic}:{message_id}"
                if state.seen_outbound(outbound_id):
                    continue
                send_thread_text(lark, binding, text, outbound_id)
                state.mark_outbound(outbound_id)
                state.log(f"sent outbound topic={binding.topic} message_id={message_id}")
                sent += 1
        except Exception as exc:
            state.log(f"outbound poll failed topic={binding.topic} error={exc}")
    if changed:
        state.save_bindings(bindings)
    return sent


def read_final_messages(path: Path, offset: int) -> tuple[list[tuple[str, str]], int]:
    if is_claude_transcript(path):
        return read_claude_final_messages(path, offset)
    return read_codex_final_messages(path, offset)


def is_claude_transcript(path: Path) -> bool:
    try:
        path.relative_to(CLAUDE_PROJECTS_DIR)
        return True
    except ValueError:
        return ".claude/projects" in str(path)


def read_codex_final_messages(path: Path, offset: int) -> tuple[list[tuple[str, str]], int]:
    size = path.stat().st_size
    if offset > size:
        offset = 0
    messages: list[tuple[str, str]] = []
    with path.open(encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            message_id, text = parse_codex_final_entry(entry)
            if message_id and text:
                messages.append((message_id, text))
        new_offset = handle.tell()
    return messages, new_offset


def parse_codex_final_entry(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None, None
    if entry.get("type") == "event_msg" and payload.get("type") == "task_complete":
        text = payload.get("last_agent_message")
        turn_id = str(payload.get("turn_id") or entry.get("timestamp") or "")
        return turn_id, text if isinstance(text, str) and text else None
    return None, None


def read_claude_final_messages(path: Path, offset: int) -> tuple[list[tuple[str, str]], int]:
    size = path.stat().st_size
    if offset > size:
        offset = 0
    groups: dict[str, dict[str, Any]] = {}
    with path.open(encoding="utf-8") as handle:
        handle.seek(offset)
        for line in handle:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            parts = claude_final_entry_parts(entry)
            if not parts:
                continue
            group = groups.setdefault(parts["group_id"], {"texts": [], "text_id": parts["message_id"], "fallbacks": [], "fallback_id": parts["message_id"]})
            if parts["texts"]:
                group["texts"].extend(parts["texts"])
                group["text_id"] = parts["message_id"]
            elif parts["fallbacks"]:
                group["fallbacks"].extend(parts["fallbacks"])
                group["fallback_id"] = parts["message_id"]
        new_offset = handle.tell()
    messages: list[tuple[str, str]] = []
    for group in groups.values():
        if group["texts"]:
            messages.append((group["text_id"], "\n\n".join(group["texts"])))
        elif group["fallbacks"]:
            messages.append((group["fallback_id"], "\n\n".join(group["fallbacks"])))
    return messages, new_offset


def parse_claude_final_entry(entry: dict[str, Any]) -> tuple[str | None, str | None]:
    parts = claude_final_entry_parts(entry)
    if not parts:
        return None, None
    texts = parts["texts"] or parts["fallbacks"]
    if not texts:
        return None, None
    return parts["message_id"], "\n\n".join(texts)


def claude_final_entry_parts(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry.get("type") != "assistant":
        return None
    message = entry.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    texts: list[str] = []
    fallbacks: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    if not texts and message.get("stop_reason") == "end_turn":
        for item in content:
            if not isinstance(item, dict) or item.get("type") != "thinking":
                continue
            thinking = item.get("thinking")
            if isinstance(thinking, str) and thinking.strip():
                fallbacks.append(thinking.strip())
    if not texts and not fallbacks:
        return None
    message_id = str(entry.get("uuid") or entry.get("timestamp") or "")
    message_obj_id = message.get("id")
    group_id = str(message_obj_id) if isinstance(message_obj_id, str) and message_obj_id else message_id
    return {"group_id": group_id, "message_id": message_id, "texts": texts, "fallbacks": fallbacks}


def send_thread_text(lark: LarkClient, binding: Binding, text: str, artifact_id: str) -> None:
    for index, chunk in enumerate(split_text(text), start=1):
        lark.reply_post(binding.root_message_id, markdown_to_feishu_post(chunk), idempotency_key=idempotency_key(binding.topic, artifact_id, str(index)))


def markdown_to_feishu_post(markdown: str) -> dict[str, Any]:
    lines: list[list[dict[str, Any]]] = []
    code_block: list[str] | None = None
    in_code = False
    for raw_line in markdown.splitlines() or [""]:
        stripped = raw_line.lstrip()
        if stripped.startswith("```"):
            if not in_code:
                code_block = ["```"]
                in_code = True
                continue
            assert code_block is not None
            code_block.append("```")
            lines.append([{"tag": "md", "text": "\n".join(code_block)}])
            code_block = None
            in_code = not in_code
            continue
        if in_code:
            assert code_block is not None
            code_block.append(raw_line)
            continue
        if not raw_line:
            lines.append([{"tag": "text", "text": " "}])
            continue
        tag = "text" if should_preserve_line_as_text(raw_line) else "md"
        lines.append([{"tag": tag, "text": raw_line}])
    if code_block is not None:
        lines.append([{"tag": "md", "text": "\n".join(code_block)}])
    return {"zh_cn": {"content": lines}}


def should_preserve_line_as_text(line: str) -> bool:
    stripped = line.lstrip()
    if line != stripped:
        return True
    if not stripped:
        return True
    return False


def consume_events() -> subprocess.Popen[str]:
    command = [
        "lark-cli",
        "event",
        "consume",
        EVENT_KEY,
        "--as",
        "bot",
        "--jq",
        "{event_id, chat_id, message_id, message_type, content, sender_id, sender, root_id, parent_id, thread_id, message}",
    ]
    return subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
        start_new_session=True,
    )


def cmd_run(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    state.ensure()
    lark = LarkClient()
    tmux = TmuxClient()
    ok, reason = lark.check()
    if not ok:
        raise SystemExit(reason)
    if not state.get_default_chat_id() and not state.load_bindings():
        state.log("startup without default chat or bindings")
    proc: subprocess.Popen[str] | None = None
    backoff = 1.0
    stopping = False

    def stop(_signum: int, _frame: Any) -> None:
        nonlocal stopping
        stopping = True
        if proc and proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    last_outbound = 0.0

    try:
        state.save_runner_heartbeat()
        while not stopping:
            if proc is None or proc.poll() is not None:
                proc = consume_events()
                state.log(f"event consumer started pid={proc.pid}")
            state.save_runner_heartbeat(event_consumer_pid=proc.pid if proc else None)
            assert proc.stdout is not None
            readable, _, _ = select.select([proc.stdout], [], [], 1.0)
            line = proc.stdout.readline() if readable else ""
            if line:
                try:
                    handle_inbound_event(state, lark, tmux, json.loads(line))
                    backoff = 1.0
                except Exception as exc:
                    state.log(f"inbound processing error={exc}")
            elif proc.poll() is not None:
                state.log(f"event consumer exited code={proc.returncode}; restart in {backoff:.1f}s")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                proc = None
            now = time.time()
            if now - last_outbound >= args.outbound_poll_interval:
                poll_outbound_once(state, lark, tmux)
                last_outbound = now
    finally:
        state.clear_runner_heartbeat()
    return 0


def ack_bootstrap_message(lark: LarkClient, event: dict[str, Any]) -> bool:
    message_id = event_message_id(event)
    if not message_id:
        return False
    lark.add_ack_reaction(message_id)
    return True


def cmd_bootstrap_chat(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    if args.chat_id:
        state.save_default_chat_id(args.chat_id)
        print(f"Saved default chat: {args.chat_id}")
        return 0
    print("Waiting for a Feishu message that reaches the bot. Press Ctrl-C to cancel.", file=sys.stderr)
    lark = LarkClient()
    proc = consume_events()
    assert proc.stdout is not None
    try:
        for line in proc.stdout:
            event = json.loads(line)
            chat_id = event_chat_id(event)
            if not chat_id:
                continue
            print(f"Candidate default chat: {chat_id}")
            confirmed = "y" if args.yes else input("Save this chat as the default for new sessions? [y/N] ").strip().lower()
            if confirmed == "y":
                state.save_default_chat_id(chat_id)
                try:
                    if ack_bootstrap_message(lark, event):
                        print("Acknowledged bootstrap message with reaction.")
                    else:
                        print("Saved default chat, but bootstrap event had no message id to acknowledge.", file=sys.stderr)
                except Exception as exc:
                    print(f"Saved default chat, but failed to acknowledge bootstrap message: {exc}", file=sys.stderr)
                print(f"Saved default chat: {chat_id}")
                return 0
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
    return 1


def cmd_attach(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    binding = create_or_update_binding(state, LarkClient(), TmuxClient())
    print(f"Attached {binding.topic} to Feishu root {binding.root_message_id}")
    runner = state.load_runner_status()
    if not runner["running"]:
        print("Warning: Feishu bridge runner is not detected. Start it with `everywhere feishu run`.", file=sys.stderr)
    return 0


def cmd_detach(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    topic = TmuxClient().current_session()
    binding = state.set_remote_control(topic, False)
    print(f"Detached {binding.topic}; binding preserved at root {binding.root_message_id}")
    return 0


def cmd_notify(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    topic = TmuxClient().current_session()
    binding = state.binding_for_topic(topic)
    if not binding:
        raise RuntimeError(f"No binding for current tmux session '{topic}'. Run feishu-bridge attach first.")
    message = args.message if args.message is not None else Path(args.message_file).read_text(encoding="utf-8")
    send_thread_text(LarkClient(), binding, message, idempotency_key(topic, "manual", message))
    print(f"Sent manual message for {topic} to root {binding.root_message_id}")
    return 0


def binding_status_payload(binding: Binding) -> dict[str, Any]:
    return {
        "topic": binding.topic,
        "chat_id": binding.chat_id,
        "root_message_id": binding.root_message_id,
        "thread_id": binding.thread_id,
        "title": binding.title,
        "active": binding.active,
        "remote_control_active": binding.remote_control_active,
        "target_pane": binding.target_pane,
        "default": binding.default,
        "transcript_path": binding.transcript_path,
        "transcript_offset": binding.transcript_offset,
        "created_at": binding.created_at,
        "updated_at": binding.updated_at,
    }


def cmd_current(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    topic = TmuxClient().current_session()
    binding = state.binding_for_topic(topic, require_active=False)
    if not binding:
        payload = {
            "topic": topic,
            "bound": False,
            "error": f"No binding for current tmux session '{topic}'. Run feishu-bridge attach first.",
        }
        if args.json:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 1
        raise RuntimeError(payload["error"])
    payload = binding_status_payload(binding)
    payload["bound"] = True
    payload["runner"] = state.load_runner_status()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        rc = "attached" if binding.remote_control_active else "detached"
        marker = "active" if binding.active else "inactive"
        print(f"{binding.topic}: {rc}, {marker}, chat={binding.chat_id}, root={binding.root_message_id}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = BridgeState(args.state_dir)
    lark = LarkClient()
    ok, reason = lark.check()
    default_chat = state.get_default_chat_id() or "-"
    runner = state.load_runner_status()
    runner_label = "running" if runner["running"] else "not running"
    if runner["pid"]:
        runner_label += f", pid={runner['pid']}"
    if runner["age_seconds"] is not None:
        runner_label += f", heartbeat_age={runner['age_seconds']:.1f}s"
    print(f"State: {state.state_dir}")
    print(f"lark-cli: {reason}")
    print(f"Runner: {runner_label}")
    print(f"Default chat: {default_chat}")
    print(f"Bindings: {len(state.load_bindings())}")
    for binding in state.load_bindings():
        rc = "attached" if binding.remote_control_active else "detached"
        marker = "active" if binding.active else "inactive"
        transcript = binding.transcript_path or "-"
        target_pane = binding.target_pane or "-"
        print(f"- {binding.topic}: {rc}, {marker}, pane={target_pane}, chat={binding.chat_id}, root={binding.root_message_id}, transcript={transcript}")
    return 0 if ok else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="feishu-bridge", description="Bridge Feishu threads and local tmux agent sessions")
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run the long-lived bridge")
    run.add_argument("--outbound-poll-interval", type=float, default=2.0)
    run.set_defaults(func=cmd_run)

    bootstrap = subparsers.add_parser("bootstrap-chat", help="Capture and save the default Feishu chat")
    bootstrap.add_argument("--chat-id", help="Save this chat id directly")
    bootstrap.add_argument("--yes", action="store_true", help="Accept the first observed chat without prompting")
    bootstrap.set_defaults(func=cmd_bootstrap_chat)

    attach = subparsers.add_parser("attach", help="Attach the current tmux session to Feishu remote control")
    attach.set_defaults(func=cmd_attach)

    detach = subparsers.add_parser("detach", help="Detach the current tmux session but keep its binding")
    detach.set_defaults(func=cmd_detach)

    notify = subparsers.add_parser("notify", help="Send a manual message for the current tmux session")
    group = notify.add_mutually_exclusive_group(required=True)
    group.add_argument("--message")
    group.add_argument("--message-file")
    notify.set_defaults(func=cmd_notify)

    current = subparsers.add_parser("current", help="Show the current tmux session binding")
    current.add_argument("--json", action="store_true", help="Print machine-readable binding JSON")
    current.set_defaults(func=cmd_current)

    status = subparsers.add_parser("status", help="Show bridge state and self-checks")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
