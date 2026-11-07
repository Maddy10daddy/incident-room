# Manual: what every piece is and how they fit

Written from what was observed on this machine (macOS 13.4, Apple silicon). Items marked
*(inferred)* were not directly verified.

## 1. The big picture

```
 YOU (human on-call)
   │  chat in Switch Console, or in Mattermost in a browser
   ▼
┌──────────────────────────── your Mac ────────────────────────────┐
│  Switch Console (desktop app)                                    │
│     ├─ runs the local Switch server ("Local Switch server")      │
│     ├─ starts one Claude Code process per agent                  │
│     └─ talks to the chat app through a "bridge"                  │
│                                                                  │
│  Claude Code processes: ops-triager, ops-investigator,           │
│     ops-release, ops-scribe, switch-buddy-admin                  │
│                                                                  │
│  ┌──── Colima: a small hidden Linux computer (virtual machine) ─┐│
│  │  Docker runs the Mattermost chat server in a container       ││
│  └──────────────────────────────────────────────────────────────┘│
│                                                                  │
│  Our project: cart-service + deployctl + loadgen + ops-sentinel  │
└──────────────────────────────────────────────────────────────────┘
```

## 2. Each component

### Switch (the product) and Switch Console (the app)
- **Switch** is an open-source system for putting AI agents into team chat. Its core idea is
  the **room**: one shared place where people and agents talk, with a shared log of messages,
  instructions, roles and tasks. Switch does not ship an AI. You bring one.
- **Switch Console** is the desktop app (`/Applications/Switch Console.app`). It is the control
  panel and the engine room. It starts a local Switch server (the "Local Switch server" in its
  sidebar; three Switch processes listening on local ports), registers your agents, starts and
  stops them, and links the chat app to the rooms.
- The ports like `localhost:51553` are Switch's API. They answer "missing Authorization header"
  in a browser because they are for programs, not people.

### Claude Code
- Claude Code is the AI coding agent installed at `~/.local/bin/claude`. It is the "brain".
- Switch Console does not contain an AI. It launches Claude Code. For each agent you will see a
  process like `claude --output-format stream-json --input-format stream-json --agent ops-triager
  --permission-prompt-tool stdio`. That means: run Claude Code as a background worker that takes
  messages in, sends answers out as structured data, and asks Switch Console (not the terminal)
  whenever it needs permission.
- **Each agent is a separate Claude Code process** with its own working folder
  (`~/.switch/agents/localhost-51553/<agent-name>`), its own instructions and its own memory.
  That is why the investigator and release agent don't know what each other thought, and only
  coordinate through room messages.
- Agents talk to the room through tools Switch gives them (we saw `post_message`,
  `read_context`, `connect_to_room`). The agents also have normal Claude Code tools, such as
  running shell commands, which is how they ran `deployctl.py`.

### How Claude is logged in inside Switch Console
- Switch Console does **not** have its own login for Claude. It reuses the Claude Code you
  already have on the machine. *(inferred)* In Settings, Agent providers it checks whether
  Claude Code is signed in ("Signed in") and then starts it. It uses whatever subscription or
  API key your Claude Code already uses, which is why the docs say setup cannot finish without
  an agent installed.
- Practical consequence: the agents' usage is billed to or counted against that same Claude account.

### How agents get "made"
Claude does not create agents. **Switch Console does**, in these steps:
1. You give it a template (below). It reads the `agents:` list.
2. For each entry it registers an agent identity on the Switch server: a name, an API key,
   who may address it (`addressing`).
3. It creates the agent's working folder.
4. It starts a Claude Code process with that agent's name and **its instructions as the
   agent's role**. The instructions are the text you wrote in the template.
So an "agent" is: **an identity on the Switch server + a Claude Code process running with a
particular set of instructions.**

### The template
- A YAML file: a recipe. It lists the agents (name, instructions, who can talk to them, which AI
  backs them), the room (name, members), and a kickoff message. `{team}` is a fill-in blank, so
  `ops` makes `ops-triager`, `ops-incident` and so on.
- Our file: `incident-room.template.yaml`. Importing it in Console creates the agents and room.
- Changing the file does **not** change agents already running. They keep the old
  instructions until recreated or edited in Console.

### The room
- A room is a Switch object: a shared conversation plus shared material, such as instructions,
  roles, tasks and decisions. Members can be people and agents. Our room is `ops-incident`.
- `addressing` decides who may give an agent orders (`anyone`, owner only, owner's agents).
  Getting this wrong earlier is why "approved" did nothing.
- A **bridge** mirrors the room into a real chat app. Here that app is Mattermost, so every
  room is also a Mattermost channel, and Console shows the same conversation.

### Mattermost
- An open-source Slack-like chat server. Switch needs *some* chat app to be the human interface,
  and when you run Switch on your own computer it brings Mattermost with it, so you don't
  need Slack or admin rights.
- It runs as one Docker container (`mattermost-team-edition`), reachable in a browser at
  `http://127.0.0.1:51554`. Your `maddy10daddy` account is a Mattermost login. It is separate
  from your WeMakeDevs login and from Claude.
- It is the flaky part of our setup (see section 3).

### Docker, Colima and "virtualisation"
- **Docker** runs programs in **containers**: sealed boxes that carry their own software, so
  "it works on my machine" is no problem. Mattermost ships as a container.
- Containers are a **Linux** technology. A Mac is not Linux, so Docker on a Mac needs a hidden
  Linux computer. That is a **virtual machine (VM)**: a pretend computer running inside your Mac.
- **Docker Desktop** is the usual app that does this, but it requires macOS 14+, and you are on
  macOS 13. So we used **Colima**, a free tool that creates and runs that VM (using Apple's
  built-in virtualization). The `docker` command on your Mac talks to Docker inside the VM
  through a socket file (`~/.colima/default/docker.sock`).
- **Why Mattermost crashes:** its container was built for Intel/AMD chips (amd64), and your Mac
  has an Apple chip (arm64). The VM has to **emulate** the other chip, which is slow and
  fragile, and Mattermost segfaulted. **Rosetta**, Apple's faster translator, would fix this,
  but it refused to work on macOS 13. I gave the VM more CPU and memory and set up a watchdog
  that restarts Mattermost when it stops answering.
- Rule of thumb: Colima must be running (`colima start`) for Switch to work, and the Mattermost
  container is the part that can die.

### The WeMakeDevs site
Just the hackathon organizer's website. You registered there. Submitting your project there is
the final step. Nothing in our project talks to it.

## 3. What we built, and the app being simulated

- **The simulated app is a toy online shop's "cart service"**: `service/app.py`. You ask for a
  cart and it returns a price, applying a discount code if you give one. It runs as a normal
  program on your Mac (no Docker), with several **releases** in `service/releases/`.
- **v2.13.2** is the healthy release. **v2.14.0** has a real bug: with no promo code the code
  does `None["pct"]`, so it crashes (500 error). **v2.14.1** is the fix.
- `loadgen.py` pretends to be shoppers. About 70% of requests have no promo code, so the bug
  hits most of them and creates real errors in `run/logs/cart-service.log`.
- `deployctl.py` is the deploy and rollback tool: swap release, restart, check health, keep
  history, `--dry-run`, `verify`.
- `sentinel/` is a **custom agent**: ordinary Python (no AI) that watches the log and posts alerts
  to the room through Switch's agent protocol. It shows that anything that speaks the protocol
  can be an agent, not only Claude.
- `demo.sh` runs it all: `up` (healthy), `break` (ship the bad release), `reset`.
- `tests/` checks the whole thing automatically.

## 4. What we are demonstrating
Humans and AI agents handling a production incident together in one room, where the humans
decide and the agents do the legwork:
1. **Detect:** the sentinel notices the errors and alerts the room, with no human report.
2. **Diagnose:** the investigator reads logs and deploy history and names the bad release and
   the failing line.
3. **Decide:** the release agent proposes a rollback (dry run) and **waits for a human**.
4. **Act and verify:** after "approved", it rolls back and confirms the error rate recovered.
5. **Document:** the scribe writes the postmortem.

Why it fits the hackathon: Switch is required to be central, and here the room, the agent
addressing, the human approval and the custom agent all come from Switch.

## 5. Where things live (so you can find them)
| Thing | Location |
|---|---|
| Project | `~/Desktop/wemakedevs/incident-room/` |
| Switch Console app | `/Applications/Switch Console.app` |
| Console data and logs | `~/Library/Application Support/switchdash/` |
| Each agent's working folder | `~/.switch/agents/localhost-51553/<agent>/` |
| Each agent's Claude memory/transcripts | `~/.claude/projects/-Users-...-switch-agents-localhost-51553-<agent>/` |
| Colima VM config | `~/.colima/default/colima.yaml` |
| Docker config (backup `.bak` alongside) | `~/.docker/config.json` |
| Mattermost in a browser | `http://127.0.0.1:51554` |

## 6. Troubleshooting cheat sheet
| Symptom | Likely cause | Fix |
|---|---|---|
| "Could not reach localhost:51553" or Mattermost won't load | Mattermost crashed | `docker restart switchdash-local-mattermost-mattermost-1` |
| `Cannot connect to the Docker daemon` | Colima not running | `colima start` |
| Agent never answers | Not addressed, or `addressing` blocks you | Tag it (`@ops-release ...`), check its Configuration |
| Agent stuck | Waiting for a permission click | Check Console for an Allow prompt |
| Changed the template, nothing changed | Running agents keep old instructions | Recreate the agents or edit them in Console |
