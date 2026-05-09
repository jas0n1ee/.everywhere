# Everywhere

Everywhere contains local remote-control transports for agent sessions.

Feishu is the first bridge. The repository boundary is intentionally broader:

- Provider config belongs in `.codex`, `.claude`, or other provider-specific directories.
- Bridge runtime code belongs here.
- Swarm remains a local orchestrator-worker runtime, not a transport layer.

## Install

Install the CLI as a Python user tool:

```bash
uv tool install jas0n1ee-everywhere
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
pipx install jas0n1ee-everywhere
everywhere install
```

Fallback user install:

```bash
python3 -m pip install --user jas0n1ee-everywhere
everywhere install
```

To install directly from GitHub instead of PyPI:

```bash
uv tool install git+https://github.com/jas0n1ee/.everywhere.git
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

To update from the GitHub repository instead of PyPI:

```bash
scripts/update-from-git.sh
```

Pass a branch, tag, or commit as the first argument when needed:

```bash
scripts/update-from-git.sh main
scripts/update-from-git.sh d14c715
```

Override the repository URL with `EVERYWHERE_GIT_REPO` for forks:

```bash
EVERYWHERE_GIT_REPO=https://github.com/<owner>/.everywhere.git scripts/update-from-git.sh main
```

If you installed with `pipx`:

```bash
pipx upgrade jas0n1ee-everywhere
everywhere install
```

If you installed with `pip --user`:

```bash
python3 -m pip install --user --upgrade jas0n1ee-everywhere
everywhere install
```

Re-running `install` after an update is safe. Existing Feishu bridge bindings and
logs remain under `~/.everywhere/feishu-bridge/`.

## Development

Before committing bridge runtime or Skill changes, run:

```bash
everywhere check
```

This runs unit tests, builds a wheel, and verifies the Skill can be discovered
with `npx skills add . --list --full-depth`.

## Release

Everywhere is published to PyPI as `jas0n1ee-everywhere`.

For maintainers, publish a new version with:

```bash
python3 -m everywhere check
rm -rf dist
uv build
uv publish
```

`UV_PUBLISH_TOKEN` must be exported in the publishing shell. PyPI does not allow
re-uploading the same version, so bump `project.version` before each release.
