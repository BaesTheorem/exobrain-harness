import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { z } from 'zod';
import { registerActivityTimeSeriesTool } from './activity-timeseries.js';
import * as utils from './utils.js';
import { CommonSchemas } from './utils.js'; // Import CommonSchemas

// Mock the utils module
vi.mock('./utils.js', async (importOriginal) => {
  const actualUtils = await importOriginal<typeof utils>();
  return {
    ...actualUtils, // Import and retain all original exports
    registerTool: vi.fn(),
    handleFitbitApiCall: vi.fn(),
  };
});

describe('Activity Time Series Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  const validParams = {
    resourcePath: 'steps',
    startDate: '2024-01-01',
    endDate: '2024-01-07',
  };

  const mockActivityTimeSeriesData = {
    'activities-steps': [
      { dateTime: '2024-01-01', value: '1000' },
      { dateTime: '2024-01-02', value: '1500' },
    ],
  };

  beforeEach(() => {
    mockServer = {} as McpServer;
    mockGetAccessToken = vi.fn();
    // Correctly mock functions from the imported 'utils' module
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerActivityTimeSeriesTool', () => {
    it('should register the get_activity_timeseries tool with correct configuration', () => {
      registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.name).toBe('get_activity_timeseries');
      expect(registeredToolConfig.description).toBe(
        "Get the raw JSON response for activity time series data from Fitbit over a date range (max 30 days). Supports various resource paths like 'steps', 'distance', 'calories', 'activityCalories', 'caloriesBMR'."
      );
      expect(registeredToolConfig.parametersSchema).toEqual({
        resourcePath: expect.any(z.ZodEnum),
        startDate: CommonSchemas.startDate,
        endDate: CommonSchemas.endDate,
      });
      expect(registeredToolConfig.handler).toEqual(expect.any(Function));
    });

    it('should call handler with correct endpoint and parameters for a valid request', async () => {
      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockActivityTimeSeriesData) }],
      });

      registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;
      const result = await handler(validParams);

      const expectedEndpoint = `activities/${validParams.resourcePath}/date/${validParams.startDate}/${validParams.endDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        validParams,
        mockGetAccessToken,
        {
          errorContext: `resource '${validParams.resourcePath}' from ${validParams.startDate} to ${validParams.endDate}`,
        }
      );
      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockActivityTimeSeriesData) }],
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'Fitbit API error';
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);
      const handler = mockRegisterTool.mock.calls[0][1].handler;

      await expect(handler(validParams)).rejects.toThrow(errorMessage);

      const expectedEndpoint = `activities/${validParams.resourcePath}/date/${validParams.startDate}/${validParams.endDate}.json`;
      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expectedEndpoint,
        validParams,
        mockGetAccessToken,
        {
          errorContext: `resource '${validParams.resourcePath}' from ${validParams.startDate} to ${validParams.endDate}`,
        }
      );
    });

    it('should handle null access token', async () => {
        mockGetAccessToken.mockResolvedValue(null);
        // Simulate handleFitbitApiCall throwing an error when no token is present
        mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available'));
  
        registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;
  
        await expect(handler(validParams)).rejects.toThrow('No access token available');
      });

    // Test for different resource paths
    const resourcePathsToTest = [
        'steps', 
        'distance', 
        'calories', 
        'activityCalories', 
        'caloriesBMR',
        'tracker/activityCalories',
        'tracker/calories',
        'tracker/distance'
    ];
    resourcePathsToTest.forEach(resourcePath => {
      it(`should construct the correct endpoint for resourcePath: ${resourcePath}`, async () => {
        const params = { ...validParams, resourcePath };
        registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);
        const handler = mockRegisterTool.mock.calls[0][1].handler;

        // Catch expected error if API call fails, we only care about the endpoint construction
        await handler(params).catch(() => {}); 

        const expectedEndpoint = `activities/${resourcePath}/date/${params.startDate}/${params.endDate}.json`;
        expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
          expectedEndpoint,
          params,
          mockGetAccessToken,
          expect.any(Object) // errorContext can vary, so not strictly checking its content here
        );
      });
    });

    it('should have correct parameter schema definition', () => {
        registerActivityTimeSeriesTool(mockServer, mockGetAccessToken);
        const schema = mockRegisterTool.mock.calls[0][1].parametersSchema;
  
        // Test resourcePath enum
        const validResourcePaths = [
            'steps', 'distance', 'calories', 'activityCalories', 'caloriesBMR',
            'tracker/activityCalories', 'tracker/calories', 'tracker/distance'
        ];
        validResourcePaths.forEach(rp => {
            expect(schema.resourcePath.safeParse(rp).success).toBe(true);
        });
        expect(schema.resourcePath.safeParse('invalidPath').success).toBe(false);
  
        // Test startDate format
        expect(schema.startDate.safeParse('2024-12-31').success).toBe(true);
        expect(schema.startDate.safeParse('2024/12/31').success).toBe(false); // Invalid format
        expect(schema.startDate.safeParse('not-a-date').success).toBe(false);
  
        // Test endDate format
        expect(schema.endDate.safeParse('2025-01-01').success).toBe(true);
        expect(schema.endDate.safeParse('2025/01/01').success).toBe(false); // Invalid format
        expect(schema.endDate.safeParse('another-invalid-date').success).toBe(false);
      });
  });
});
