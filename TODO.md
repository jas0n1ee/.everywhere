# Everywhere TODO

## Decisions Made

- Everywhere is a Python tool package, installed with `uv tool install`, `pipx`, or `pip --user`.
- Stable public commands are:
  - `everywhere install`
  - `everywhere feishu run`
  - `everywhere feishu bootstrap-chat`
  - `everywhere feishu attach`
  - `everywhere feishu detach`
  - `everywhere feishu notify`
  - `everywhere feishu status`
  - direct alias: `feishu-bridge <command>`
- Feishu remote-control delivery is transport behavior, not Swarm runtime behavior.
- When remote control is attached, provider final answers are expected to be forwarded by transcript/hook capture.
- Agents should not depend on `NOTIFY HUMAN` just to deliver normal final answers to Feishu.
- Provider prompts should keep remote-control behavior mostly out-of-band.
  If mentioned at all, it should only be a tiny command-use hint for explicit attach/notify requests.
- Replace `NOTIFY HUMAN` as a magic phrase with explicit bridge commands such as `everywhere feishu notify`.
- Keep Everywhere as a Python runtime/tool and expose an Everywhere Skill for agent-facing usage guidance.
- For agent-to-human artifact delivery, first add `everywhere feishu current --json`; let the agent call `lark-cli` directly for upload in the short term.
- `bootstrap-chat` acknowledges the bootstrap Feishu message with a reaction after saving the default chat.
- `npx skills add` installs the isolated `skills/everywhere` Skill without copying runtime code.

## Remote Control / Feishu Bridge

- Decide how non-Feishu bridges should share common code with `feishu_bridge.py`.
  Feishu is the first bridge, not the whole Everywhere transport layer.
- Decide whether attachments are v1 bridge behavior or a Feishu-specific extension.
- Add outbound file/image delivery for agent-to-human communication.
  When the agent needs to send a local file or image to the human, Feishu bridge should upload it into the attached Feishu thread.
  `lark-cli im +messages-reply` already supports `--image <local path>` and `--file <local path>`.
- Decide whether the review gate should be documentation only, a local checklist command, or a test/lint command that must pass before bridge and provider-prompt commits.
