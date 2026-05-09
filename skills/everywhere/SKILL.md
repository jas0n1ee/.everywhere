---
name: everywhere
description: Use when the user asks to attach or control a local tmux agent session through Feishu, inspect the current Feishu bridge topic, notify the human through the attached thread, or send local files/images from the agent to the human through Feishu.
---

# Everywhere

Everywhere is the local remote-control transport for agent sessions. It is a runtime tool, not provider-specific prompt logic.

Use it only when the user asks for Feishu remote control, wants a human notification through the attached Feishu thread, asks for the current bridge topic, or asks you to send a local file/image to the human.

## Commands

`/everywhere` is a human intent, not a shell command and not a command to
echo back to the user. When the human asks you to run `/everywhere`, the agent
must enable Feishu remote control by executing these local shell commands from
the target agent pane:

```bash
everywhere feishu status
everywhere feishu current --json || true
everywhere feishu attach
```

After `attach`, verify that the binding exists:

```bash
everywhere feishu current --json
everywhere feishu status
```

Treat `bound: true`, `remote_control_active: true`, and a non-empty
`target_pane` as the success condition. If the runner is not active, start it:

```bash
everywhere feishu run
```

When the human asks you to run `/everywhere detach`, detach the current tmux
session from Feishu remote control:

```bash
everywhere feishu detach
```

Check current binding from inside the target tmux session:

```bash
everywhere feishu current --json
```

Attach the current tmux session to Feishu remote control:

```bash
everywhere feishu attach
```

`attach` binds the current tmux pane. Run it from the agent pane that should
receive remote-control input.

Do not use a bare `tmux display-message -p '#{pane_id}'` to decide whether
`attach` targeted the right pane; it can report the tmux client's current pane
instead of the shell command's pane. Prefer `everywhere feishu current --json`.
If you must inspect tmux directly, target the pane explicitly:

```bash
tmux display-message -p -t "$TMUX_PANE" '#S:#I.#P #{pane_id} #{pane_current_command} #{pane_active}'
tmux list-panes -a -F '#S:#{window_index}.#{pane_index} #{pane_id} active=#{pane_active} cmd=#{pane_current_command}'
```

Send a short notification:

```bash
everywhere feishu notify --message "<summary and decision needed>"
```

Send a longer Markdown notification:

```bash
everywhere feishu notify --message-file <path>
```

Inspect bridge state:

```bash
everywhere feishu status
```

## Send Files Or Images

When the human asks for a local artifact, first inspect the current binding:

```bash
everywhere feishu current --json
```

If `bound` is true, use the returned `root_message_id`.

`lark-cli` requires `--image` and `--file` paths to be relative to the current working directory. `cd` to the artifact directory first and pass only the file name:

```bash
cd /path/to
lark-cli im +messages-reply --message-id <root_message_id> --reply-in-thread --image image.png --as bot
lark-cli im +messages-reply --message-id <root_message_id> --reply-in-thread --file file.pdf --as bot
```

Only upload an artifact when the human explicitly asks for it or the artifact is clearly part of the requested deliverable. Do not auto-upload arbitrary paths that appear in a normal final answer.

If no binding exists, ask the human to attach remote control or run `everywhere feishu attach` from the target tmux session when appropriate.
