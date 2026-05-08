# Everywhere Feishu Bridge Onboarding

This guide gets a local tmux agent session connected to a Feishu thread so a
human can observe and control it remotely.

## What Everywhere Provides

Everywhere is a transport runtime. The current bridge is Feishu:

- inbound Feishu replies are pasted into the orchestrator pane in tmux window `0`
- assistant final replies are forwarded back to the Feishu thread from provider transcripts
- manual notifications can be sent with `feishu-bridge notify`

Swarm remains separate. Swarm may call the bridge, but Everywhere does not own worker orchestration.

## Install

Preferred one-time install check:

```bash
npx @jas0n1ee/everywhere install
```

The installer is idempotent. It checks local tools, creates
`~/.everywhere/feishu-bridge/`, and prints the next setup steps. It does not
delete existing bridge bindings, logs, or local Feishu state.

For persistent local use, install it globally:

```bash
npm install -g @jas0n1ee/everywhere
everywhere install
```

During local development from a repo checkout, run:

```bash
./bin/everywhere install
```

or add the repo `bin` directory to your shell PATH:

```bash
export PATH="/path/to/.everywhere/bin:$PATH"
```

The package exposes:

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
```

The bridge stores state under:

```text
~/.everywhere/feishu-bridge/
```

## Update

For `npx` usage, request the latest package when you want a fresh copy:

```bash
npx @jas0n1ee/everywhere@latest install
```

For a global install:

```bash
npm install -g @jas0n1ee/everywhere@latest
everywhere install
```

For a git checkout:

```bash
git pull
./bin/everywhere install
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
- tmux window `0` is the agent/orchestrator window
- pane `0` in window `0` is the orchestrator pane
- window `0` name starts with `orchestrator`
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

## Manual Notify

Send a short message to the current session binding:

```bash
feishu-bridge notify --message "Need human decision: ..."
```

Send a longer Markdown handoff:

```bash
feishu-bridge notify --message-file /path/to/handoff.md
```

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
