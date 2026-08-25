import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  CommonSchemas, 
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';

interface ActivityDistance {
  activity: string;
  distance: number;
}

interface HeartRateZone {
  name: string;
  minutes: number;
  caloriesOut: number;
}

interface ActivityGoals {
  activeMinutes: number;
  caloriesOut: number;
  distance: number;
  floors: number;
  steps: number;
}

interface ActivitySummary {
  activityCalories: number;
  caloriesOut: number;
  steps: number;
  distances: ActivityDistance[];
  heartRateZones: HeartRateZone[];
  restingHeartRate?: number;
}

interface DailyActivitySummaryResponse {
  activities: unknown[];
  goals: ActivityGoals;
  summary: ActivitySummary;
}

/**
 * Registers a daily activity summary tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerDailyActivityTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type DailyActivityParams = Pick<CommonParams, 'date'>;

  registerTool(server, {
    name: 'get_daily_activity_summary',
    description: "Get the raw JSON response for daily activity summary from Fitbit for a specific date. Includes goals, steps, calories, distances, and heart rate zones. Requires a 'date' parameter in YYYY-MM-DD format.",
    parametersSchema: {
      date: CommonSchemas.date,
    },
    handler: async ({ date }: DailyActivityParams) => {
      const endpoint = `activities/date/${date}.json`;
      
      return handleFitbitApiCall<DailyActivitySummaryResponse, DailyActivityParams>(
        endpoint,
        { date },
        getAccessTokenFn,
        {
          errorContext: `date '${date}'`
        }
      );
    }
  });
}