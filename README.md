# Everywhere

Everywhere contains local remote-control transports for agent sessions.

Feishu is the first bridge. The repository boundary is intentionally broader:

- Provider config belongs in `.codex`, `.claude`, or other provider-specific directories.
- Bridge runtime code belongs here.
- Swarm remains a local orchestrator-worker runtime, not a transport layer.

## Install

Run the installer with npm:

```bash
npx @jas0n1ee/everywhere install
```

The installer is idempotent. It checks local prerequisites, creates bridge state under
`~/.everywhere/feishu-bridge/`, and prints the next setup steps.

For regular use, install the CLI globally:

```bash
npm install -g @jas0n1ee/everywhere
everywhere install
```

During local development from a checkout, use the repo binary directly:

```bash
./bin/everywhere install
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
```

`feishu-bridge <command>` is also exposed as a direct alias for scripts or local
debugging.

See [docs/ONBOARDING.md](docs/ONBOARDING.md) for `lark-cli` setup, Feishu app
requirements, bootstrap, attach, and troubleshooting.

## Update

If you use `npx`, run the latest package explicitly:

```bash
npx @jas0n1ee/everywhere@latest install
```

If you installed globally:

```bash
npm install -g @jas0n1ee/everywhere@latest
everywhere install
```

If you are using a git checkout:

```bash
git pull
./bin/everywhere install
```

Re-running `install` after an update is safe. Existing Feishu bridge bindings and
logs remain under `~/.everywhere/feishu-bridge/`.
