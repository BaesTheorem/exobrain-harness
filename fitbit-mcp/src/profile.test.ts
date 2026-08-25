import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { registerProfileTool } from './profile.js';
import * as utils from './utils.js';

// Mock the utils module
vi.mock('./utils.js', () => ({
  registerTool: vi.fn(),
  handleFitbitApiCall: vi.fn()
}));

describe('Profile Tool', () => {
  let mockServer: McpServer;
  let mockGetAccessToken: ReturnType<typeof vi.fn>;
  let mockRegisterTool: ReturnType<typeof vi.fn>;
  let mockHandleFitbitApiCall: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    // Create a mock server with minimal required properties
    mockServer = {} as McpServer;

    mockGetAccessToken = vi.fn();
    mockRegisterTool = vi.mocked(utils.registerTool);
    mockHandleFitbitApiCall = vi.mocked(utils.handleFitbitApiCall);
    
    // Clear all mocks before each test
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  describe('registerProfileTool', () => {
    it('should register the get_profile tool with correct configuration', () => {
      registerProfileTool(mockServer, mockGetAccessToken);

      expect(mockRegisterTool).toHaveBeenCalledOnce();
      expect(mockRegisterTool).toHaveBeenCalledWith(mockServer, {
        name: 'get_profile',
        description: "Get the raw JSON response for the user's Fitbit profile.",
        parametersSchema: {},
        handler: expect.any(Function)
      });
    });

    it('should call handler with correct endpoint and parameters', async () => {
      const mockProfileData = {
        user: {
          fullName: 'John Doe',
          age: 30,
          gender: 'MALE',
          height: 175,
          weight: 70,
          avatar: 'https://example.com/avatar.jpg',
          memberSince: '2020-01-01'
        }
      };

      mockHandleFitbitApiCall.mockResolvedValue({
        content: [{ type: 'text', text: JSON.stringify(mockProfileData) }]
      });

      registerProfileTool(mockServer, mockGetAccessToken);

      // Get the handler function that was registered
      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      // Call the handler
      const result = await handler();

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'profile.json',
        {},
        mockGetAccessToken,
        {
          errorContext: 'profile data'
        }
      );

      expect(result).toEqual({
        content: [{ type: 'text', text: JSON.stringify(mockProfileData) }]
      });
    });

    it('should handle API errors gracefully', async () => {
      const errorMessage = 'API rate limit exceeded';
      mockHandleFitbitApiCall.mockRejectedValue(new Error(errorMessage));

      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler()).rejects.toThrow(errorMessage);

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'profile.json',
        {},
        mockGetAccessToken,
        {
          errorContext: 'profile data'
        }
      );
    });

    it('should handle null access token', async () => {
      mockGetAccessToken.mockResolvedValue(null);
      mockHandleFitbitApiCall.mockRejectedValue(new Error('No access token available'));

      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await expect(handler()).rejects.toThrow('No access token available');
    });

    it('should use correct endpoint URL', async () => {
      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await handler().catch(() => {}); // Ignore errors, just test the call

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        'profile.json',
        expect.any(Object),
        expect.any(Function),
        expect.objectContaining({
          errorContext: 'profile data'
        })
      );
    });

    it('should pass empty parameters object', async () => {
      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      const handler = registeredToolConfig.handler;

      await handler().catch(() => {}); // Ignore errors, just test the call

      expect(mockHandleFitbitApiCall).toHaveBeenCalledWith(
        expect.any(String),
        {},
        expect.any(Function),
        expect.any(Object)
      );
    });

    it('should have empty parameters schema', () => {
      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.parametersSchema).toEqual({});
    });

    it('should use correct tool name and description', () => {
      registerProfileTool(mockServer, mockGetAccessToken);

      const registeredToolConfig = mockRegisterTool.mock.calls[0][1];
      
      expect(registeredToolConfig.name).toBe('get_profile');
      expect(registeredToolConfig.description).toBe("Get the raw JSON response for the user's Fitbit profile.");
    });
  });
});