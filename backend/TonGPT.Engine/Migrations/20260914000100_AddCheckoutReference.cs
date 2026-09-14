using Microsoft.EntityFrameworkCore;
using Microsoft.EntityFrameworkCore.Infrastructure;
using Microsoft.EntityFrameworkCore.Migrations;
using TonGPT.Engine.Data;

namespace TonGPT.Engine.Migrations;

[DbContext(typeof(AppDbContext))]
[Migration("20260914000100_AddCheckoutReference")]
public partial class AddCheckoutReference : Migration
{
    protected override void Up(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.AddColumn<string>(name: "CheckoutReference", table: "Payments",
            type: "character varying(128)", maxLength: 128, nullable: true);
        migrationBuilder.CreateIndex(name: "IX_Payments_TelegramUserId_CheckoutReference", table: "Payments",
            columns: new[] { "TelegramUserId", "CheckoutReference" });
    }
    protected override void Down(MigrationBuilder migrationBuilder)
    {
        migrationBuilder.DropIndex(name: "IX_Payments_TelegramUserId_CheckoutReference", table: "Payments");
        migrationBuilder.DropColumn(name: "CheckoutReference", table: "Payments");
    }
}
