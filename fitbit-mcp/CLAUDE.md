# Claude Development Guide

## Project Overview
MCP server named `fitbit` that reads the **Google Health API v4** (the Fitbit Web API shut down on 2026-10-30). Read FORK.md first: it has the reason, the tool map and the operations notes.

**Design Philosophy:** Each tool is a thin proxy that returns Google's raw JSON (data points or daily roll-ups). Tool names and arguments match the old Fitbit tools, because harness skills call them by name.

## Development Commands
- `npm run build` - Compile TypeScript to build/ directory
- `npm run start` - Run the built MCP server
- `npm run dev` - Build and run with MCP inspector for testing/debugging
- `npm run lint` - Check code quality and style issues
- `npm run format` - Auto-fix code formatting
- `npm test` - Run tests with Vitest
- `npm run test:coverage` - Run tests with coverage report

## CI/CD
- GitHub Actions workflow runs tests, lint checks, and build on push/PR to main branch
- Located at `.github/workflows/ci.yml`

## Project Structure
- `src/index.ts` - entry point; registers the tools on a stdio server
- `src/google-auth.ts` - Google OAuth: consent URL, code exchange, refresh, token file
- `src/google-health.ts` - API client: data type time shapes, date filters, list with paging, daily roll-ups
- `src/google-tools.ts` - every MCP tool
- `scripts/google-auth.mjs` - consent CLI behind `bin/fitbit-reauth`
- `scripts/token-check.mjs` - 6-hourly launchd token check
- `.google-health-token.json` - OAuth token (gitignored)

## Code Conventions
- TypeScript with ES modules, Zod for parameters.
- **Documentation first:** check the discovery document (`https://health.googleapis.com/$discovery/rest?version=v4`) before you add a data type. Path ids are kebab-case; filter fields are snake_case.
- Add a new data type to `SHAPES` in `src/google-health.ts` with its time shape, or `dataTypeSpec()` refuses it.
- Tools catch API errors and return `isError` text. They never throw.
- Credentials: `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` in the harness `.env`.

## Contributing & Improvements

When working on this codebase:
1. Follow the existing code style and patterns
2. Update relevant documentation 
3. Test changes thoroughly with the MCP inspector
4. Ensure backward compatibility with existing tools
5. **VERY IMPORTANT:** When you have completed a task, you MUST run `npm run build`, `npm test` and `npm run lint`
6. Update documentation when making changes

