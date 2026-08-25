import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

// Define ToolFunction type locally for test typing
type ToolFunction<P = any, R = any> = (params: P) => Promise<R>;
import { z } from 'zod';
import { registerHeartRateTools } from './heart-rate.js';
import * as utils from './utils.js';

// Mock the utils.js module, specifically makeFitbitRequest
vi.mock('./utils.js', async () => {
  const actualUtils = await vi.importActual('./utils.js');
  return {
    ...actualUtils,
    makeFitbitRequest: vi.fn(),
  };
});

describe('Heart Rate Tools', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockMakeFitbitRequest: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Create a mock server instance with a mocked 'tool' method
    mockServer = {
      tool: vi.fn(),
    } as unknown as McpServer; // Cast to McpServer, acknowledging it's a partial mock

    mockGetAccessToken = vi.fn().mockResolvedValue('test_access_token');
    mockMakeFitbitRequest = vi.mocked(utils.makeFitbitRequest);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerHeartRateTools', () => {
    it('should register both heart rate tools', () => {
      registerHeartRateTools(mockServer, mockGetAccessToken);
      expect(mockServer.tool).toHaveBeenCalledTimes(2);
      expect(mockServer.tool).toHaveBeenCalledWith(
        'get_heart_rate',
        expect.any(String),
        expect.any(Object),
        expect.any(Function)
      );
      expect(mockServer.tool).toHaveBeenCalledWith(
        'get_heart_rate_by_date_range',
        expect.any(String),
        expect.any(Object),
        expect.any(Function)
      );
    });

    describe('get_heart_rate (period tool)', () => {
      let periodToolHandler: ToolFunction<any, any>;
      const periodToolName = 'get_heart_rate';

      beforeEach(() => {
        registerHeartRateTools(mockServer, mockGetAccessToken);
        // Find the handler for the period tool
        const periodToolCall = vi.mocked(mockServer.tool).mock.calls.find(call => call[0] === periodToolName);
        if (periodToolCall && typeof periodToolCall[3] === 'function') {
          periodToolHandler = periodToolCall[3];
        } else {
          throw new Error(`Handler for ${periodToolName} not found or not a function`);
        }
      });

      it('should register with correct name, description, and schema', () => {
        const periodToolCall = vi.mocked(mockServer.tool).mock.calls.find(call => call[0] === periodToolName);
        expect(periodToolCall).toBeDefined();
        expect(periodToolCall?.[0]).toBe(periodToolName);
        expect(periodToolCall?.[1]).toContain("Get the raw JSON response for heart rate data from Fitbit for a specified period");
        // Basic schema check, can be more detailed if needed
        const schema = periodToolCall?.[2] as any;
        expect(schema.period).toBeInstanceOf(z.ZodEnum);
        expect(schema.date).toBeInstanceOf(z.ZodOptional);
      });

      it('should call makeFitbitRequest with correct endpoint for period and default date', async () => {
        const mockData = { 'activities-heart': [{ dateTime: '2025-05-25', value: { restingHeartRate: 60 } }] };
        mockMakeFitbitRequest.mockResolvedValue(mockData);
        const params = { period: '1d' as const };

        await periodToolHandler(params);

        expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
          'activities/heart/date/today/1d.json',
          mockGetAccessToken,
          'https://api.fitbit.com/1'
        );
      });

      it('should call makeFitbitRequest with correct endpoint for period and specified date', async () => {
        const mockData = { 'activities-heart': [{ dateTime: '2025-05-24', value: { restingHeartRate: 62 } }] };
        mockMakeFitbitRequest.mockResolvedValue(mockData);
        const params = { period: '7d' as const, date: '2025-05-24' };

        await periodToolHandler(params);

        expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
          'activities/heart/date/2025-05-24/7d.json',
          mockGetAccessToken,
          'https://api.fitbit.com/1'
        );
      });

      it('should return formatted data on successful API call', async () => {
        const mockRawData = { 'activities-heart': [{ dateTime: '2025-05-25', value: { restingHeartRate: 60 } }] };
        mockMakeFitbitRequest.mockResolvedValue(mockRawData);
        const params = { period: '1d' as const };

        const result = await periodToolHandler(params);

        expect(result.content[0].text).toBe(JSON.stringify(mockRawData, null, 2));
        expect(result.isError).toBeUndefined();
      });

      it('should handle API call failure (makeFitbitRequest returns null)', async () => {
        mockMakeFitbitRequest.mockResolvedValue(null);
        const params = { period: '1d' as const, date: '2025-05-25' };

        const result = await periodToolHandler(params);

        expect(result.content[0].text).toContain("Failed to retrieve heart rate data");
        expect(result.isError).toBe(true);
      });

      it('should handle no data found (empty activities-heart array)', async () => {
        const mockEmptyData = { 'activities-heart': [] };
        mockMakeFitbitRequest.mockResolvedValue(mockEmptyData);
        const params = { period: '1d' as const, date: '2025-05-25' };

        const result = await periodToolHandler(params);

        expect(result.content[0].text).toContain("No heart rate data found");
        expect(result.isError).toBeUndefined(); // Not an API error, just no data
      });
    });

    describe('get_heart_rate_by_date_range (range tool)', () => {
      let rangeToolHandler: ToolFunction<any, any>;
      const rangeToolName = 'get_heart_rate_by_date_range';

      beforeEach(() => {
        registerHeartRateTools(mockServer, mockGetAccessToken);
        const rangeToolCall = vi.mocked(mockServer.tool).mock.calls.find(call => call[0] === rangeToolName);
        if (rangeToolCall && typeof rangeToolCall[3] === 'function') {
          rangeToolHandler = rangeToolCall[3];
        } else {
          throw new Error(`Handler for ${rangeToolName} not found or not a function`);
        }
      });

      it('should register with correct name, description, and schema', () => {
        const rangeToolCall = vi.mocked(mockServer.tool).mock.calls.find(call => call[0] === rangeToolName);
        expect(rangeToolCall).toBeDefined();
        expect(rangeToolCall?.[0]).toBe(rangeToolName);
        expect(rangeToolCall?.[1]).toContain("Get the raw JSON response for heart rate data from Fitbit for a specific date range");
        const schema = rangeToolCall?.[2] as any;
        expect(schema.startDate).toBeInstanceOf(z.ZodString);
        expect(schema.endDate).toBeInstanceOf(z.ZodString);
      });

      it('should call makeFitbitRequest with correct endpoint for date range', async () => {
        const mockData = { 'activities-heart': [{ dateTime: '2025-05-25', value: { restingHeartRate: 60 } }] };
        mockMakeFitbitRequest.mockResolvedValue(mockData);
        const params = { startDate: '2025-05-01', endDate: '2025-05-25' };

        await rangeToolHandler(params);

        expect(mockMakeFitbitRequest).toHaveBeenCalledWith(
          'activities/heart/date/2025-05-01/2025-05-25.json',
          mockGetAccessToken,
          'https://api.fitbit.com/1'
        );
      });

      it('should return formatted data on successful API call', async () => {
        const mockRawData = { 'activities-heart': [{ dateTime: '2025-05-25', value: { restingHeartRate: 60 } }] };
        mockMakeFitbitRequest.mockResolvedValue(mockRawData);
        const params = { startDate: '2025-05-01', endDate: '2025-05-25' };

        const result = await rangeToolHandler(params);

        expect(result.content[0].text).toBe(JSON.stringify(mockRawData, null, 2));
        expect(result.isError).toBeUndefined();
      });

      it('should handle API call failure (makeFitbitRequest returns null)', async () => {
        mockMakeFitbitRequest.mockResolvedValue(null);
        const params = { startDate: '2025-05-01', endDate: '2025-05-25' };

        const result = await rangeToolHandler(params);

        expect(result.content[0].text).toContain("Failed to retrieve heart rate data");
        expect(result.isError).toBe(true);
      });

      it('should handle no data found (empty activities-heart array)', async () => {
        const mockEmptyData = { 'activities-heart': [] };
        mockMakeFitbitRequest.mockResolvedValue(mockEmptyData);
        const params = { startDate: '2025-05-01', endDate: '2025-05-25' };

        const result = await rangeToolHandler(params);

        expect(result.content[0].text).toContain("No heart rate data found");
        expect(result.isError).toBeUndefined();
      });
    });
  });
});
