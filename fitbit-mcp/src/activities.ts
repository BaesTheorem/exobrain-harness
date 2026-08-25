import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  CommonSchemas, 
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';

// --- Fitbit API Response Interfaces for Activities ---

// Represents a single activity entry from the Fitbit Activities API
interface ActivityLogEntry {
  logId: number;
  activityId: number;
  activityName: string;
  activityTypeId: number;
  activityLevel?: {
    minutes: number;
    name: string;
  }[];
  averageHeartRate?: number;
  calories: number;
  distance?: number;
  distanceUnit?: string;
  duration: number;
  activeDuration: number;
  steps?: number;
  source: {
    id: string;
    name: string;
    type: string;
  };
  startDate: string;
  startTime: string;
  originalStartDate: string;
  originalStartTime: string;
  heartRateZones?: {
    caloriesOut: number;
    max: number;
    min: number;
    minutes: number;
    name: string;
  }[];
  lastModified: string;
  elevationGain?: number;
  hasGps?: boolean;
  hasActiveZoneMinutes?: boolean;
}

// Represents the overall structure of the response from the Fitbit Activities API by date range
interface ActivitiesListResponse {
  activities: ActivityLogEntry[];
  pagination?: {
    beforeDate: string;
    limit: number;
    next: string;
    offset: number;
    previous: string;
    sort: string;
  };
}

// --- Tool Registration ---

/**
 * Registers a Fitbit activities/exercises tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerActivitiesTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type ActivitiesParams = Pick<CommonParams, 'afterDate' | 'limit'>;

  registerTool(server, {
    name: 'get_exercises',
    description: "Get the raw JSON response for exercise and activity logs from Fitbit after a specific date. Requires 'afterDate' parameter in 'YYYY-MM-DD' format. Retrieves a detailed list of logged exercises and activities.",
    parametersSchema: {
      afterDate: CommonSchemas.afterDate,
      limit: CommonSchemas.limit,
    },
    handler: async ({ afterDate, limit = 20 }: ActivitiesParams) => {
      const endpoint = `activities/list.json?afterDate=${afterDate}&sort=asc&offset=0&limit=${limit}`;
      
      return handleFitbitApiCall<ActivitiesListResponse, ActivitiesParams>(
        endpoint,
        { afterDate, limit },
        getAccessTokenFn,
        {
          successDataExtractor: (data) => data.activities || [],
          noDataMessage: `after date '${afterDate}'`,
          errorContext: `after date '${afterDate}'`
        }
      );
    }
  });
}
