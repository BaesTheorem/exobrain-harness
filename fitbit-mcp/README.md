# fitbit-mcp

An MCP server named `fitbit` that reads Fitbit and Pixel Watch data from the
[Google Health API v4](https://developers.google.com/health). It replaced a fork
of TheDigitalNinja/mcp-fitbit after Google turned off the legacy Fitbit Web API
on 2026-10-30. [FORK.md](FORK.md) has the reason, the tool map and the
operations notes.

## Setup

1. Make a Google Cloud OAuth client of type "Web application" with
   `https://www.google.com` as an authorized redirect URI. Enable the Google
   Health API in the same project. Publish the consent screen "In production",
   because "Testing" refresh tokens expire after 7 days.
2. Put `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` in the harness
   `.env`.
3. `npm ci && npm run build`
4. `bin/fitbit-reauth`, approve the consent page, then paste the redirected
   URL. The token goes to `.google-health-token.json`.
5. Register the server: `claude mcp add --scope user fitbit -- "$PWD/bin/fitbit-mcp"`

The Google account must be signed in to the Google Health app, or the API
answers `ACCOUNT_NOT_LINKED`.

## License

MIT (see LICENSE). The original fork base is Copyright TheDigitalNinja.
