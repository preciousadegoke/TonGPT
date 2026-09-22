using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace TonGPT.Engine.Migrations
{
    /// <inheritdoc />
    public partial class AddPendingDowngrades : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<DateTime>(
                name: "PendingExpiry",
                table: "Users",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "PendingPlan",
                table: "Users",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "PendingStartsAt",
                table: "Users",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "Kind",
                table: "UpgradeQuotes",
                type: "text",
                nullable: false,
                defaultValue: "upgrade");

            migrationBuilder.AddColumn<DateTime>(
                name: "PendingExpiry",
                table: "UpgradeQuotes",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<int>(
                name: "PendingPlan",
                table: "UpgradeQuotes",
                type: "integer",
                nullable: true);

            migrationBuilder.AddColumn<DateTime>(
                name: "PendingStartsAt",
                table: "UpgradeQuotes",
                type: "timestamp with time zone",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            // An old schema cannot represent paid future coverage. Restore a
            // reviewed backup instead of silently deleting it during rollback.
            migrationBuilder.Sql("""
                LOCK TABLE "Users", "UpgradeQuotes" IN ACCESS EXCLUSIVE MODE;
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM "Users" WHERE "PendingPlan" IS NOT NULL OR "PendingStartsAt" IS NOT NULL OR "PendingExpiry" IS NOT NULL)
                       OR EXISTS (SELECT 1 FROM "UpgradeQuotes" WHERE "Kind" = 'downgrade')
                    THEN
                        RAISE EXCEPTION 'Cannot remove issued downgrade quotes or paid coverage; restore a reviewed backup for rollback.';
                    END IF;
                END $$;
                """);
            migrationBuilder.DropColumn(
                name: "PendingExpiry",
                table: "Users");

            migrationBuilder.DropColumn(
                name: "PendingPlan",
                table: "Users");

            migrationBuilder.DropColumn(
                name: "PendingStartsAt",
                table: "Users");

            migrationBuilder.DropColumn(
                name: "Kind",
                table: "UpgradeQuotes");

            migrationBuilder.DropColumn(
                name: "PendingExpiry",
                table: "UpgradeQuotes");

            migrationBuilder.DropColumn(
                name: "PendingPlan",
                table: "UpgradeQuotes");

            migrationBuilder.DropColumn(
                name: "PendingStartsAt",
                table: "UpgradeQuotes");
        }
    }
}
