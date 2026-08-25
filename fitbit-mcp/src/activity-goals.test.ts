import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerActivityGoalsTool } from './activity-goals.js';
import * as utils from './utils.js';
import { z } from 'zod';

// Mock the utils module
vi.mock('./utils.js', () => ({
  registerTool: vi.fn(),
  handleFitbitApiCall: vi.fn()
}));

describe('Activity Goals Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn().mockResolvedValue('test_access_token');
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerActivityGoalsTool', () => {
    it('should register the get_activity_goals tool with correct configuration', () => {
      registerActivityGoalsTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.name).toBe('get_activity_goals');
      expect(registeredToolConfig.description).toBe("Get the raw JSON response for user\'s activity goals from Fitbit. Supports \'daily\' and \'weekly\' periods. Returns goal values for steps, distance, calories, floors, active minutes, and active zone minutes.");
      // Compare schema properties instead of the schema object itself
      expect(registeredToolConfig.parametersSchema.period).toBeInstanceOf(z.ZodEnum);
      expect(registeredToolConfig.parametersSchema.period._def.values).toEqual(['daily', 'weekly']);
      expect(registeredToolConfig.parametersSchema.period._def.description).toBe("Goal period - either \'daily\' or \'weekly\'");
      expect(registeredToolConfig.handler).toEqual(expect.any(Function));
    });

    it('should call handler with correct endpoint and parameters for "daily" period', async () => {
      const mockGoalsData = { goals: { steps: 10000 } };
      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockGoalsData) }]
      });

      registerActivityGoalsTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;
      const result = await handler({ period: 'daily' });

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'activities/goals/daily.json',
        { period: 'daily' },
        mockGetAccessToken,
        { errorContext: "period 'daily'" }
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockGoalsData) }]
      });
    });

    it('should call handler with correct endpoint and parameters for "weekly" period', async () => {
      const mockGoalsData = { goals: { activeMinutes: 60 } };
      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockGoalsData) }]
      });

      registerActivityGoalsTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;
      const result = await handler({ period: 'weekly' });

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'activities/goals/weekly.json',
        { period: 'weekly' },
        mockGetAccessToken,
        { errorContext: "period 'weekly'" }
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockGoalsData) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'API error';
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerActivityGoalsTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;

      await expect(handler({ period: 'daily' })).rejects.toThrow(errorMessage);
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'activities/goals/daily.json',
        { period: 'daily' },
        mockGetAccessToken,
        { errorContext: "period 'daily'" }
      );
    });

    it('should handle null access token', async () => {
      mockGetAccessToken.mockResolvedValue(null);
      // Simulate the behavior of handleFitbitApiCall when token is null, 
      // which might be to throw or return a specific error structure.
      // For this test, let's assume it throws, consistent with profile.test.ts
      mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available'));

      registerActivityGoalsTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;

      await expect(handler({ period: 'weekly' })).rejects.toThrow('No access token available');
    });
    
    it('should have correct parameter schema for period', () => {
      registerActivityGoalsTool(mockServer, mockGetAccessToken);
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const schema = z.object(registeredToolConfig.parametersSchema);

      // Test valid inputs
      expect(schema.safeParse({ period: 'daily' }).success).toBe(true);
      expect(schema.safeParse({ period: 'weekly' }).success).toBe(true);

      // Test invalid input
      const invalidResult = schema.safeParse({ period: 'monthly' });
      expect(invalidResult.success).toBe(false);
      if (!invalidResult.success) {
        expect(invalidResult.error.errors[0].message).toBe("Invalid enum value. Expected 'daily' | 'weekly', received 'monthly'");
      }
    });
  });
});
