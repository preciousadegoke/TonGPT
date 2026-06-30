using System.Collections.Concurrent;
using System.Security.Cryptography;
using Microsoft.Extensions.Primitives;

namespace TonGPT.Engine.Middleware;

/// <summary>
/// Validates X-Api-Key or Authorization header using constant-time comparison
/// (timing-attack safe), and locks out an IP after repeated auth failures
/// (ARCH-002 brute-force defense).
/// </summary>
public class ApiKeyMiddleware
{
    private readonly RequestDelegate _next;
    private readonly byte[] _apiKeyBytes;
    private readonly ILogger<ApiKeyMiddleware> _logger;
    private readonly IHostEnvironment _env;

    // Per-IP failed-auth tracking. Static so it survives across requests for the
    // lifetime of the process (the middleware is constructed per-pipeline).
    private static readonly ConcurrentDictionary<string, (int Count, DateTime WindowStart, DateTime LockedUntil)> _fails = new();
    private const int MaxFailsPerWindow = 10;
    private static readonly TimeSpan FailWindow = TimeSpan.FromMinutes(5);
    private static readonly TimeSpan LockoutDuration = TimeSpan.FromMinutes(15);

    public ApiKeyMiddleware(RequestDelegate next, IConfiguration config, ILogger<ApiKeyMiddleware> logger, IHostEnvironment env)
    {
        _next = next;
        _logger = logger;
        _env = env;
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
        // SEC-004: exempt Swagger ONLY in development (was unconditional).
        if (_env.IsDevelopment() &&
            context.Request.Path.StartsWithSegments("/swagger", StringComparison.OrdinalIgnoreCase))
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

        var ip = context.Connection.RemoteIpAddress?.ToString() ?? "unknown";

        // ARCH-002: if this IP is locked out, reject immediately (fail-closed).
        if (_fails.TryGetValue(ip, out var state) && DateTime.UtcNow < state.LockedUntil)
        {
            context.Response.StatusCode = 429;
            await context.Response.WriteAsJsonAsync(new { message = "Too many failed attempts. Try again later." });
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
            RecordFailure(ip);
            context.Response.StatusCode = 401;
            await context.Response.WriteAsJsonAsync(new { message = "Missing X-Api-Key or Authorization: Bearer." });
            return;
        }

        var extractedBytes = System.Text.Encoding.UTF8.GetBytes(extracted);
        if (extractedBytes.Length != _apiKeyBytes.Length || !CryptographicOperations.FixedTimeEquals(_apiKeyBytes, extractedBytes))
        {
            RecordFailure(ip);
            context.Response.StatusCode = 403;
            await context.Response.WriteAsJsonAsync(new { message = "Invalid API key." });
            return;
        }

        // Success — clear any failure state for this IP.
        _fails.TryRemove(ip, out _);
        await _next(context);
    }

    private void RecordFailure(string ip)
    {
        var now = DateTime.UtcNow;
        var updated = _fails.AddOrUpdate(
            ip,
            _ => (1, now, DateTime.MinValue),
            (_, s) =>
            {
                // Reset the counter if the window elapsed.
                if (now - s.WindowStart > FailWindow)
                    return (1, now, DateTime.MinValue);
                var count = s.Count + 1;
                var lockedUntil = count >= MaxFailsPerWindow ? now + LockoutDuration : s.LockedUntil;
                return (count, s.WindowStart, lockedUntil);
            });

        if (updated.Count >= MaxFailsPerWindow && updated.LockedUntil > now)
            _logger.LogWarning("Auth lockout: IP {Ip} locked until {Until} after {Count} failed attempts.",
                ip, updated.LockedUntil, updated.Count);
    }
}
