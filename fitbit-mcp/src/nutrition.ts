import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { makeFitbitRequest, ToolResponseStructure } from './utils.js';

const FITBIT_API_BASE = 'https://api.fitbit.com/1';

// --- Fitbit API Response Interfaces for Nutrition ---

// Represents a single nutrition entry from the Fitbit Time Series API
interface NutritionTimeSeriesEntry {
  dateTime: string; // Date of the entry
  value: string; // Nutrition value as a string
}

// Represents the structure of the response from the Fitbit Time Series API for nutrition
interface NutritionTimeSeriesResponse {
  [key: string]: NutritionTimeSeriesEntry[]; // Dynamic key based on resource type
}

// Represents a food log entry with nutrition details
interface FoodLogEntry {
  loggedFood: {
    accessLevel: string;
    amount: number;
    brand: string;
    calories: number;
    foodId: number;
    logDate: string;
    logId: number;
    name: string;
    unit: {
      id: number;
      name: string;
      plural: string;
    };
    nutritionalValues?: {
      calories: number;
      carbs: number;
      fat: number;
      fiber: number;
      protein: number;
      sodium: number;
    };
  };
}

// Represents the food log response structure
interface FoodLogResponse {
  foods: FoodLogEntry[];
  goals: {
    calories: number;
  };
  summary: {
    calories: number;
    carbs: number;
    fat: number;
    fiber: number;
    protein: number;
    sodium: number;
    water: number;
  };
}

// --- Tool Registration ---

/**
 * Registers Fitbit nutrition tools with the MCP server.
 * @param server The McpServer instance.
 * @param getAccessTokenFn Function to retrieve the current access token.
 */
export function registerNutritionTools(
  server: McpServer,
  getAccessTokenFn: () => Promise<string | null>
): void {
  // --- Food Log Tool (comprehensive nutrition data) ---

  const foodLogToolName = 'get_food_log';
  const foodLogDescription =
    'Get comprehensive nutrition data (calories, protein, carbs, fat, fiber, sodium) from Fitbit food log for a specific date. Returns daily summary totals and individual food entries with nutritional values.';

  const foodLogParametersSchemaShape = {
    date: z
      .string()
      .regex(
        /^\d{4}-\d{2}-\d{2}$|^today$/,
        "Date must be in YYYY-MM-DD format or 'today'."
      )
      .optional()
      .describe(
        "The date for which to retrieve food log data (YYYY-MM-DD or 'today'). Defaults to 'today'."
      ),
  };

  type FoodLogParams = {
    date?: string;
  };

  server.tool(
    foodLogToolName,
    foodLogDescription,
    foodLogParametersSchemaShape,
    async ({
      date = 'today',
    }: FoodLogParams): Promise<ToolResponseStructure> => {
      // Construct the endpoint
      const endpoint = `foods/log/date/${date}.json`;

      const foodLogData = await makeFitbitRequest<FoodLogResponse>(
        endpoint,
        getAccessTokenFn,
        FITBIT_API_BASE
      );

      // Handle API call failure
      if (!foodLogData) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve food log data from Fitbit API for date '${date}'. Check token and permissions.`,
            },
          ],
          isError: true,
        };
      }

      // Return successful response with raw JSON
      const rawJsonResponse = JSON.stringify(foodLogData, null, 2);
      return {
        content: [{ type: 'text', text: rawJsonResponse }],
      };
    }
  );

  // --- Nutrition by Date/Period Tool ---

  const periodToolName = 'get_nutrition';
  const periodDescription =
    "Get the raw JSON response for nutrition data from Fitbit for a specified resource and period ending today or on a specific date. Requires 'resource' parameter (caloriesIn, water) and 'period' parameter such as '1d', '7d', '30d', '1w', '1m', '3m', '6m', '1y' and optionally accepts 'date' parameter.";

  const periodParametersSchemaShape = {
    resource: z
      .enum([
        'caloriesIn',
        'water',
        'protein',
        'carbs',
        'fat',
        'fiber',
        'sodium',
      ])
      .describe('The nutrition resource to retrieve data for.'),
    period: z
      .enum(['1d', '7d', '30d', '1w', '1m', '3m', '6m', '1y'])
      .describe('The time period for which to retrieve nutrition data.'),
    date: z
      .string()
      .regex(
        /^\d{4}-\d{2}-\d{2}$|^today$/,
        "Date must be in YYYY-MM-DD format or 'today'."
      )
      .optional()
      .describe(
        "The date for which to retrieve nutrition data (YYYY-MM-DD or 'today'). Defaults to 'today'."
      ),
  };

  type NutritionPeriodParams = {
    resource:
      | 'caloriesIn'
      | 'water'
      | 'protein'
      | 'carbs'
      | 'fat'
      | 'fiber'
      | 'sodium';
    period: '1d' | '7d' | '30d' | '1w' | '1m' | '3m' | '6m' | '1y';
    date?: string;
  };

  server.tool(
    periodToolName,
    periodDescription,
    periodParametersSchemaShape,
    async ({
      resource,
      period,
      date = 'today',
    }: NutritionPeriodParams): Promise<ToolResponseStructure> => {
      // Construct the endpoint dynamically
      const endpoint = `foods/log/${resource}/date/${date}/${period}.json`;

      const nutritionData =
        await makeFitbitRequest<NutritionTimeSeriesResponse>(
          endpoint,
          getAccessTokenFn,
          FITBIT_API_BASE
        );

      // Handle API call failure
      if (!nutritionData) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve nutrition data from Fitbit API for resource '${resource}', date '${date}' and period '${period}'. Check token and permissions.`,
            },
          ],
          isError: true,
        };
      }

      // Handle no data found for the period
      const resourceKey = `foods-log-${resource}`;
      const nutritionEntries = nutritionData[resourceKey] || [];
      if (nutritionEntries.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `No nutrition data found for resource '${resource}', date '${date}' and period '${period}'.`,
            },
          ],
        };
      }

      // Return successful response with raw JSON
      const rawJsonResponse = JSON.stringify(nutritionData, null, 2);
      return {
        content: [{ type: 'text', text: rawJsonResponse }],
      };
    }
  );

  // --- Nutrition by Date Range Tool ---

  const rangeToolName = 'get_nutrition_by_date_range';
  const rangeDescription =
    "Get the raw JSON response for nutrition data from Fitbit for a specific resource and date range. Requires 'resource' parameter (caloriesIn, water), 'startDate' and 'endDate' parameters in 'YYYY-MM-DD' format. Note: The API enforces a maximum range of 1,095 days.";

  const rangeParametersSchemaShape = {
    resource: z
      .enum([
        'caloriesIn',
        'water',
        'protein',
        'carbs',
        'fat',
        'fiber',
        'sodium',
      ])
      .describe('The nutrition resource to retrieve data for.'),
    startDate: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, 'Start date must be in YYYY-MM-DD format.')
      .describe(
        'The start date for which to retrieve nutrition data (YYYY-MM-DD).'
      ),
    endDate: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, 'End date must be in YYYY-MM-DD format.')
      .describe(
        'The end date for which to retrieve nutrition data (YYYY-MM-DD).'
      ),
  };

  type NutritionRangeParams = {
    resource:
      | 'caloriesIn'
      | 'water'
      | 'protein'
      | 'carbs'
      | 'fat'
      | 'fiber'
      | 'sodium';
    startDate: string;
    endDate: string;
  };

  server.tool(
    rangeToolName,
    rangeDescription,
    rangeParametersSchemaShape,
    async ({
      resource,
      startDate,
      endDate,
    }: NutritionRangeParams): Promise<ToolResponseStructure> => {
      // Construct the endpoint dynamically
      const endpoint = `foods/log/${resource}/date/${startDate}/${endDate}.json`;

      // Make the request
      const nutritionData =
        await makeFitbitRequest<NutritionTimeSeriesResponse>(
          endpoint,
          getAccessTokenFn,
          FITBIT_API_BASE
        );

      // Handle API call failure
      if (!nutritionData) {
        return {
          content: [
            {
              type: 'text',
              text: `Failed to retrieve nutrition data from Fitbit API for resource '${resource}' and the date range '${startDate}' to '${endDate}'. Check token, permissions, date format, and ensure the range is 1,095 days or less.`,
            },
          ],
          isError: true,
        };
      }

      // Handle no data found
      const resourceKey = `foods-log-${resource}`;
      const nutritionEntries = nutritionData[resourceKey] || [];
      if (nutritionEntries.length === 0) {
        return {
          content: [
            {
              type: 'text',
              text: `No nutrition data found for resource '${resource}' and the date range '${startDate}' to '${endDate}'.`,
            },
          ],
        };
      }

      // Return successful response
      const rawJsonResponse = JSON.stringify(nutritionData, null, 2);
      return {
        content: [{ type: 'text', text: rawJsonResponse }],
      };
    }
  );
}
