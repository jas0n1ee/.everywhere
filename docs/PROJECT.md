# Everywhere Project Notes

## Purpose

Everywhere is a local remote-control transport layer for agent sessions.

It lets a human temporarily control and observe a local terminal agent session from an external chat surface. Feishu is the first bridge, but the project should be structured so Telegram, Slack, email, or other transports can be added later without becoming provider-specific config.

## Current Boundary

- Bridge/runtime code belongs in `.everywhere`.
- Provider prompts and provider-specific settings belong in `.codex`, `.claude`, or similar provider directories.
- Swarm remains a local orchestrator-worker runtime.
- Remote control is not Swarm task state.
- Provider prompts should keep remote-control behavior mostly out-of-band.
  Remote-control forwarding is bridge behavior, not something agents should reason about every turn.
- `NOTIFY HUMAN` should not be used as a magic phrase. Explicit commands such as `everywhere feishu notify` are the escalation surface.
- Everywhere remains a Python runtime/tool. Agent-facing behavior should live in an Everywhere Skill.
- Agents can discover the current Feishu thread with `everywhere feishu current --json` and upload artifacts by calling `lark-cli im +messages-reply --image/--file` from the artifact directory.
- Feishu thread topic maps to one tmux session.
- The tmux session name is the topic name.
- Window `0` must look like an agent window. By default, names starting with `orchestrator`, `claude`, `codex`, or `node` are accepted.
- Pane `0` in window `0` is the agent pane that receives remote-control input.

## Current Feishu Bridge Commands

- `run`: long-lived bridge process; consumes Feishu message events and polls provider transcripts.
- `bootstrap-chat`: saves the default chat id used when creating a new topic thread.
- `attach`: binds the current tmux session to a Feishu thread and enables remote control.
- `detach`: pauses inbound and outbound remote-control traffic while preserving the binding.
- `notify`: manually sends a message to the current session binding.
- `status`: prints self-checks, default chat, and known bindings.

## Implemented

- State under `~/.everywhere/feishu-bridge/`.
- Default chat resolution via environment or saved config.
- Binding storage for topic, chat id, root message id, optional thread id, transcript path, offsets, and remote-control state.
- Inbound Feishu text/post routing into tmux window `0`.
- Inbound attachment download for supported image/file resource keys, injecting the saved local path into tmux.
- Attachments are a supported Feishu bridge v1 feature, not a transport-neutral Everywhere abstraction yet.
- Inbound ACK reaction after successful delivery.
- Detached state ignores inbound events and suppresses outbound forwarding.
- Codex outbound capture from JSONL `task_complete.last_agent_message`.
- Claude outbound capture from JSONL assistant text blocks.
- Feishu post output for basic Markdown rendering.
- Text splitting for long outbound messages.
- Event and outbound-message dedupe.
- Basic restart loop for `lark-cli event consume`.
- Python packaging through `pyproject.toml`, with `everywhere` and `feishu-bridge` console scripts.
- `skills/everywhere/SKILL.md` plus `.skillignore` so `npx skills add` can install only agent-facing guidance.
- Unit tests for state, binding lookup, dedupe, text splitting, tmux paste, Codex/Claude transcript parsing, Markdown post conversion, and attachment key extraction.

## Known Gaps

- The bridge is still implemented as one Feishu-specific Python file.
- There is no shared transport interface for future non-Feishu bridges.
- There is no provider abstraction beyond path-based Codex/Claude transcript detection.
- Claude final-answer detection is heuristic; transcript hooks may be better.
- Codex hook support has not been researched or implemented.
- Markdown-to-Feishu post rendering is basic and still needs edge-case review.
- No E2E test harness exists for a real Feishu test chat.
- No process supervisor config exists.
- No structured config schema or migration layer exists.
- Logs are metadata-oriented, but the privacy/security model is not documented.
- There is no documented push/release workflow.

## Human Escalation

Remote-control delivery and task-state paging should be designed separately.

Current working interpretation:

- When remote control is attached, assistant final answers are forwarded by the bridge automatically.
- Agents should not need to emit `NOTIFY HUMAN` only to make Feishu delivery happen.
- Agents should use explicit commands for human paging, such as `everywhere feishu notify`.
- Rich handoff is not a separate command. If an agent needs to send a local artifact, use the Everywhere Skill workflow: inspect the current binding, then call `lark-cli` from the artifact directory with a relative file name.

## Review Questions

- Should Everywhere be only a transport runtime, or also own provider transcript/hook adapters?
- Should `attach` create a Feishu thread automatically, or should binding require an explicit thread created by the human?
- Should provider prompts mention remote control at all?
- Should `notify` remain as a stable command if automatic final-answer forwarding is the primary behavior?
- Should attachments be part of v1 or documented as experimental?
- Should outbound final-answer capture use provider hooks instead of transcript polling?
- Should bridge state live only under `~/.everywhere`, or should project-local state be supported for test/dev?
- Should Feishu Markdown rendering use post messages, cards, or another richer format?
- Should detached bindings still show in `status` by default?
- Should old test bindings be garbage-collected or archived?

## Development Check

```bash
everywhere check
```

This command runs:

- `python3 tests/run_feishu_bridge_tests.py`
- `python3 -m pip wheel . -w <tempdir> --no-deps`
- `npx skills add . --list --full-depth`
