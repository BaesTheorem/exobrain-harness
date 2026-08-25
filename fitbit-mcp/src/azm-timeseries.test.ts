import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerAzmTimeSeriesTool } from './azm-timeseries.js';
import * as utils from './utils.js';
import { CommonSchemas } from './utils.js'; // Import CommonSchemas

// Mock the utils module
vi.mock('./utils.js', async (importOriginal) => {
  const actualUtils = await importOriginal<typeof utils>();
  return {
    ...actualUtils, // Import and retain all exports
    registerTool: vi.fn(),
    handleFitbitApiCall: vi.fn(),
  };
});

describe('AzmTimeSeries Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn();
    // Correctly typed mock for registerTool from the vi.mock
    mockRegisterTool = vi.mocked(utils.registerTool);
    // Correctly typed mock for handleFitbitApiCall from the vi.mock
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerAzmTimeSeriesTool', () => {
    const testStartDate = '2023-01-01';
    const testEndDate = '2023-01-07';

    it('should register the get_azm_timeseries tool with correct configuration', () => {
      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      expect(mockRegisterTool).toHaveBeenCalledWith(mockServer, {
        name: 'get_azm_timeseries',
        description: "Get the raw JSON response for Active Zone Minutes (AZM) time series data from Fitbit over a date range (max 1095 days). Returns total AZM plus breakdown by fat burn, cardio, and peak zones.",
        parametersSchema: {
          startDate: CommonSchemas.startDate,
          endDate: CommonSchemas.endDate,
        },
        handler: expect.any(Function)
      });
    });

    it('should call handler with correct endpoint and parameters', async () => {
      const mockAzmResponse = {
        'activities-active-zone-minutes': [
          { dateTime: '2023-01-01', value: { activeZoneMinutes: 30, fatBurnActiveZoneMinutes: 10, cardioActiveZoneMinutes: 15, peakActiveZoneMinutes: 5 } },
          { dateTime: '2023-01-02', value: { activeZoneMinutes: 45, fatBurnActiveZoneMinutes: 15, cardioActiveZoneMinutes: 20, peakActiveZoneMinutes: 10 } }
        ]
      };

      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockAzmResponse) }]
      });

      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      const result = await handler({ startDate: testStartDate, endDate: testEndDate });

      const expectedEndpoint = `activities/active-zone-minutes/date/${testStartDate}/${testEndDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        { startDate: testStartDate, endDate: testEndDate },
        mockGetAccessToken,
        {
          errorContext: `AZM data from ${testStartDate} to ${testEndDate}`
        }
      );

      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockAzmResponse) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'API error occurred';
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler({ startDate: testStartDate, endDate: testEndDate })).rejects.toThrow(errorMessage);

      const expectedEndpoint = `activities/active-zone-minutes/date/${testStartDate}/${testEndDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        { startDate: testStartDate, endDate: testEndDate },
        mockGetAccessToken,
        {
          errorContext: `AZM data from ${testStartDate} to ${testEndDate}`
        }
      );
    });

    it('should handle null access token', async () => {
      mockGetAccessToken.mockResolvedValue(null);
      // Simulate handleFitbitApiCall throwing an error when token is null,
      // as it would try to use it or the underlying request would fail.
      mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available'));

      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler({ startDate: testStartDate, endDate: testEndDate })).rejects.toThrow('No access token available');
    });

    it('should use correct tool name and description', () => {
      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.name).toBe('get_azm_timeseries');
      expect(registeredToolConfig.description).toBe("Get the raw JSON response for Active Zone Minutes (AZM) time series data from Fitbit over a date range (max 1095 days). Returns total AZM plus breakdown by fat burn, cardio, and peak zones.");
    });

    it('should have correct parameters schema', () => {
      registerAzmTimeSeriesTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.parametersSchema).toEqual({
        startDate: CommonSchemas.startDate,
        endDate: CommonSchemas.endDate,
      });
    });
  });
});
