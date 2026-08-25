import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { 
  registerTool, 
  CommonSchemas,
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';

interface ActivityTimeSeriesEntry {
  dateTime: string;
  value: string;
}

interface ActivityTimeSeriesResponse {
  [key: string]: ActivityTimeSeriesEntry[];
}

/**
 * Registers an activity time series tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerActivityTimeSeriesTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type ActivityTimeSeriesParams = Pick<CommonParams, 'startDate' | 'endDate'> & { resourcePath: string };

  registerTool(server, {
    name: 'get_activity_timeseries',
    description: "Get the raw JSON response for activity time series data from Fitbit over a date range (max 30 days). Supports various resource paths like 'steps', 'distance', 'calories', 'activityCalories', 'caloriesBMR'.",
    parametersSchema: {
      resourcePath: z
        .enum([
          'steps',
          'distance', 
          'calories',
          'activityCalories',
          'caloriesBMR',
          'tracker/activityCalories',
          'tracker/calories',
          'tracker/distance'
        ])
        .describe("Activity resource to retrieve (e.g., 'steps', 'distance', 'calories')"),
      startDate: CommonSchemas.startDate,
      endDate: CommonSchemas.endDate,
    },
    handler: async ({ resourcePath, startDate, endDate }: ActivityTimeSeriesParams) => {
      const endpoint = `activities/${resourcePath}/date/${startDate}/${endDate}.json`;
      
      return handleFitbitApiCall<ActivityTimeSeriesResponse, ActivityTimeSeriesParams>(
        endpoint,
        { resourcePath, startDate, endDate },
        getAccessTokenFn,
        {
          errorContext: `resource '${resourcePath}' from ${startDate} to ${endDate}`
        }
      );
    }
  });
}