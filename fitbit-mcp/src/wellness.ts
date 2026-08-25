import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { makeFitbitRequest, ToolResponseStructure } from './utils.js';

const FITBIT_API_BASE = 'https://api.fitbit.com/1';

type DateRangeParams = { startDate: string; endDate: string };

const dateRangeSchema = {
  startDate: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, 'Start date must be in YYYY-MM-DD format.')
    .describe('The start date (YYYY-MM-DD).'),
  endDate: z
    .string()
    .regex(/^\d{4}-\d{2}-\d{2}$/, 'End date must be in YYYY-MM-DD format.')
    .describe('The end date (YYYY-MM-DD).'),
};

function registerDateRangeTool(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>,
  toolName: string,
  description: string,
  endpointPath: (start: string, end: string) => string,
  rangeLimitDays: number
): void {
  server.tool(
    toolName,
    description,
    dateRangeSchema,
    async ({ startDate, endDate }: DateRangeParams): Promise<ToolResponseStructure> => {
      const start = new Date(startDate);
      const end = new Date(endDate);
      const days = Math.round((end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24));
      if (days > rangeLimitDays) {
        return {
          content: [
            {
              type: 'text',
              text: `Date range exceeds the Fitbit API limit of ${rangeLimitDays} days for this endpoint.`,
            },
          ],
          isError: true,
        };
      }
      const endpoint = endpointPath(startDate, endDate);
      const data = await makeFitbitRequest<unknown>(
        endpoint,
        getAccessTokenFn,
        FITBIT_API_BASE
      );
      if (!data) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve ${toolName} data from Fitbit API for '${startDate}' to '${endDate}'. The device may not record this metric, or the date range may be outside the available history.`,
            },
          ],
          isError: true,
        };
      }
      return { content: [{ type: 'text', text: JSON.stringify(data, null, 2) }] };
    }
  );
}

export function registerWellnessTools(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  registerDateRangeTool(
    server,
    getAccessTokenFn,
    'get_temp_skin_by_date_range',
    "Get nightly skin temperature variation (relative to a personal baseline, in °C) from Fitbit for a date range. Returns one entry per night where data was recorded. Useful for illness early-detection — illness elevates nightly skin temp +0.2°C / +0.4°F or more, while stress/anxiety does not. Requires 'startDate' and 'endDate' (YYYY-MM-DD). Max range 30 days.",
    (s, e) => `temp/skin/date/${s}/${e}.json`,
    30
  );

  registerDateRangeTool(
    server,
    getAccessTokenFn,
    'get_breathing_rate_by_date_range',
    "Get nightly average breathing rate (breaths per minute, full sleep + by sleep stage) from Fitbit for a date range. Useful as an illness confirmer — respiratory illness elevates breathing rate. Requires 'startDate' and 'endDate' (YYYY-MM-DD). Max range 30 days.",
    (s, e) => `br/date/${s}/${e}.json`,
    30
  );

  registerDateRangeTool(
    server,
    getAccessTokenFn,
    'get_hrv_by_date_range',
    "Get nightly heart rate variability (HRV) from Fitbit for a date range. Both stress and illness lower HRV, so this is best used alongside skin temp / RHR / breathing rate for triangulation. Requires 'startDate' and 'endDate' (YYYY-MM-DD). Max range 30 days.",
    (s, e) => `hrv/date/${s}/${e}.json`,
    30
  );

  registerDateRangeTool(
    server,
    getAccessTokenFn,
    'get_spo2_by_date_range',
    "Get nightly average SpO2 (blood oxygen saturation, %) from Fitbit for a date range. Drops during respiratory illness and sleep apnea. Requires 'startDate' and 'endDate' (YYYY-MM-DD). Max range 30 days.",
    (s, e) => `spo2/date/${s}/${e}.json`,
    30
  );
}
