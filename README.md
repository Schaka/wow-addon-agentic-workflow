# wow-addon-agentic-workflow

This repository is a template and a set of tools for World of Warcraft addon development with coding agents. It gives people and agents the same tools and the same workflow. WoW Forever is the first supported client.

The template contains these parts:

1. A pin of the exact game build that the repository targets, in `wow-target.toml`.
2. An MCP server and a command line tool that answer API questions for that build.
3. Static analysis that finds removed APIs and old combat log code.
4. An offline simulator that runs addons and tests without the game.
5. An in-client test addon that returns test results and Lua errors through SavedVariables.
6. Agent instructions in `AGENTS.md` and portable skills in `.agents/skills/`.

## Requirements

You need Python 3.11 or later and a Lua 5.1 interpreter. LuaJIT also works. You need the game only for in-client tests.

## Quick start

```sh
./waw api sync
./waw doctor
./waw target status
./waw verify
```

On Windows, use `waw.cmd` in place of `./waw`.

## Create an addon repository

Use one repository for each addon or addon family. This template stays the source of the tools.

```sh
./waw new-repo ../MyAddon-Forever
cd ../MyAddon-Forever
./waw api sync
./waw index
./waw new MyAddon
```

Open a new agent session in the new folder. One session works best on one repository, because `AGENTS.md`, the MCP server and the pin belong to the repository.

If you find a defect in the tools, fix it in this template. Then copy the tools to the addon repository:

```sh
./waw sync-tools ../MyAddon-Forever
```

The sync does not change `wow-target.toml`, `README.md`, `PROJECT.md`, `addons/` or `docs/project/`. Put facts about one addon in `PROJECT.md` and `docs/project/`.

If the tools do not find your client, set `WOW_FOREVER_DIR` or create `waw.local.toml`:

```toml
[client]
path = "/path/to/World of Warcraft/_forever_"
```

## Commands

| Command | Purpose |
| --- | --- |
| `./waw doctor` | Make sure that the tools are ready |
| `./waw target status` | Compare the pin with the live build, the client and the UI source |
| `./waw target bump` | Pin a synced build after review |
| `./waw api sync` | Download the pinned UI source and build a snapshot |
| `./waw api sync --latest` | Build a snapshot of the newest UI source |
| `./waw api sync --retail` | Build a Midnight snapshot for comparison |
| `./waw api lookup NAME` | Read one API, event, enum or CVar |
| `./waw api search TEXT` | Search API names |
| `./waw api restrictions TEXT` | List secret and restricted APIs |
| `./waw api diff` | Compare the pinned build with the newest synced build |
| `./waw index` | Build the code graph indexes |
| `./waw index status` | Show the code graph project names |
| `./waw check` | Run static analysis |
| `./waw test` | Run offline tests |
| `./waw verify` | Run static analysis and offline tests |
| `./waw link` | Link addons into the client |
| `./waw ingame prepare` | Install the test addon for one test run |
| `./waw ingame collect` | Read the test results |
| `./waw ingame errors` | Read the Lua errors of the last session |
| `./waw package` | Build release zip files in `dist/` |
| `./waw new NAME` | Create an addon from the example |
| `./waw new-repo PATH` | Create an addon repository from this template |
| `./waw sync-tools PATH` | Copy the tools and shared docs to an addon repository |
| `./waw docs` | Find Simple English problems |
| `./waw mcp` | Run the MCP server on stdio |

## Code graph

The template connects to [codebase-memory-mcp](https://github.com/DeusData/codebase-memory-mcp), so that agents query code and do not read whole files. Install the tool once for your computer. If it is not installed, the other tools still work.

| Index | Scope | Content |
| --- | --- | --- |
| `repo-<folder>` | One repository | The code of that repository |
| `wow-framexml-<product>-<build>` | All repositories on the computer | Blizzard UI source for one build |
| `wow-ref-<name>` | All repositories on the computer | Reference addons |

The shared source files are in `~/.cache/waw`. Set `WAW_CACHE` to use another folder. Each shared index is built once. A new repository adds only its own index.

For Claude Code, `.claude/settings.json` adds the project names to each new session and subagent. It also reminds the agent to query the graph before it reads a large Lua or XML file.

## Agent setup

`AGENTS.md` is the source of the instructions. `CLAUDE.md` and `GEMINI.md` import it. Codex, Cursor and GitHub Copilot read `AGENTS.md` directly.

The repository includes MCP configuration for these clients:

| Client | File |
| --- | --- |
| Claude Code | `.mcp.json` |
| Cursor | `.cursor/mcp.json` |
| VS Code | `.vscode/mcp.json` |
| Codex | `.codex/config.toml` |
| Gemini CLI | `.gemini/settings.json` |

On Windows, change `python3` to `py` in the file for your client.

## Documents

| Document | Content |
| --- | --- |
| `docs/guidelines.md` | Code style, comments and addon architecture |
| `docs/platform.md` | Facts about the Forever client, with the evidence for each fact |
| `docs/testing.md` | The test layers and the limits of each layer |
| `docs/migration/combat-log.md` | How to replace the combat log |
| `docs/migration/secret-values.md` | How to work with secret values |
| `docs/migration/api-changes.md` | How to port an older addon |
| `docs/migration/field-notes.md` | Facts that real ports proved in the client |
| `docs/research.md` | What other projects do, and the sources |

## Tests for the tools

Run `python3 tools/tests/test_waw.py` after you change a file in `tools/`.

## License

This repository uses the GNU Affero General Public License, version 3 only. See `LICENSE`.

The skill in `.agents/skills/simple-english/` comes from [SimpleEnglish](https://github.com/AminBlg/SimpleEnglish). It keeps its MIT license, in the `LICENSE` file of that folder.
