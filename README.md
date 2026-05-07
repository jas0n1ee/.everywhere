# Everywhere

Everywhere contains local remote-control transports for agent sessions.

Feishu is the first bridge, but the repository boundary is intentionally broader:

- Provider config belongs in `.codex`, `.claude`, or other provider-specific directories.
- Bridge runtime code belongs here.
- Swarm remains a local orchestrator-worker runtime, not a transport layer.
