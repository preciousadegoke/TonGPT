using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace TonGPT.Engine.Migrations
{
    /// <inheritdoc />
    public partial class AddUpgradeQuotes : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<long>(
                name: "EntitlementVersion",
                table: "Users",
                type: "bigint",
                nullable: false,
                defaultValue: 0L);

            migrationBuilder.CreateTable(
                name: "PaymentReconciliations",
                columns: table => new
                {
                    PaymentId = table.Column<Guid>(type: "uuid", nullable: false),
                    QuoteReference = table.Column<string>(type: "text", nullable: true),
                    Reason = table.Column<string>(type: "text", nullable: false),
                    Currency = table.Column<string>(type: "text", nullable: false),
                    ActualUnits = table.Column<decimal>(type: "numeric(28,9)", precision: 28, scale: 9, nullable: false),
                    ExpectedUnits = table.Column<long>(type: "bigint", nullable: true),
                    PaidAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_PaymentReconciliations", x => x.PaymentId);
                });

            migrationBuilder.CreateTable(
                name: "UpgradeQuotes",
                columns: table => new
                {
                    Reference = table.Column<string>(type: "character varying(32)", maxLength: 32, nullable: false),
                    TelegramId = table.Column<string>(type: "text", nullable: false),
                    FromPlan = table.Column<int>(type: "integer", nullable: false),
                    TargetPlan = table.Column<int>(type: "integer", nullable: false),
                    SubscriptionExpiry = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    EntitlementVersion = table.Column<long>(type: "bigint", nullable: false),
                    Provider = table.Column<string>(type: "text", nullable: false),
                    ExpectedUnits = table.Column<long>(type: "bigint", nullable: false),
                    CreatedAt = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    ValidUntil = table.Column<DateTime>(type: "timestamp with time zone", nullable: false),
                    AppliedPaymentId = table.Column<Guid>(type: "uuid", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_UpgradeQuotes", x => x.Reference);
                });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "PaymentReconciliations");

            migrationBuilder.DropTable(
                name: "UpgradeQuotes");

            migrationBuilder.DropColumn(
                name: "EntitlementVersion",
                table: "Users");
        }
    }
}
