using System.Security.Cryptography;
using Microsoft.Extensions.Primitives;

namespace TonGPT.Engine.Middleware;

/// <summary>
/// Validates X-Api-Key or Authorization header using constant-time comparison (timing-attack safe).
/// </summary>
public class ApiKeyMiddleware
{
    private readonly RequestDelegate _next;
    private readonly byte[] _apiKeyBytes;
    private readonly ILogger<ApiKeyMiddleware> _logger;

    public ApiKeyMiddleware(RequestDelegate next, IConfiguration config, ILogger<ApiKeyMiddleware> logger)
    {
        _next = next;
        _logger = logger;
        var key = config["EngineApiKey"] ?? config["ApiKey"] ?? Environment.GetEnvironmentVariable("ENGINE_API_KEY");
        if (string.IsNullOrEmpty(key))
        {
            _logger.LogWarning("EngineApiKey not configured - API key middleware will reject all requests. Set ENGINE_API_KEY or EngineApiKey.");
            _apiKeyBytes = Array.Empty<byte>();
        }
        else
        {
            _apiKeyBytes = System.Text.Encoding.UTF8.GetBytes(key);
        }
    }

    public async Task InvokeAsync(HttpContext context)
    {
        // Exempt Swagger in development only
        if (context.Request.Path.StartsWithSegments("/swagger", StringComparison.OrdinalIgnoreCase))
        {
            await _next(context);
            return;
        }

        if (_apiKeyBytes.Length == 0)
        {
            context.Response.StatusCode = 503;
            await context.Response.WriteAsJsonAsync(new { message = "API key not configured." });
            return;
        }

        string? extracted = null;
        if (context.Request.Headers.TryGetValue("X-Api-Key", out var xApiKey) && !StringValues.IsNullOrEmpty(xApiKey))
            extracted = xApiKey.ToString();
        else if (context.Request.Headers.Authorization.Count > 0)
        {
            var auth = context.Request.Headers.Authorization.ToString();
            if (auth.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase))
                extracted = auth["Bearer ".Length..].Trim();
        }

        if (string.IsNullOrEmpty(extracted))
        {
            context.Response.StatusCode = 401;
            await context.Response.WriteAsJsonAsync(new { message = "Missing X-Api-Key or Authorization: Bearer." });
            return;
        }

        var extractedBytes = System.Text.Encoding.UTF8.GetBytes(extracted);
        if (extractedBytes.Length != _apiKeyBytes.Length || !CryptographicOperations.FixedTimeEquals(_apiKeyBytes, extractedBytes))
        {
            context.Response.StatusCode = 403;
            await context.Response.WriteAsJsonAsync(new { message = "Invalid API key." });
            return;
        }

        await _next(context);
    }
}
