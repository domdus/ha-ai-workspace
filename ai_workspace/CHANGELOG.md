# Changelog

## 1.0.0

First public release.

- Cursor SDK runtime for AI Workspace on Home Assistant OS (app) and Home Assistant Container (Docker)
- Prebuilt image for amd64 and arm64
- Shared runtime token. On Home Assistant OS the integration creates it and writes it to the app. Docker sets `RUNTIME_TOKEN`. A runtime that listens beyond loopback refuses chats without a token.
- MCP servers sent by the integration must be HTTP. stdio servers and environment overrides from requests are refused.
- Users who are not admins only get the built-in Home Assistant MCP Server with their own login
- Agents are kept open between messages, so follow-ups keep their context; a lost agent resumes from the saved chat
- Large MCP results are shortened to valid JSON before the model reads them
- Requires Home Assistant 2025.12 or newer
