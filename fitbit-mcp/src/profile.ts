import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  handleFitbitApiCall
} from './utils.js';

// Represents the structure of the response from the Fitbit Profile API
interface FitbitProfile {
  user: {
    fullName: string;
    age: number;
    gender: string;
    height: number; // in centimeters
    weight: number; // in kilograms
    avatar: string; // URL to the user's avatar
    memberSince: string; // Date the user joined Fitbit
    // Add other fields as needed
  };
}

/**
 * Registers a single, parameterized Fitbit profile tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerProfileTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  registerTool(server, {
    name: 'get_profile',
    description: "Get the raw JSON response for the user's Fitbit profile.",
    parametersSchema: {},
    handler: async () => {
      const endpoint = 'profile.json';
      
      return handleFitbitApiCall<FitbitProfile, Record<string, never>>(
        endpoint,
        {},
        getAccessTokenFn,
        {
          errorContext: 'profile data'
        }
      );
    }
  });
}
