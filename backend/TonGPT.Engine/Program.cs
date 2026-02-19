using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;

var builder = WebApplication.CreateBuilder(args);

// Add services to the container.
builder.Services.AddControllers();
builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();
builder.Services.AddHttpClient();
builder.Services.AddHostedService<TonGPT.Engine.Services.SubscriptionWorker>();

// Database Context
// Switching back to PostgreSQL
// builder.Services.AddDbContext<AppDbContext>(options =>
//    options.UseInMemoryDatabase("TonGPT"));
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseNpgsql(builder.Configuration.GetConnectionString("DefaultConnection")));

var app = builder.Build();

// Configure the HTTP request pipeline.
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

// app.UseHttpsRedirection();
// app.UseHttpsRedirection();
app.UseMiddleware<TonGPT.Engine.Middleware.ApiKeyMiddleware>();
app.UseAuthorization();

app.MapControllers();

app.Run();
