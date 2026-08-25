import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { 
  registerTool, 
  handleFitbitApiCall
} from './utils.js';

interface ActivityGoalsData {
  activeMinutes?: number;
  activeZoneMinutes?: number;
  caloriesOut?: number;
  distance?: number;
  floors?: number;
  steps?: number;
}

interface ActivityGoalsResponse {
  goals: ActivityGoalsData;
}

/**
 * Registers an activity goals tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerActivityGoalsTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type ActivityGoalsParams = { period: string };

  registerTool(server, {
    name: 'get_activity_goals',
    description: "Get the raw JSON response for user's activity goals from Fitbit. Supports 'daily' and 'weekly' periods. Returns goal values for steps, distance, calories, floors, active minutes, and active zone minutes.",
    parametersSchema: {
      period: z
        .enum(['daily', 'weekly'])
        .describe("Goal period - either 'daily' or 'weekly'")
    },
    handler: async ({ period }: ActivityGoalsParams) => {
      const endpoint = `activities/goals/${period}.json`;
      
      return handleFitbitApiCall<ActivityGoalsResponse, ActivityGoalsParams>(
        endpoint,
        { period },
        getAccessTokenFn,
        {
          errorContext: `period '${period}'`
        }
      );
    }
  });
}