using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Models;

namespace TonGPT.Engine.Data
{
    public class AppDbContext : DbContext
    {
        public AppDbContext(DbContextOptions<AppDbContext> options) : base(options) { }

        public DbSet<User> Users { get; set; }
        public DbSet<Payment> Payments { get; set; }
        public DbSet<ChatMessage> ChatMessages { get; set; }
        public DbSet<ActivityLog> ActivityLogs { get; set; }

        protected override void OnModelCreating(ModelBuilder modelBuilder)
        {
            base.OnModelCreating(modelBuilder);
            
            modelBuilder.Entity<User>()
                .HasIndex(u => u.TelegramId)
                .IsUnique();

            modelBuilder.Entity<ChatMessage>()
                .HasIndex(c => c.TelegramId);

            modelBuilder.Entity<ActivityLog>()
                .HasIndex(a => a.TelegramId);
        }
    }
}
