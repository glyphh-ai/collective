# Glyphh Collective

A council of models for Claude. Collective is an MCP server that asks Claude, OpenAI Codex, Gemini and Grok the same question at once, each through the command-line tool you are already signed in to, and hands their answers back to Claude to weigh. You need no API keys: every member uses its own CLI sign-in.

## Members

| Member | CLI | Sign in |
| --- | --- | --- |
| claude | [Claude Code](https://claude.com/claude-code) `claude` | `claude` then `/login` |
| codex | [OpenAI Codex](https://github.com/openai/codex) `codex` | `codex login` |
| gemini | [Gemini CLI](https://github.com/google-gemini/gemini-cli) `gemini` | `gemini` and choose Sign in with Google |
| grok | Grok CLI `grok` | follow the CLI's sign-in |

Collective asks only the members whose CLI is installed. Every member runs in an empty temporary folder, and Codex runs in its read-only sandbox.

## Install in Claude Code

```bash
claude mcp add collective --scope user -- uvx --from git+https://github.com/glyphh-ai/collective glyphh-collective
```

## Tools

- `council(question, members?, rounds=1)` asks every member at once. With `rounds=2`, each member then sees the others' answers and says where it agrees, where it pushes back, and what its final answer is.
- `members()` lists the members and whether each CLI is installed.

Members cannot see your conversation, so Claude puts the whole context into the question.

## Configure

Change a member's command, or add a new one, in `~/.config/collective/members.toml`:

```toml
[members.gemini]
command = ["gemini", "-m", "gemini-2.5-pro", "-p"]

[members.grok]
enabled = false

[members.local]
command = ["ollama", "run", "llama3"]
prompt_via = "stdin"
```

The prompt goes last on the command line unless `prompt_via = "stdin"`. Each member has 300 seconds to answer, which you can change with `COLLECTIVE_TIMEOUT`.

## License

Apache-2.0
