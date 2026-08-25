import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  CommonSchemas, 
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';

// Represents a single weight entry from the Fitbit Time Series API
interface WeightTimeSeriesEntry {
  dateTime: string; // Date (and potentially time) of the entry
  value: string; // Weight value as a string
}

// Represents the structure of the response from the Fitbit Time Series API for weight
interface WeightTimeSeriesResponse {
  'body-weight': WeightTimeSeriesEntry[]; // Array of weight entries
}

// --- Tool Registration ---

/**
 * Registers a single, parameterized Fitbit weight tool with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerWeightTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type WeightParams = Pick<CommonParams, 'period'>;

  registerTool(server, {
    name: 'get_weight',
    description: "Get the raw JSON response for weight entries from Fitbit for a specified period ending today. Requires a 'period' parameter such as '1d', '7d', '30d', '3m', '6m', '1y'",
    parametersSchema: {
      period: CommonSchemas.period,
    },
    handler: async ({ period }: WeightParams) => {
      const endpoint = `/body/weight/date/today/${period}.json`;
      
      return handleFitbitApiCall<WeightTimeSeriesResponse, WeightParams>(
        endpoint,
        { period },
        getAccessTokenFn,
        {
          successDataExtractor: (data) => data['body-weight'] || [],
          noDataMessage: `the period '${period}'`,
          errorContext: `period '${period}'`
        }
      );
    }
  });
}
