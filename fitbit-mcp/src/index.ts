#!/usr/bin/env node

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import dotenv from 'dotenv';
import path from 'path';
import { fileURLToPath } from 'url';

// Import authentication functions
import {
  initializeAuth,
  startAuthorizationFlow,
  getAccessToken,
} from './auth.js';
// Import tool registration function(s)
import { registerWeightTool } from './weight.js';
import { registerSleepTool } from './sleep.js';
import { registerProfileTool } from './profile.js';
import { registerActivitiesTool } from './activities.js';
import { registerHeartRateTools } from './heart-rate.js';
import { registerNutritionTools } from './nutrition.js';
import { registerDailyActivityTool } from './daily-activity.js';
import { registerActivityGoalsTool } from './activity-goals.js';
import { registerActivityTimeSeriesTool } from './activity-timeseries.js';
import { registerAzmTimeSeriesTool } from './azm-timeseries.js';
import { registerWellnessTools } from './wellness.js';
// Import utilities
import './utils.js';

// Calculate the directory name of the current module (build/index.js)
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

// Construct the absolute path to the .env file (one level up from build/)
// Load environment variables early in the application lifecycle
const envPath = path.resolve(__dirname, '..', '.env');
dotenv.config({ path: envPath });

// Validate required environment variables
function validateEnvironment(): void {
  const requiredVars = {
    FITBIT_CLIENT_ID: process.env.FITBIT_CLIENT_ID,
    FITBIT_CLIENT_SECRET: process.env.FITBIT_CLIENT_SECRET,
  };

  const missingVars = Object.entries(requiredVars)
    .filter(([, value]) => !value)
    .map(([key]) => key);

  if (missingVars.length > 0) {
    console.error('Missing required environment variables:');
    missingVars.forEach(varName => {
      console.error(`   - ${varName}`);
    });
    console.error(`Please create a .env file at: ${envPath}`);
    console.error('See README.md for details on getting Fitbit API credentials.');
    process.exit(1);
  }
}

// Validate environment before proceeding
validateEnvironment();

// Log successful environment loading
console.error('✅ Environment variables loaded successfully');

// Create the main MCP server instance
const server = new McpServer({
  name: 'fitbit',
  version: '1.0.0',
  capabilities: {
    resources: {},
    tools: {}, // Tools are registered dynamically below
  },
});

// Register available tools with the MCP server
registerWeightTool(server, getAccessToken);
registerSleepTool(server, getAccessToken);
registerProfileTool(server, getAccessToken);
registerActivitiesTool(server, getAccessToken);
registerHeartRateTools(server, getAccessToken);
registerNutritionTools(server, getAccessToken);
registerDailyActivityTool(server, getAccessToken);
registerActivityGoalsTool(server, getAccessToken);
registerActivityTimeSeriesTool(server, getAccessToken);
registerAzmTimeSeriesTool(server, getAccessToken);
registerWellnessTools(server, getAccessToken);

// --- Main Application Entry Point ---
async function main() {
  // Initialize the authentication module (e.g., load persisted token)
  await initializeAuth();

  // Set up the transport layer for communication (stdio in this case)
  const transport = new StdioServerTransport();

  try {
    // Connect the MCP server to the transport
    await server.connect(transport);
    console.error('Fitbit MCP Server connected via stdio.');

    // Check if an access token is available after connection
    // If not, initiate the OAuth2 authorization flow
    const token = await getAccessToken();
    if (!token) {
      console.error(
        'No access token found. Starting Fitbit authorization flow...'
      );
      startAuthorizationFlow(); // Start flow in background, do not await
    } else {
      console.error('Using existing/loaded access token.');
    }
  } catch (error) {
    console.error('Failed to connect MCP server:', error);
    process.exit(1); // Exit if connection fails
  }

  console.error('MCP Server setup complete. Waiting for requests...');
  // The server connection via StdioServerTransport keeps the process alive.
}

// Execute the main function and handle any top-level errors
main().catch((error: Error) => {
  console.error(
    'Fatal error during MCP server startup:',
    error.message || error
  );
  process.exit(1);
});
