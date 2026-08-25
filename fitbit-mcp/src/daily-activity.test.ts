import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerDailyActivityTool } from './daily-activity.js';
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

describe('DailyActivity Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn();
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerDailyActivityTool', () => {
    const testDate = '2023-03-15';

    it('should register the get_daily_activity_summary tool with correct configuration', () => {
      registerDailyActivityTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      expect(mockRegisterTool).toHaveBeenCalledWith(mockServer, {
        name: 'get_daily_activity_summary',
        description: "Get the raw JSON response for daily activity summary from Fitbit for a specific date. Includes goals, steps, calories, distances, and heart rate zones. Requires a 'date' parameter in YYYY-MM-DD format.",
        parametersSchema: {
          date: CommonSchemas.date,
        },
        handler: expect.any(Function)
      });
    });

    it('should call handler with correct endpoint and parameters', async () => {
      const mockDailyActivityResponse = {
        activities: [],
        goals: { activeMinutes: 30, caloriesOut: 2500, distance: 5, floors: 10, steps: 10000 },
        summary: { 
          activityCalories: 500, 
          caloriesOut: 2800, 
          steps: 12000, 
          distances: [{activity: 'total', distance: 8.5}],
          heartRateZones: [
            { name: 'Out of Range', minutes: 1000, caloriesOut: 1500},
            { name: 'Fat Burn', minutes: 60, caloriesOut: 300},
            { name: 'Cardio', minutes: 30, caloriesOut: 200},
            { name: 'Peak', minutes: 10, caloriesOut: 100}
          ],
          restingHeartRate: 60
        }
      };

      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockDailyActivityResponse) }]
      });

      registerDailyActivityTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      const result = await handler({ date: testDate });

      const expectedEndpoint = `activities/date/${testDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        { date: testDate },
        mockGetAccessToken,
        {
          errorContext: `date '${testDate}'`
        }
      );

      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockDailyActivityResponse) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'Fitbit API error';
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerDailyActivityTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler({ date: testDate })).rejects.toThrow(errorMessage);

      const expectedEndpoint = `activities/date/${testDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        { date: testDate },
        mockGetAccessToken,
        {
          errorContext: `date '${testDate}'`
        }
      );
    });

    it('should handle null access token', async () => {
      mockGetAccessToken.mockResolvedValue(null);
      mockHandleFitbitApiCall.mockRejectedValue(new Error('Access token is null'));

      registerDailyActivityTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler({ date: testDate })).rejects.toThrow('Access token is null');
    });

    it('should use correct tool name and description', () => {
      registerDailyActivityTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.name).toBe('get_daily_activity_summary');
      expect(registeredToolConfig.description).toBe("Get the raw JSON response for daily activity summary from Fitbit for a specific date. Includes goals, steps, calories, distances, and heart rate zones. Requires a 'date' parameter in YYYY-MM-DD format.");
    });

    it('should have correct parameters schema', () => {
      registerDailyActivityTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.parametersSchema).toEqual({
        date: CommonSchemas.date,
      });
    });
  });
});
