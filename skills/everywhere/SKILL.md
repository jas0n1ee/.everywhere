---
name: everywhere
description: Use when the user asks to attach or control a local tmux agent session through Feishu, inspect the current Feishu bridge topic, notify the human through the attached thread, or send local files/images from the agent to the human through Feishu.
---

# Everywhere

Everywhere is the local remote-control transport for agent sessions. It is a runtime tool, not provider-specific prompt logic.

Use it only when the user asks for Feishu remote control, wants a human notification through the attached Feishu thread, asks for the current bridge topic, or asks you to send a local file/image to the human.

## Commands

Check current binding from inside the target tmux session:

```bash
everywhere feishu current --json
```

Attach the current tmux session to Feishu remote control:

```bash
everywhere feishu attach
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

When the human asks for a local artifact, upload it through the current attached Feishu thread:

```bash
everywhere feishu upload --image /path/to/image.png --message "optional caption"
everywhere feishu upload --file /path/to/file.pdf --message "optional caption"
```

If you need to inspect the target first, run:

```bash
everywhere feishu current --json
```

Only upload an artifact when the human explicitly asks for it or the artifact is clearly part of the requested deliverable. Do not auto-upload arbitrary paths that appear in a normal final answer.

If no binding exists, ask the human to attach remote control or run `everywhere feishu attach` from the target tmux session when appropriate.
