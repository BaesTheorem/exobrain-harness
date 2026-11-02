#!/usr/bin/env node
/**
 * The `fitbit` MCP server, backed by the Google Health API v4 since the legacy
 * Fitbit Web API shut down (HTTP 410 from 2026-10-30). The server name stays
 * `fitbit` so the harness skills that call mcp__fitbit__* keep working.
 *
 * It never opens a browser. With no token, tools return an error that names
 * bin/fitbit-reauth, and the 6-hourly token check raises a banner.
 */
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { registerGoogleHealthTools } from './google-tools.js';

const server = new McpServer({ name: 'fitbit', version: '2.0.0' });
registerGoogleHealthTools(server);

await server.connect(new StdioServerTransport());
console.error('fitbit MCP (Google Health API v4) connected via stdio.');
