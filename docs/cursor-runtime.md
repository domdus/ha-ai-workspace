# Cursor runtime in Docker

These are extras for [Option B](../README.md#option-b-home-assistant-container-docker) (Home Assistant Container). The basic setup with `network_mode: host` needs none of this. The Home Assistant OS app handles network and token for you.

## Bridge network

Docker uses a bridge network when you leave out `network_mode: host`. Use it when you do not want the runtime on the host network, or when Home Assistant itself runs on a bridge.

Inside a bridge container, `127.0.0.1` is the container itself, not Home Assistant. The runtime therefore rewrites MCP addresses such as `http://127.0.0.1:8123/...` to the Docker host, so it can still reach Home Assistant. Remove `network_mode` and use:

```yaml
    ports:
      - "127.0.0.1:8090:8090"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    environment:
      HOST: "0.0.0.0"
      RUNTIME_TOKEN: "a-long-random-value"
      REWRITE_LOOPBACK_HOST: host.docker.internal
```

- `127.0.0.1:8090:8090` publishes port **8090** only on this machine, not on your network.
- `RUNTIME_TOKEN` is required here. A runtime that listens on more than loopback refuses chats until a token is set, so nobody else on the network can use your Cursor key. Put the same value in **Cursor agent → Runtime token** ([Runtime token](../README.md#runtime-token)).
- If Home Assistant is another container on the same bridge, set the agent's **Cursor runtime address** to `http://cursor-sdk:8090`.

## Files on disk

Why: Cursor agents can read and write files. That is useful for notes, scripts, or a project you want the assistant to work on next to the chat. Your automations and dashboards are **not** edited this way; those changes always go through MCP.

The agent works in `WORKSPACE_DIR` (default `/data/workspace`, inside the `ai-workspace-data` volume). Whatever it writes there survives restarts. On the first start the runtime adds two instruction files, `AGENTS.md` and `.cursor/rules/home-assistant.mdc`, only if they are missing. It never overwrites your own files.

To use a folder on the host instead:

```yaml
    environment:
      WORKSPACE_DIR: /workspace
    volumes:
      - ai-workspace-data:/data
      - /path/on/host:/workspace
```

- Do not mount the Home Assistant `/config` folder. The agent would then edit files that Home Assistant expects to manage itself.
- Cursor's own state stays under `/data`, so keep that volume.
- The Home Assistant OS app cannot mount any host folder this way.

## Git repository

Why: if your project lives in git, the agent can start from a fresh clone and, if you allow it, commit and push its work.

The runtime image includes git. Set `GIT_REPO` on the **container** (AI Workspace itself never stores git credentials). On the first start the runtime clones the repository into `WORKSPACE_DIR`. Later starts keep that checkout. The clone is skipped if the folder already has a checkout or other files.

A private repository with an SSH key:

```yaml
    environment:
      GIT_REPO: git@github.com:example/my-repo.git
      GIT_BRANCH: main
      GIT_SSH_KEY: /run/secrets/git_ssh
      GIT_USER_NAME: AI Workspace
      GIT_USER_EMAIL: ai-workspace@local
    volumes:
      - ai-workspace-data:/data
      - /home/me/.ssh/id_ed25519:/run/secrets/git_ssh:ro
```

- `GIT_SSH_KEY` is the path to the key inside the container (or the key text itself).
- For HTTPS instead of SSH, set `GIT_TOKEN` to a personal access token. It is not written into the repository's `.git/config`.
- `GIT_USER_NAME` and `GIT_USER_EMAIL` are what the agent's commits are signed with.
- The agent can only push if that key or token is allowed to. Use a read-only key if it should never push.
