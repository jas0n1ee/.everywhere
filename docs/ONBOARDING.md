# Everywhere Feishu Bridge Onboarding

This guide gets a local tmux agent session connected to a Feishu thread so a
human can observe and control it remotely.

## What Everywhere Provides

Everywhere is a transport runtime. The current bridge is Feishu:

- inbound Feishu replies are pasted into pane `0` of tmux window `0`
- assistant final replies are forwarded back to the Feishu thread from provider transcripts
- manual notifications can be sent with `feishu-bridge notify`

Swarm remains separate. Swarm may call the bridge, but Everywhere does not own worker orchestration.

## Install

Preferred user install:

```bash
uv tool install git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

If `everywhere` is not on your shell path after installation, run:

```bash
uv tool update-shell
```

The installer is idempotent. It checks local tools, creates
`~/.everywhere/feishu-bridge/`, and prints the next setup steps. It does not
delete existing bridge bindings, logs, or local Feishu state.

It also installs the Everywhere Skill globally with:

```bash
npx skills add jas0n1ee/.everywhere --global --full-depth --agent codex claude-code --skill everywhere --yes --copy
```

The Skill lives under `skills/everywhere/` and has a `.skillignore` whitelist so
the installed Skill contains agent-facing instructions, not the Python runtime
code.

If you use `pipx` instead of `uv`:

```bash
pipx install git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

Fallback user install:

```bash
python3 -m pip install --user git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

During local development from a repo checkout:

```bash
uv tool install --editable .
everywhere install --skill-source .
```

The Python package exposes:

```bash
everywhere install
everywhere feishu <command>
feishu-bridge <command>
```

The stable Feishu bridge command set is:

```bash
everywhere feishu run
everywhere feishu bootstrap-chat
everywhere feishu attach
everywhere feishu detach
everywhere feishu notify
everywhere feishu status
everywhere feishu current
```

The bridge stores state under:

```text
~/.everywhere/feishu-bridge/
```

## Update

For `uv tool` installs:

```bash
uv tool upgrade jas0n1ee-everywhere
everywhere install
```

For `pipx` installs:

```bash
pipx upgrade jas0n1ee-everywhere
everywhere install
```

For `pip --user` installs:

```bash
python3 -m pip install --user --upgrade git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

Run `everywhere install` after updating. It is safe to run repeatedly and keeps
existing state in place.

## lark-cli Setup

The Feishu bridge depends on `lark-cli`.

First-time app setup:

```bash
lark-cli config init --new
```

For bot operations, the app credentials are enough after the app has the required scopes enabled in the Feishu developer console. Do not run `auth login` for bot identity.

For user-scoped operations, authorize only the required scope:

```bash
lark-cli auth login --scope "<missing_scope>"
```

Useful checks:

```bash
lark-cli event --help
lark-cli im +messages-send --help
```

If `lark-cli` returns a permission error, inspect the missing scope and console URL in the error output. Enable bot scopes in the developer console; use `auth login --scope ...` only for user identity.

## Required Feishu App Capabilities

The bridge uses `lark-cli` for:

- receiving message events: `lark-cli event consume im.message.receive_v1`
- sending messages and replies as bot
- adding ACK reactions
- downloading supported message resources for attachments

The app must be able to receive message events for the target chat and send bot messages into that chat.

## Bootstrap A Default Chat

`attach` creates a root Feishu message in the default chat. Configure that chat
first.

If you already know the chat id:

```bash
feishu-bridge bootstrap-chat --chat-id <chat_id>
```

Equivalent package form:

```bash
everywhere feishu bootstrap-chat --chat-id <chat_id>
```

If you want the bridge to capture the first observed chat from message events:

```bash
feishu-bridge bootstrap-chat
```

Then send a message in the target Feishu chat and follow the prompt. For
non-interactive bootstrap, accept the first observed chat:

```bash
feishu-bridge bootstrap-chat --yes
```

When bootstrap saves a chat from an observed Feishu message, the bot adds an ACK
reaction to that message so the human can see that setup completed.

You can also set the default chat for a process with:

```bash
export FEISHU_BRIDGE_CHAT_ID=<chat_id>
```

## Run The Bridge

Start the long-lived bridge process:

```bash
feishu-bridge run
```

Equivalent package form:

```bash
everywhere feishu run
```

It consumes Feishu message events and polls provider transcripts for outbound replies.

Common development form:

```bash
feishu-bridge run --outbound-poll-interval 2
```

Keep this process running while remote control is needed.

## Attach A tmux Session

`attach` must run inside the target tmux session.

Requirements:

- you are inside tmux
- tmux window `0` is the agent window
- pane `0` in window `0` is the agent pane
- window `0` name starts with `orchestrator`, `claude`, `codex`, or `node`
- a default Feishu chat is configured
- `feishu-bridge run` is running or will be started soon

From a pane inside the target tmux session:

```bash
feishu-bridge attach
```

Equivalent package form:

```bash
everywhere feishu attach
```

The bridge will:

1. read the current tmux session name as the topic
2. validate window `0`
3. create or update a binding under `~/.everywhere/feishu-bridge/`
4. send a root Feishu message like:

```text
<topic>

Remote Control attached.
```

Human replies in that Feishu thread are pasted into pane `0` of tmux window `0`.

If your agent window has a different naming convention, set:

```bash
export FEISHU_BRIDGE_AGENT_WINDOW_PREFIXES="orchestrator,claude,codex,node,my-agent"
```

## Manual Notify

Send a short message to the current session binding:

```bash
feishu-bridge notify --message "Need human decision: ..."
```

Send a longer Markdown handoff:

```bash
feishu-bridge notify --message-file /path/to/handoff.md
```

## Agent Artifact Upload

When an agent needs to send a local file or image to the human, first identify
the current attached Feishu thread:

```bash
everywhere feishu current --json
```

Use the returned `root_message_id` with `lark-cli`. `lark-cli` requires
`--image` and `--file` paths to be relative to the current working directory, so
`cd` to the artifact directory first and pass only the file name:

```bash
cd /path/to
lark-cli im +messages-reply --message-id <root_message_id> --reply-in-thread --image image.png --as bot
lark-cli im +messages-reply --message-id <root_message_id> --reply-in-thread --file file.pdf --as bot
```

Do this only when the human explicitly asks for an artifact or when the artifact
is clearly part of the requested delivery.

Attachments are a supported Feishu bridge v1 feature:

- inbound Feishu files/images are downloaded under `~/.everywhere/feishu-bridge/attachments/<topic>/` and their local paths are pasted into the agent session
- outbound local files/images are sent by the agent with `lark-cli im +messages-reply --image/--file` after resolving the current binding
- this is not yet a transport-neutral Everywhere attachment abstraction

## Detach And Status

Pause remote control while keeping the binding:

```bash
feishu-bridge detach
```

Inspect setup and bindings:

```bash
feishu-bridge status
```

## Troubleshooting

If `attach` says there is no default chat, run `bootstrap-chat`.

If `attach` says it must run inside tmux, switch to the target tmux session and run it from there.

If inbound replies do not arrive, confirm `feishu-bridge run` is running and `lark-cli event --help` works.

If outbound replies do not arrive, run `feishu-bridge status` and confirm the binding has a transcript path.

Bridge logs live at:

```text
~/.everywhere/feishu-bridge/bridge.log
```
