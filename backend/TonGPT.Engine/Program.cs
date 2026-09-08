using Microsoft.AspNetCore.HttpOverrides;
using Microsoft.EntityFrameworkCore;
using System.Threading.RateLimiting;
using TonGPT.Engine.Data;
using TonGPT.Engine.Middleware;
using TonGPT.Engine.Services;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddHttpClient();
// LAUNCH-FIX 1: bounded client for toncenter get-method calls. The default
// HttpClient timeout is 100s — a slow/throttled toncenter stacked up
// multi-second calls and pressured the thread pool (Kestrel heartbeat
// warning in the 2026-07-03 boot log). 8s is generous for runGetMethod.
builder.Services.AddHttpClient("toncenter", c => c.Timeout = TimeSpan.FromSeconds(8));
builder.Services.AddHostedService<SubscriptionWorker>();
builder.Services.AddHostedService<ChatRetentionJob>();

// ARCH-002: rate limiting. A per-IP fixed window throttles brute-force against
// the single API key and blunts DoS. Tunable via RateLimit:* config.
var rlPermit = builder.Configuration.GetValue<int>("RateLimit:PermitPerMinute", 120);
builder.Services.AddRateLimiter(options =>
{
    options.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(ctx =>
    {
        var ip = ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown";
        return RateLimitPartition.GetFixedWindowLimiter(ip, _ => new FixedWindowRateLimiterOptions
        {
            PermitLimit = rlPermit,
            Window = TimeSpan.FromMinutes(1),
            QueueLimit = 0,
        });
    });
});

// ARCH-001: honor X-Forwarded-Proto/For so the app sees the real client scheme
// when running behind a TLS-terminating proxy (the common deployment).
builder.Services.Configure<ForwardedHeadersOptions>(o =>
{
    o.ForwardedHeaders = ForwardedHeaders.XForwardedFor | ForwardedHeaders.XForwardedProto;
    // Proxies are trusted by the deployment; clear the default safe-list so the
    // forwarded headers from the edge proxy are honored.
    o.KnownNetworks.Clear();
    o.KnownProxies.Clear();
});

// Database Context
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

var app = builder.Build();

var connectionString = app.Configuration.GetConnectionString("DefaultConnection");
if (string.IsNullOrWhiteSpace(connectionString))
    throw new InvalidOperationException(
        "DefaultConnection is not configured. " +
        "Set it via environment variable: ConnectionStrings__DefaultConnection"
    );

// AUDIT-FIX (deploy reality): apply EF migrations on boot. Without this, a
// fresh Postgres (first Fly.io deploy, wiped volume) has no schema and every
// query 500s until someone manually runs `dotnet ef database update`.
// Disable with Database:MigrateOnStartup=false if migrations are a deploy step.
if (app.Configuration.GetValue("Database:MigrateOnStartup", true))
{
    using var migrationScope = app.Services.CreateScope();
    var db = migrationScope.ServiceProvider.GetRequiredService<AppDbContext>();
    var pending = db.Database.GetPendingMigrations().ToList();
    if (pending.Count > 0)
    {
        app.Logger.LogInformation("Applying {Count} pending EF migration(s): {Names}",
            pending.Count, string.Join(", ", pending));
        db.Database.Migrate();
    }
}

app.UseForwardedHeaders();

// ARCH-001: in production, enforce HSTS and (optionally) redirect to HTTPS so the
// API key never travels in cleartext. HTTPS redirect is on by default but can be
// disabled (Security:RequireHttpsRedirect=false) for setups where the edge proxy
// already guarantees TLS and a redirect would loop.
if (!app.Environment.IsDevelopment())
{
    app.UseHsts();
    if (app.Configuration.GetValue("Security:RequireHttpsRedirect", true))
        app.UseHttpsRedirection();

    // Loud, throttled warning if a production request still arrives over plain
    // HTTP (e.g. proxy not setting X-Forwarded-Proto) — the API key is exposed.
    app.Use(async (context, next) =>
    {
        if (!context.Request.IsHttps &&
            !string.Equals(context.Request.Headers["X-Forwarded-Proto"], "https", StringComparison.OrdinalIgnoreCase))
        {
            app.Logger.LogWarning(
                "Request received over plain HTTP in production from {Ip} to {Path}. " +
                "The API key may be exposed in transit — terminate TLS at the edge.",
                context.Connection.RemoteIpAddress, context.Request.Path);
        }
        await next();
    });
}

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// Rate limiting runs BEFORE auth so unauthenticated brute-force is throttled too.
app.UseRateLimiter();
app.UseMiddleware<ApiKeyMiddleware>();
app.UseAuthorization();

app.MapControllers();

app.Run();
