import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { registerNutritionTools } from './nutrition.js';
import * as utils from './utils.js';
import type { ToolResponseStructure } from './utils.js';

// Mock the utils module
vi.mock('./utils.js', () => ({
  makeFitbitRequest: vi.fn(),
}));

describe('Nutrition Tools', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockMakeFitbitRequest: ReturnType<typeof vi.fn>;
  let mockServerToolSpy: any; // Simplified spy type

  beforeEach(() => {
    mockServer = {
      tool: vi.fn(), // Mock the .tool method directly
    } as unknown as McpServer;
    mockGetAccessToken = vi.fn();
    mockMakeFitbitRequest = vi.mocked(utils.makeFitbitRequest);
    mockServerToolSpy = vi.spyOn(mockServer, 'tool'); // Spy on the mocked .tool method
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('registerNutritionTools', () => {
    it('should register all nutrition tools via server.tool', () => {
      registerNutritionTools(mockServer, mockGetAccessToken);
      expect(mockServerToolSpy).toHaveBeenCalledTimes(3);
      expect(mockServerToolSpy).toHaveBeenCalledWith(
        'get_food_log',
        expect.any(String),
        expect.any(Object),
        expect.any(Function)
      );
      expect(mockServerToolSpy).toHaveBeenCalledWith(
        'get_nutrition',
        expect.any(String),
        expect.any(Object),
        expect.any(Function)
      );
      expect(mockServerToolSpy).toHaveBeenCalledWith(
        'get_nutrition_by_date_range',
        expect.any(String),
        expect.any(Object),
        expect.any(Function)
      );
    });
  });

  // Helper to get the arguments for a specific tool registration
  const getToolRegistrationArgs = (toolName: string) => {
    const call = mockServerToolSpy.mock.calls.find((c: any[]) => c[0] === toolName);
    if (!call) throw new Error(`Tool ${toolName} not registered or spy not capturing call.`);
    return {
      name: call[0] as string,
      description: call[1] as string,
      parametersSchema: call[2] as Record<string, z.ZodTypeAny>,
      handler: call[3] as (params: any) => Promise<ToolResponseStructure>,
    };
  };

  describe('get_food_log tool', () => {
    const toolName = 'get_food_log';
    const defaultDate = 'today';

    beforeEach(() => {
      // Ensure tools are registered before each test in this block
      registerNutritionTools(mockServer, mockGetAccessToken);
    });

    it('should register with correct configuration', () => {
      const config = getToolRegistrationArgs(toolName);
      expect(config.name).toBe(toolName);
      expect(config.description).toBe('Get comprehensive nutrition data (calories, protein, carbs, fat, fiber, sodium) from Fitbit food log for a specific date. Returns daily summary totals and individual food entries with nutritional values.');
      // Check schema structure
      expect(config.parametersSchema.date).toBeInstanceOf(z.ZodOptional);
      expect((config.parametersSchema.date as z.ZodOptional<z.ZodString>)._def.innerType).toBeInstanceOf(z.ZodString);
    });

    it('should call makeFitbitRequest with correct endpoint for default date', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const mockFoodLogData = { foods: [], summary: {}, goals: {} };
      mockMakeFitbitRequest.mockResolvedValue(mockFoodLogData);

      const result = await handler({}); // Call handler with empty params for default date

      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/date/${defaultDate}.json`,
        mockGetAccessToken,
        'https://api.fitbit.com/1'
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockFoodLogData, null, 2) }]
      });
    });

    it('should call makeFitbitRequest with correct endpoint for specified date', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const specificDate = '2023-01-15';
      const mockFoodLogData = { foods: [], summary: {}, goals: {} };
      mockMakeFitbitRequest.mockResolvedValue(mockFoodLogData);

      const result = await handler({ date: specificDate });

      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/date/${specificDate}.json`,
        mockGetAccessToken,
        'https://api.fitbit.com/1'
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockFoodLogData, null, 2) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      mockMakeFitbitRequest.mockResolvedValue(null); // Simulate API failure

      const result = await handler({ date: '2023-01-15' });
      
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain('Failed to retrieve food log data');
    });
    
    it('should handle null access token by letting makeFitbitRequest handle it', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      mockGetAccessToken.mockResolvedValue(null);
      mockMakeFitbitRequest.mockResolvedValue(null);

      const result = await handler({ date: '2023-01-15' });
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain('Failed to retrieve food log data');
      
      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/date/2023-01-15.json`,
        mockGetAccessToken, 
        'https://api.fitbit.com/1'
      );
    });
  });

  describe('get_nutrition tool', () => {
    const toolName = 'get_nutrition';
    const defaultDate = 'today';

    beforeEach(() => {
      registerNutritionTools(mockServer, mockGetAccessToken);
    });
    
    it('should register with correct configuration', () => {
      const config = getToolRegistrationArgs(toolName);
      expect(config.name).toBe(toolName);
      expect(config.description).toContain('Get the raw JSON response for nutrition data from Fitbit for a specified resource and period');
      expect(config.parametersSchema.resource).toBeInstanceOf(z.ZodEnum);
      expect(config.parametersSchema.period).toBeInstanceOf(z.ZodEnum);
      expect(config.parametersSchema.date).toBeInstanceOf(z.ZodOptional);
    });

    it('should call makeFitbitRequest with correct endpoint for specified resource, period, and default date', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const resource = 'caloriesIn';
      const period = '7d';
      const mockResponseData = { [`foods-log-${resource}`]: [{ dateTime: '2023-01-15', value: '2000' }] };
      mockMakeFitbitRequest.mockResolvedValue(mockResponseData);

      const params = { resource, period };
      const result = await handler(params);

      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/${resource}/date/${defaultDate}/${period}.json`,
        mockGetAccessToken,
        'https://api.fitbit.com/1'
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockResponseData, null, 2) }]
      });
    });

    it('should call makeFitbitRequest with correct endpoint for specified resource, period, and date', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const resource = 'water';
      const period = '1m';
      const specificDate = '2023-01-10';
      const mockResponseData = { [`foods-log-${resource}`]: [{ dateTime: '2023-01-10', value: '2000' }] };
      mockMakeFitbitRequest.mockResolvedValue(mockResponseData);
      
      const params = { resource, period, date: specificDate };
      const result = await handler(params);

      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/${resource}/date/${specificDate}/${period}.json`,
        mockGetAccessToken,
        'https://api.fitbit.com/1'
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockResponseData, null, 2) }]
      });
    });
    
    it('should handle API errors gracefully', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      mockMakeFitbitRequest.mockResolvedValue(null); 
      const params = { resource: 'caloriesIn', period: '7d', date: '2023-01-15' };
      const result = await handler(params);
      
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain('Failed to retrieve nutrition data');
    });

    it('should handle no data found for the period', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const resource = 'protein';
      const period = '1d';
      const date = '2023-01-01';
      const mockResponseData = { [`foods-log-${resource}`]: [] }; 
      mockMakeFitbitRequest.mockResolvedValue(mockResponseData);

      const params = { resource, period, date };
      const result = await handler(params);

      expect(result.isError).toBeUndefined(); 
      expect(result.content[0].text).toContain(`No nutrition data found for resource '${resource}'`);
    });
  });

  describe('get_nutrition_by_date_range tool', () => {
    const toolName = 'get_nutrition_by_date_range';

    beforeEach(() => {
      registerNutritionTools(mockServer, mockGetAccessToken);
    });

    it('should register with correct configuration', () => {
      const config = getToolRegistrationArgs(toolName);
      expect(config.name).toBe(toolName);
      expect(config.description).toContain('Get the raw JSON response for nutrition data from Fitbit for a specific resource and date range.');
      expect(config.parametersSchema.resource).toBeInstanceOf(z.ZodEnum);
      expect(config.parametersSchema.startDate).toBeInstanceOf(z.ZodString);
      expect(config.parametersSchema.endDate).toBeInstanceOf(z.ZodString);
    });

    it('should call makeFitbitRequest with correct endpoint for specified resource and date range', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const resource = 'fat';
      const startDate = '2023-01-01';
      const endDate = '2023-01-07';
      const mockResponseData = { [`foods-log-${resource}`]: [{ dateTime: '2023-01-01', value: '50' }] };
      mockMakeFitbitRequest.mockResolvedValue(mockResponseData);

      const params = { resource, startDate, endDate };
      const result = await handler(params);

      expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
        `foods/log/${resource}/date/${startDate}/${endDate}.json`,
        mockGetAccessToken,
        'https://api.fitbit.com/1'
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockResponseData, null, 2) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      mockMakeFitbitRequest.mockResolvedValue(null); 
      const params = { resource: 'carbs', startDate: '2023-01-01', endDate: '2023-01-07' };
      const result = await handler(params);
      
      expect(result.isError).toBe(true);
      expect(result.content[0].text).toContain('Failed to retrieve nutrition data');
    });
    
    it('should handle no data found for the date range', async () => {
      const { handler } = getToolRegistrationArgs(toolName);
      const resource = 'fiber';
      const startDate = '2023-02-01';
      const endDate = '2023-02-05';
      const mockResponseData = { [`foods-log-${resource}`]: [] };
      mockMakeFitbitRequest.mockResolvedValue(mockResponseData);

      const params = { resource, startDate, endDate };
      const result = await handler(params);

      expect(result.isError).toBeUndefined();
      expect(result.content[0].text).toContain(`No nutrition data found for resource '${resource}'`);
    });
  });
});
