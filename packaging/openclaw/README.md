# Music Assistant — OpenClaw bundle

An installable [OpenClaw](https://github.com/openclaw/openclaw) plugin bundle
that wires [Music Assistant](https://www.music-assistant.io/) into OpenClaw
over MCP. It pre-declares the Music Assistant MCP server (streamable-HTTP) so
the `ma_*` tools are available right after install, and ships a `SKILL.md`
that tells the agent when and how to use them.

This is a Claude-format bundle (`.claude-plugin/plugin.json` + `.mcp.json` +
`skills/`); OpenClaw detects and maps it into its native plugin features.

## Prerequisites

- A running Music Assistant with the MCP Server plugin enabled and reachable
  from where OpenClaw runs.
- A Music Assistant **long-lived access token**. The quickest way to mint one
  scoped to OpenClaw is the MCP Server plugin's **Connect Wizard** (it creates
  a token named `MCP — OpenClaw`). A token from *Profile → Long-lived access
  tokens* also works.

## Install

```bash
# 1. Provide the token via the environment (interpolated into the
#    Authorization header — never commit it into the bundle).
export MA_TOKEN="<your-music-assistant-token>"

# 2. Install the bundle (from a local checkout or, once published, by name).
openclaw plugins install ./packaging/openclaw

# 3. Restart the OpenClaw gateway so the ma_* tools load.
```

## Configuration

The server is declared in [`.mcp.json`](./.mcp.json):

```json
{
  "mcpServers": {
    "ma": {
      "transport": "streamable-http",
      "url": "http://localhost:8095/mcp/v1",
      "headers": { "Authorization": "Bearer ${MA_TOKEN}" },
      "connectionTimeoutMs": 30000
    }
  }
}
```

- **`MA_TOKEN`** — supplied via the environment. OpenClaw interpolates
  `${VAR}` in `headers` values, so the token stays out of the committed file.
- **`url`** — defaults to `http://localhost:8095/mcp/v1`, which assumes
  OpenClaw runs on the same host as Music Assistant. OpenClaw does **not**
  interpolate `${VAR}` in the `url` field, so for a remote Music Assistant edit
  this value directly to point at your host (e.g.
  `https://music.example.com/mcp/v1`).

## Notes

- The Music Assistant MCP server speaks **streamable-HTTP** and answers `GET`
  on the endpoint (with a valid token it opens the server-to-client SSE
  stream; without one it returns `401`, never `405`). OpenClaw's bundle-mcp
  client opens that optional `GET` stream before `POST initialize`, so a
  POST-only server would fail — this server is not POST-only.
- Tool availability follows the server's per-capability permissions. If a
  category is disabled on the server, those tools simply will not appear.
