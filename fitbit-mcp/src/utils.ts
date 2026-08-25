/**
 * Shared utility functions for Fitbit API integration
 */

import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { 
  HTTP_CONFIG, 
  ERROR_MESSAGES, 
  FITBIT_API_VERSIONS,
  DATE_REGEX,
  VALIDATION_MESSAGES,
  TIME_PERIODS,
  HEART_RATE_DETAIL_LEVELS,
  type TimePeriod,
  type HeartRateDetailLevel
} from './config.js';

// Common response structures for MCP tools
export type TextContent = { type: 'text'; text: string };

export type ToolResponseStructure = {
  content: TextContent[];
  isError?: boolean;
  _meta?: Record<string, unknown>;
  [key: string]: unknown;
};

/**
 * Makes a generic request to the Fitbit API.
 * Handles adding the base URL, authorization header, and basic error handling.
 * @param endpoint The specific API endpoint path (e.g., '/body/weight/date/today/30d.json').
 * @param getAccessTokenFn A function that returns the current valid access token or null.
 * @param apiBase The base URL for the API (defaults to v1, can be overridden for different API versions)
 * @returns A promise resolving to the parsed JSON response (type T) or null if the request fails.
 */
export async function makeFitbitRequest<T>(
  endpoint: string,
  getAccessTokenFn: () => Promise<string | null>,
  apiBase: string = FITBIT_API_VERSIONS.V1
): Promise<T | null> {
  const currentAccessToken = await getAccessTokenFn();
  if (!currentAccessToken) {
    console.error(`Error: ${ERROR_MESSAGES.NO_ACCESS_TOKEN}`);
    return null;
  }

  // Ensure endpoint starts correctly relative to the user path
  const cleanEndpoint = endpoint.startsWith('/')
    ? endpoint.substring(1)
    : endpoint;
  // Construct the full URL including the user scope '-'.
  const url = `${apiBase}/user/-/${cleanEndpoint}`;
  console.error(`Attempting Fitbit API request to: ${url}`);

  const headers = {
    'User-Agent': HTTP_CONFIG.USER_AGENT,
    Authorization: `Bearer ${currentAccessToken}`,
    Accept: 'application/json',
  };

  try {
    const response = await fetch(url, { headers });
    if (!response.ok) {
      const errorBody = await response.text();
      console.error(
        `Fitbit API Error! Status: ${response.status}, URL: ${url}, Body: ${errorBody}`
      );
      if (response.status === 401) {
        console.error(ERROR_MESSAGES.TOKEN_EXPIRED);
      }
      return null;
    }
    // Handle potential empty response body for certain success statuses (e.g., 204 No Content)
    if (response.status === 204) {
      return {} as T; // Return an empty object or appropriate type for no content
    }
    return (await response.json()) as T;
  } catch (error) {
    console.error(`Error making Fitbit request to ${url}:`, error);
    return null;
  }
}

// === Parameter Validation Schemas ===

export const CommonSchemas = {
  period: z
    .enum(TIME_PERIODS)
    .describe(VALIDATION_MESSAGES.PERIOD_REQUIRED),
  
  startDate: z
    .string()
    .regex(DATE_REGEX, VALIDATION_MESSAGES.DATE_FORMAT)
    .describe(VALIDATION_MESSAGES.START_DATE_REQUIRED),
  
  endDate: z
    .string()
    .regex(DATE_REGEX, VALIDATION_MESSAGES.DATE_FORMAT)
    .describe(VALIDATION_MESSAGES.END_DATE_REQUIRED),
  
  detailLevel: z
    .enum(HEART_RATE_DETAIL_LEVELS)
    .describe(VALIDATION_MESSAGES.DETAIL_LEVEL_REQUIRED),
  
  date: z
    .string()
    .regex(DATE_REGEX, VALIDATION_MESSAGES.DATE_FORMAT)
    .describe('The date for which to retrieve data (YYYY-MM-DD)'),
    
  afterDate: z
    .string()
    .regex(DATE_REGEX, VALIDATION_MESSAGES.DATE_FORMAT)
    .describe('Retrieve activities after this date (YYYY-MM-DD)'),
    
  limit: z
    .number()
    .min(1)
    .max(100)
    .optional()
    .describe('Maximum number of items to return (1-100, default: 20)')
} as const;

// === Common Parameter Types ===

export type CommonParams = {
  period: TimePeriod;
  startDate: string;
  endDate: string;
  detailLevel: HeartRateDetailLevel;
  date: string;
  afterDate: string;
  limit?: number;
};

// === Tool Response Helpers ===

export function createErrorResponse(message: string): ToolResponseStructure {
  return {
    content: [{ type: 'text', text: message }],
    isError: true,
  };
}

export function createSuccessResponse(data: unknown): ToolResponseStructure {
  const rawJsonResponse = JSON.stringify(data, null, 2);
  return {
    content: [{ type: 'text', text: rawJsonResponse }],
  };
}

export function createNoDataResponse(context: string): ToolResponseStructure {
  return {
    content: [{ type: 'text', text: `${ERROR_MESSAGES.NO_DATA_FOUND} ${context}.` }],
  };
}

// === Tool Registration Helper ===

export interface ToolConfig {
  name: string;
  description: string;
  parametersSchema: Record<string, z.ZodTypeAny>;
  // Using 'any' here is necessary because different handlers expect different parameter types
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  handler: (params: any) => Promise<ToolResponseStructure>;
}

export function registerTool(
  server: McpServer,
  config: ToolConfig
): void {
  server.tool(
    config.name,
    config.description,
    config.parametersSchema,
    config.handler
  );
}

// === Fitbit-Specific Tool Helpers ===

export async function handleFitbitApiCall<TResponse, TParams>(
  endpoint: string,
  params: TParams,
  getAccessTokenFn: () => Promise<string | null>,
  options: {
    apiBase?: string;
    successDataExtractor?: (data: TResponse) => unknown[] | null;
    noDataMessage?: string;
    errorContext?: string;
  } = {}
): Promise<ToolResponseStructure> {
  const {
    apiBase = FITBIT_API_VERSIONS.V1,
    successDataExtractor,
    noDataMessage,
    errorContext = JSON.stringify(params)
  } = options;

  const responseData = await makeFitbitRequest<TResponse>(
    endpoint,
    getAccessTokenFn,
    apiBase
  );

  if (!responseData) {
    return createErrorResponse(
      `${ERROR_MESSAGES.API_REQUEST_FAILED} for ${errorContext}. ${ERROR_MESSAGES.CHECK_TOKEN_PERMISSIONS}.`
    );
  }

  // Check for empty data if extractor provided
  if (successDataExtractor) {
    const extractedData = successDataExtractor(responseData);
    if (!extractedData || extractedData.length === 0) {
      return createNoDataResponse(noDataMessage || errorContext);
    }
  }

  return createSuccessResponse(responseData);
}
