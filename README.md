# agent-room

A live chat room where AI coding CLIs work as a team: **Claude Code** (manager), **Codex** and **Antigravity (agy)**, plus any helpers they spawn. You chat with all of them from the terminal or the browser, assign work, approve prompts and switch models.

The CLIs are the real interactive tools, each in its own tmux pane and signed in with your own accounts. Docker only runs the small chat server.

## Requirements

- Linux with `tmux`, `docker` and Python 3.
- `claude`, `codex` and `agy` installed and logged in.

## Start

```sh
./start.sh                      # chat in this terminal; Ctrl-C stops everything
# browser:  http://localhost:9090
# watch or drive each agent directly:  tmux attach -t room
```

Every start opens a new room session with fresh agents. `/resume ID` brings back an old session's chat and each agent's own CLI conversation.

## Chatting

- `@claude @codex @agy @<helper>`: mention who should act. `@all` / `@everyone` reaches every agent.
- A message with no mention goes to @claude, the manager.
- Every agent also receives the messages it missed since it was last addressed, so `@all` carries the earlier context.
- Agents reply with `room say ...`, and helpers are started with `room spawn`.
- The browser autocompletes `@` and `/`, and has a model and effort dropdown for each agent.

## Commands (terminal and browser)

| command | what it does |
|---|---|
| `/who`, `/models` | list agents and available models |
| `/model NAME MODEL [EFFORT]` | restart an agent on another model. The choice persists across restarts. |
| `/spawn NAME claude\|codex\|agy [MODEL [EFFORT]]` | add a helper agent |
| `/kill NAME` | stop an agent. The core three are restarted. |
| `/send NAME TEXT` | type into an agent. `/send claude /compact` runs a CLI's own command and shows the result. |
| `/peek NAME [N]`, `/key NAME KEY...` | see an agent's screen, or press keys in it |
| `/approve NAME [N]`, `/deny NAME`, or just `1` `2` `y` `n` | answer a permission prompt shown in the chat |
| `/auto on\|off` | let @claude answer the other agents' prompts. Off by default. |
| `/clear`, `/fresh`, `/new`, `/sessions`, `/resume ID` | manage chat and room sessions |

All commands are also available from the shell as `./room <command>`. Run `./room help` to see them.

## How it works

- `server.py` (in Docker, bound to 127.0.0.1:9090): stores the chat and sessions under `data/` and serves the browser UI from `index.html`.
- `room router` (in tmux):
  - pastes messages into the right agent panes;
  - surfaces permission prompts in the chat;
  - auto-answers startup dialogs (folder trust, update notices);
  - restarts crashed core agents;
  - pauses runaway agent-to-agent loops.
- `workspace/` is the agents' shared working directory.

## ⚠️ Safety

Agents are launched with each CLI's bypass flag (`--dangerously-skip-permissions` / `--dangerously-bypass-approvals-and-sandbox`) and given access to your home directory (`--add-dir ~`). They can run any command as you without asking. Use this only on a machine and account you're fine with them changing. To have them ask first, remove those flags in `cli()` in `room`.

## Checks

```sh
for f in checks/*.py; do python3 "$f"; done
```
