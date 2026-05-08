# Everywhere

Everywhere contains local remote-control transports for agent sessions.

Feishu is the first bridge. The repository boundary is intentionally broader:

- Provider config belongs in `.codex`, `.claude`, or other provider-specific directories.
- Bridge runtime code belongs here.
- Swarm remains a local orchestrator-worker runtime, not a transport layer.

## Install

Install the CLI as a Python user tool:

```bash
uv tool install git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

If `everywhere` is not on your shell path after installation, run:

```bash
uv tool update-shell
```

The installer is idempotent. It checks local prerequisites, creates bridge state under
`~/.everywhere/feishu-bridge/`, installs the Everywhere Skill with `npx skills add`,
and prints the next setup steps.

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

During local development from a checkout:

```bash
uv tool install --editable .
everywhere install
```

## Feishu Bridge

Configure `lark-cli`, save a default Feishu chat, start the bridge, then attach
from inside the tmux session you want to control:

```bash
everywhere feishu bootstrap-chat --chat-id <chat_id>
everywhere feishu run
everywhere feishu attach
```

Stable public commands:

```bash
everywhere install
everywhere feishu run
everywhere feishu bootstrap-chat
everywhere feishu attach
everywhere feishu detach
everywhere feishu notify
everywhere feishu status
everywhere feishu current
```

`feishu-bridge <command>` is also exposed as a direct alias for scripts or local
debugging.

The installed Skill teaches agents to use `everywhere feishu current --json`
and then call `lark-cli im +messages-reply` when the human asks for a local
file or image artifact.

See [docs/ONBOARDING.md](docs/ONBOARDING.md) for `lark-cli` setup, Feishu app
requirements, bootstrap, attach, and troubleshooting.

## Update

If you installed with `uv tool`:

```bash
uv tool upgrade jas0n1ee-everywhere
everywhere install
```

If you installed with `pipx`:

```bash
pipx upgrade jas0n1ee-everywhere
everywhere install
```

If you installed with `pip --user`:

```bash
python3 -m pip install --user --upgrade git+https://github.com/jas0n1ee/.everywhere.git
everywhere install
```

Re-running `install` after an update is safe. Existing Feishu bridge bindings and
logs remain under `~/.everywhere/feishu-bridge/`.
