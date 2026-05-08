# Everywhere

Everywhere contains local remote-control transports for agent sessions.

Feishu is the first bridge, but the repository boundary is intentionally broader:

- Provider config belongs in `.codex`, `.claude`, or other provider-specific directories.
- Bridge runtime code belongs here.
- Swarm remains a local orchestrator-worker runtime, not a transport layer.

## Feishu Bridge Quick Start

Install and check prerequisites:

```bash
npx @jas0n1ee/everywhere install
```

Then use:

```bash
everywhere feishu run
everywhere feishu attach
```

See [docs/ONBOARDING.md](docs/ONBOARDING.md) for `lark-cli` setup, default chat bootstrap, and the full `feishu-bridge attach` workflow.
