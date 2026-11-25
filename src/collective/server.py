"""Glyphh Collective: a council of models for Claude, run through the CLIs you are already signed in to.

Each member is a command-line tool (claude, codex, gemini, grok) run headless with its own sign-in,
so no API keys live here. The council tool asks every member the same question at once and,
with rounds=2, shows each member the others' answers so it can stand by or revise its own.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from mcp.server.mcpserver import MCPServer

CONFIG = Path(os.environ.get("COLLECTIVE_CONFIG", "~/.config/collective/members.toml")).expanduser()
TIMEOUT = float(os.environ.get("COLLECTIVE_TIMEOUT", "300"))


@dataclass
class Member:
    name: str
    command: list[str]
    # "arg": prompt is the last argument; "stdin": prompt is piped in
    prompt_via: str = "arg"
    # codex writes its final message to a file; "{out}" in the command is replaced with that path
    output_file: bool = False
    env_drop: list[str] = field(default_factory=list)

    @property
    def binary(self) -> str:
        return self.command[0]

    def installed(self) -> bool:
        return shutil.which(self.binary) is not None


DEFAULTS: dict[str, Member] = {
    "claude": Member(
        "claude",
        ["claude", "-p", "--output-format", "text", "--no-session-persistence", "--tools", ""],
        # --tools takes a list, so a prompt argument after it would be eaten
        prompt_via="stdin",
        # a nested claude refuses to start inside a Claude Code session without this
        env_drop=["CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"],
    ),
    "codex": Member(
        "codex",
        ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "read-only",
         "--color", "never", "-o", "{out}"],
        output_file=True,
    ),
    # Google retired Gemini CLI's personal sign-in in June 2026; Antigravity CLI (agy) replaces it
    "gemini": Member("gemini", ["agy", "--output-format", "text", "-p"]),
    "grok": Member("grok", ["grok", "-p"]),
}


def load_members() -> dict[str, Member]:
    """Defaults, overridden or extended by ~/.config/collective/members.toml.

    [members.gemini]
    command = ["gemini", "-m", "gemini-2.5-pro", "-p"]
    """
    members = dict(DEFAULTS)
    if CONFIG.exists():
        data = tomllib.loads(CONFIG.read_text())
        for name, spec in data.get("members", {}).items():
            if spec.get("enabled") is False:
                members.pop(name, None)
                continue
            base = members.get(name)
            members[name] = Member(
                name,
                spec.get("command", base.command if base else [name]),
                spec.get("prompt_via", base.prompt_via if base else "arg"),
                spec.get("output_file", base.output_file if base else False),
                spec.get("env_drop", base.env_drop if base else []),
            )
    return members


async def ask(member: Member, prompt: str) -> dict:
    """Run one member headless and return its answer or the reason it failed."""
    if not member.installed():
        return {"member": member.name, "ok": False, "error": f"`{member.binary}` is not installed"}
    env = {k: v for k, v in os.environ.items() if k not in member.env_drop}
    with tempfile.TemporaryDirectory(prefix="collective-") as work:
        out = Path(work) / "answer.txt"
        cmd = [part.replace("{out}", str(out)) for part in member.command]
        stdin = None
        if member.prompt_via == "stdin":
            stdin = prompt.encode()
        else:
            cmd.append(prompt)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=work, env=env,
                stdin=asyncio.subprocess.PIPE if stdin else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(stdin), TIMEOUT)
        except asyncio.TimeoutError:
            proc.kill()
            return {"member": member.name, "ok": False, "error": f"no answer after {TIMEOUT:.0f}s"}
        except OSError as e:
            return {"member": member.name, "ok": False, "error": str(e)}
        text = out.read_text() if member.output_file and out.exists() else stdout.decode()
        if proc.returncode != 0 or not text.strip():
            tail = stderr.decode().strip().splitlines()[-5:]
            return {"member": member.name, "ok": False,
                    "error": f"exit {proc.returncode}: " + " | ".join(tail)}
        return {"member": member.name, "ok": True, "answer": text.strip()}


def revise_prompt(question: str, mine: str, others: list[dict]) -> str:
    theirs = "\n\n".join(f"### {o['member']}\n{o['answer']}" for o in others)
    return (
        f"You are one member of a council of AI models answering this question:\n\n{question}\n\n"
        f"Your first answer was:\n\n{mine}\n\n"
        f"The other members answered:\n\n{theirs}\n\n"
        "Say where you agree and where you disagree with them, and why. Then give your final answer, "
        "changing it only if their arguments convinced you."
    )


mcp = MCPServer(
    "collective",
    instructions=(
        "Glyphh Collective asks a council of other AI models (Claude, OpenAI Codex, Gemini, Grok), each "
        "through the user's own signed-in CLI. Use `council` for a second opinion, a hard decision, or a "
        "review where independent models help; then weigh their answers yourself and say where they "
        "disagree. `members` shows who is available."
    ),
)


@mcp.tool()
async def members() -> list[dict]:
    """List the council members and whether each one's CLI is installed on this machine."""
    return [{"member": m.name, "command": m.binary, "installed": m.installed()}
            for m in load_members().values()]


@mcp.tool()
async def council(question: str, members: list[str] | None = None, rounds: int = 1) -> dict:
    """Ask every council member the same question at once and return each answer.

    question: the full question, with all the context a member needs (they cannot see this chat).
    members: names to ask (claude, codex, gemini, grok); default is every installed member.
    rounds: 1 for independent answers; 2 to also show each member the others' answers and let it
            agree, push back or revise.
    """
    roster = load_members()
    chosen = [roster[n] for n in (members or roster) if n in roster]
    if not members:
        chosen = [m for m in chosen if m.installed()]
    if not chosen:
        return {"error": "no council members are available", "members": list(roster)}

    first = await asyncio.gather(*(ask(m, question) for m in chosen))
    result = {"question": question, "round_1": first}
    answered = [r for r in first if r["ok"]]
    if rounds >= 2 and len(answered) >= 2:
        by_name = {m.name: m for m in chosen}
        second = await asyncio.gather(*(
            ask(by_name[r["member"]],
                revise_prompt(question, r["answer"], [o for o in answered if o is not r]))
            for r in answered
        ))
        result["round_2"] = second
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
