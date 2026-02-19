using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace TonGPT.Engine.Migrations
{
    /// <inheritdoc />
    public partial class AddWalletAddress : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<string>(
                name: "WalletAddress",
                table: "Users",
                type: "text",
                nullable: true);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "WalletAddress",
                table: "Users");
        }
    }
}
