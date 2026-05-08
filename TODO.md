# Everywhere TODO

## Remote Control / Feishu Bridge

- Decide which bridge commands should be part of the stable public interface.
  Current candidates: `run`, `bootstrap-chat`, `attach`, `detach`, `notify`, `status`.
- Decide whether provider prompts should mention remote-control behavior at all, or whether the bridge should remain completely out-of-band.
- Rework the old `NOTIFY HUMAN` guidance:
  - Feishu remote-control delivery should not depend on Swarm runtime artifacts.
  - When remote-control is attached, provider final answers are expected to be forwarded by transcript/hook capture.
  - `NOTIFY HUMAN` may still be useful for explicit task-state paging, but that needs a separate design from terminal remote control.
- Decide how non-Feishu bridges should share common code with `feishu_bridge.py`.
  Feishu is the first bridge, not the whole Everywhere transport layer.
- Decide whether attachments are v1 bridge behavior or a Feishu-specific extension.
- Add a first-class handoff-to-human command that can publish a local Markdown handoff as a Feishu doc and return the doc URL.
  Current observed behavior: creating the doc as bot and sending the URL into the Feishu conversation is enough for Feishu to render the title and for the human to read it.
  The command should rely on that path first, then only add explicit permission management if a future target chat cannot read the created doc.
- Add a review gate before committing bridge and provider-prompt changes.
