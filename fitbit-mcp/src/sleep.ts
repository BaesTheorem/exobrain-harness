import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { 
  registerTool, 
  CommonSchemas, 
  handleFitbitApiCall,
  type CommonParams 
} from './utils.js';
import { FITBIT_API_VERSIONS, VALIDATION_MESSAGES } from './config.js';

// --- Fitbit API Response Interfaces for Sleep ---

// Represents the summary data for different sleep stages
interface SleepLevelSummaryData {
  count: number;
  minutes: number;
  thirtyDayAvgMinutes?: number; // Optional, might not always be present
}

// Represents the summary of sleep levels (deep, light, rem, wake)
interface SleepLevelSummary {
  deep?: SleepLevelSummaryData;
  light?: SleepLevelSummaryData;
  rem?: SleepLevelSummaryData;
  wake?: SleepLevelSummaryData;
  // Older "classic" sleep logs might have different structures
  restless?: SleepLevelSummaryData;
  awake?: SleepLevelSummaryData;
  asleep?: SleepLevelSummaryData;
}

// Represents detailed data points for sleep stages (simplified)
interface SleepLevelDataPoint {
  dateTime: string;
  level: 'deep' | 'light' | 'rem' | 'wake' | 'asleep' | 'awake' | 'restless';
  seconds: number;
}

// Represents the structure containing sleep level summaries and detailed data
interface SleepLevels {
  summary: SleepLevelSummary;
  data: SleepLevelDataPoint[];
  shortData?: SleepLevelDataPoint[]; // For naps or short sleep periods
}

// Represents a single sleep log entry from the Fitbit API
interface SleepLogEntry {
  logId: number;
  dateOfSleep: string;
  startTime: string;
  endTime: string;
  duration: number; // Milliseconds
  minutesToFallAsleep: number;
  minutesAsleep: number;
  minutesAwake: number;
  minutesAfterWakeup?: number; // May not be present in all log types
  timeInBed: number;
  efficiency: number;
  type: 'stages' | 'classic';
  infoCode: number;
  levels?: SleepLevels; // Present for 'stages' type
  // Classic sleep logs might have slightly different fields
  isMainSleep: boolean;
}


// Represents the overall structure of the response from the Fitbit Sleep API by date range
interface SleepLogRangeResponse {
  sleep: SleepLogEntry[]; // Array of sleep log entries for the requested date range
  // Note: The summary object might not be present or might differ in the date range endpoint response.
  // Adjust based on actual API behavior if needed.
}

// --- Tool Registration ---

/**
 * Registers a single, parameterized Fitbit sleep tool with the MCP server for a date range.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerSleepTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  type SleepParams = Pick<CommonParams, 'startDate' | 'endDate'>;

  registerTool(server, {
    name: 'get_sleep_by_date_range',
    description: `Get the raw JSON response for sleep logs from Fitbit for a specific date range. Requires 'startDate' and 'endDate' parameters in 'YYYY-MM-DD' format. ${VALIDATION_MESSAGES.MAX_RANGE_100_DAYS}.`,
    parametersSchema: {
      startDate: CommonSchemas.startDate,
      endDate: CommonSchemas.endDate,
    },
    handler: async ({ startDate, endDate }: SleepParams) => {
      const endpoint = `/sleep/date/${startDate}/${endDate}.json`;
      
      return handleFitbitApiCall<SleepLogRangeResponse, SleepParams>(
        endpoint,
        { startDate, endDate },
        getAccessTokenFn,
        {
          apiBase: FITBIT_API_VERSIONS.V1_2,
          successDataExtractor: (data) => data.sleep || [],
          noDataMessage: `the date range '${startDate}' to '${endDate}'`,
          errorContext: `date range '${startDate}' to '${endDate}'`
        }
      );
    }
  });
}
