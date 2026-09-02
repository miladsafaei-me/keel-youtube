"""The default provider: an already-installed, already-signed-in Claude Code CLI.

Chosen as the default because it needs no API key and no Python dependency - if a
colleague has Claude Code, this tool works for them immediately.

The call is deliberately sealed off from the machine it runs on. Left to its
defaults the CLI loads that user's personal instruction files, settings, hooks,
plugins and MCP servers, which would make the tool expensive, slow, and worst of
all non-reproducible: two people would get different screenshots from the same
video because of rules neither of them wrote for this tool. Every flag below
exists to close one of those doors.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..binaries import run
from ..errors import LLMError
from .base import Provider, parse_json_object

_SYSTEM_PROMPT = (
    "You are a precise extraction tool inside a command-line program. "
    "Answer only with the JSON object the user asks for. "
    "You may read the image and text files named in the prompt. Do nothing else: "
    "do not write files, do not run commands, do not explain yourself."
)


class ClaudeCLIProvider(Provider):
    name = "claude-cli"
    setup_hint = (
        "install Claude Code and sign in: https://claude.com/claude-code "
        "(then `claude` must be on PATH)"
    )

    @property
    def default_model(self) -> str:
        return "sonnet"

    @classmethod
    def available(cls) -> bool:
        return shutil.which("claude") is not None

    def ask(self, prompt: str, schema: dict, images: list[Path] | None = None) -> dict:
        binary = shutil.which("claude")
        if not binary:
            raise LLMError(f"the `claude` command was not found - {self.setup_hint}")

        # Images are passed as absolute paths and read by the CLI's own Read
        # tool, which is how this provider sees pictures at all.
        body = prompt
        if images:
            listing = "\n".join(f"  {p.resolve()}" for p in images)
            body = f"{prompt}\n\nRead each of these image files before answering:\n{listing}"

        # Sandbox the session: our own system prompt instead of the CLI's large
        # default, no user/project settings, no MCP servers, no skills, and Read
        # as the only tool. `--setting-sources ""` is what keeps a colleague's
        # personal configuration out of the answer.
        cmd = [
            binary, "-p", body,
            "--model", self.model,
            "--output-format", "json",
            "--json-schema", json.dumps(schema),
            "--system-prompt", _SYSTEM_PROMPT,
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--allowed-tools", "Read",
            "--permission-mode", "bypassPermissions",
        ]
        proc = run(cmd, timeout=900)
        if proc.returncode != 0:
            raise LLMError(f"the claude CLI failed: {proc.stderr.strip()[-400:]}")

        try:
            envelope = json.loads(proc.stdout.strip() or "{}")
        except json.JSONDecodeError as exc:
            raise LLMError(f"the claude CLI returned unreadable output: {exc}") from exc

        if envelope.get("is_error"):
            raise LLMError(f"the claude CLI reported an error: {envelope.get('result', '')[:300]}")

        structured = envelope.get("structured_output")
        if isinstance(structured, dict) and structured:
            return structured
        return parse_json_object(envelope.get("result") or "")
