using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace TonGPT.Engine.Migrations
{
    /// <inheritdoc />
    public partial class AddConsentFields : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<DateTime>(
                name: "ConsentAt",
                table: "Users",
                type: "timestamp with time zone",
                nullable: true);

            migrationBuilder.AddColumn<string>(
                name: "ConsentVersion",
                table: "Users",
                type: "text",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "ConsentAt",
                table: "Users");

            migrationBuilder.DropColumn(
                name: "ConsentVersion",
                table: "Users");
        }
    }
}
