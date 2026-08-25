import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  CommonSchemas,
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';

interface AzmValue {
  activeZoneMinutes: number;
  fatBurnActiveZoneMinutes: number;
  cardioActiveZoneMinutes: number;
  peakActiveZoneMinutes: number;
}

interface AzmTimeSeriesEntry {
  dateTime: string;
  value: AzmValue;
}

interface AzmTimeSeriesResponse {
  'activities-active-zone-minutes': AzmTimeSeriesEntry[];
}

/**
 * Registers an Active Zone Minutes time series tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerAzmTimeSeriesTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type AzmTimeSeriesParams = Pick<CommonParams, 'startDate' | 'endDate'>;

  registerTool(server, {
    name: 'get_azm_timeseries',
    description: "Get the raw JSON response for Active Zone Minutes (AZM) time series data from Fitbit over a date range (max 1095 days). Returns total AZM plus breakdown by fat burn, cardio, and peak zones.",
    parametersSchema: {
      startDate: CommonSchemas.startDate,
      endDate: CommonSchemas.endDate,
    },
    handler: async ({ startDate, endDate }: AzmTimeSeriesParams) => {
      const endpoint = `activities/active-zone-minutes/date/${startDate}/${endDate}.json`;
      
      return handleFitbitApiCall<AzmTimeSeriesResponse, AzmTimeSeriesParams>(
        endpoint,
        { startDate, endDate },
        getAccessTokenFn,
        {
          errorContext: `AZM data from ${startDate} to ${endDate}`
        }
      );
    }
  });
}