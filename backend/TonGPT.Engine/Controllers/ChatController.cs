using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using TonGPT.Engine.Data;
using TonGPT.Engine.Models;
using System.Threading.Tasks;
using System.Linq;
using System.Collections.Generic;

namespace TonGPT.Engine.Controllers
{
    [ApiController]
    [Route("api/[controller]")]
    public class ChatController : ControllerBase
    {
        private readonly AppDbContext _context;

        public ChatController(AppDbContext context)
        {
            _context = context;
        }

        public class ChatMessageDto
        {
            public long TelegramId { get; set; }
            public string? UserMessage { get; set; }
            public string? AiResponse { get; set; }
            public DateTime? Timestamp { get; set; }
        }

        [HttpPost("message")]
        public async Task<IActionResult> SaveMessage([FromBody] ChatMessageDto messageDto)
        {
            var msg = new ChatMessage
            {
                TelegramId = messageDto.TelegramId.ToString(),
                UserMessage = messageDto.UserMessage,
                AiResponse = messageDto.AiResponse,
                Timestamp = messageDto.Timestamp ?? DateTime.UtcNow
            };

            _context.ChatMessages.Add(msg);
            await _context.SaveChangesAsync();

            return Ok(new { status = "Success", id = msg.Id });
        }

        [HttpGet("history/{telegramId}")]
        public async Task<IActionResult> GetHistory(string telegramId, [FromQuery] int limit = 10)
        {
            var messages = await _context.ChatMessages
                .Where(m => m.TelegramId == telegramId)
                .OrderByDescending(m => m.Timestamp)
                .Take(limit)
                .OrderBy(m => m.Timestamp) // Return in chronological order
                .Select(m => new 
                {
                    userMessage = m.UserMessage,
                    aiResponse = m.AiResponse,
                    timestamp = m.Timestamp
                })
                .ToListAsync();

            return Ok(messages);
        }
    }
}
