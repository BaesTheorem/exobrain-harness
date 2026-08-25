import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { makeFitbitRequest, ToolResponseStructure } from './utils.js';

const FITBIT_API_BASE = 'https://api.fitbit.com/1';

// --- Fitbit API Response Interfaces for Heart Rate ---

// Represents a heart rate zone from the Fitbit API
interface HeartRateZone {
  caloriesOut: number;
  max: number;
  min: number;
  minutes: number;
  name: string;
}

// Represents heart rate data for a single day
interface HeartRateValue {
  heartRateZones: HeartRateZone[];
  restingHeartRate?: number;
}

// Represents a single heart rate entry from the Fitbit Time Series API
interface HeartRateTimeSeriesEntry {
  dateTime: string;
  value: HeartRateValue;
}

// Represents the structure of the response from the Fitbit Time Series API for heart rate
interface HeartRateTimeSeriesResponse {
  'activities-heart': HeartRateTimeSeriesEntry[];
}

// --- Tool Registration ---

/**
 * Registers Fitbit heart rate tools with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerHeartRateTools(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  // --- Heart Rate by Date/Period Tool ---

  const periodToolName = 'get_heart_rate';
  const periodDescription =
    "Get the raw JSON response for heart rate data from Fitbit for a specified period ending today or on a specific date. Requires a 'period' parameter such as '1d', '7d', '30d', '1w', '1m' and optionally accepts 'date' parameter.";

  const periodParametersSchemaShape = {
    period: z
      .enum(['1d', '7d', '30d', '1w', '1m'])
      .describe('The time period for which to retrieve heart rate data.'),
    date: z
      .string()
      .regex(
        /^\d{4}-\d{2}-\d{2}$|^today$/,
        "Date must be in YYYY-MM-DD format or 'today'."
      )
      .optional()
      .describe(
        "The date for which to retrieve heart rate data (YYYY-MM-DD or 'today'). Defaults to 'today'."
      ),
  };

  type HeartRatePeriodParams = {
    period: '1d' | '7d' | '30d' | '1w' | '1m';
    date?: string;
  };

  server.tool(
    periodToolName,
    periodDescription,
    periodParametersSchemaShape,
    async ({
      period,
      date = 'today',
    }: HeartRatePeriodParams): Promise<ToolResponseStructure> => {
      // Construct the endpoint dynamically
      const endpoint = `activities/heart/date/${date}/${period}.json`;

      const heartRateData =
        await makeFitbitRequest<HeartRateTimeSeriesResponse>(
          endpoint,
          getAccessTokenFn,
          FITBIT_API_BASE
        );

      // Handle API call failure
      if (!heartRateData) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve heart rate data from Fitbit API for date '${date}' and period '${period}'. Check token and permissions.`,
            },
          ],
          isError: true,
        };
      }

      // Handle no data found for the period
      const heartRateEntries = heartRateData['activities-heart'] || [];
      if (heartRateEntries.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `No heart rate data found for date '${date}' and period '${period}'.`,
            },
          ],
        };
      }

      // Return successful response with raw JSON
      const rawJsonResponse = JSON.stringify(heartRateData, null, 2);
      return {
        content: [{ type: 'text', text: rawJsonResponse }],
      };
    }
  );

  // --- Heart Rate by Date Range Tool ---

  const rangeToolName = 'get_heart_rate_by_date_range';
  const rangeDescription =
    "Get the raw JSON response for heart rate data from Fitbit for a specific date range. Requires 'startDate' and 'endDate' parameters in 'YYYY-MM-DD' format. Note: The API enforces a maximum range of 1 year.";

  const rangeParametersSchemaShape = {
    startDate: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, 'Start date must be in YYYY-MM-DD format.')
      .describe(
        'The start date for which to retrieve heart rate data (YYYY-MM-DD).'
      ),
    endDate: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, 'End date must be in YYYY-MM-DD format.')
      .describe(
        'The end date for which to retrieve heart rate data (YYYY-MM-DD).'
      ),
  };

  type HeartRateRangeParams = {
    startDate: string;
    endDate: string;
  };

  server.tool(
    rangeToolName,
    rangeDescription,
    rangeParametersSchemaShape,
    async ({
      startDate,
      endDate,
    }: HeartRateRangeParams): Promise<ToolResponseStructure> => {
      // Construct the endpoint dynamically
      const endpoint = `activities/heart/date/${startDate}/${endDate}.json`;

      // Make the request
      const heartRateData =
        await makeFitbitRequest<HeartRateTimeSeriesResponse>(
          endpoint,
          getAccessTokenFn,
          FITBIT_API_BASE
        );

      // Handle API call failure
      if (!heartRateData) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve heart rate data from Fitbit API for the date range '${startDate}' to '${endDate}'. Check token, permissions, date format, and ensure the range is 1 year or less.`,
            },
          ],
          isError: true,
        };
      }

      // Handle no data found
      const heartRateEntries = heartRateData['activities-heart'] || [];
      if (heartRateEntries.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `No heart rate data found for the date range '${startDate}' to '${endDate}'.`,
            },
          ],
        };
      }

      // Return successful response
      const rawJsonResponse = JSON.stringify(heartRateData, null, 2);
      return {
        content: [{ type: 'text', text: rawJsonResponse }],
      };
    }
  );
}
