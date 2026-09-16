using System.Collections.Concurrent;
using System.Security.Cryptography;

namespace DbQuery.Services;

public interface IEmbedSessionService
{
    string CreateEmbedSession(string username, int ttlMinutes = 60);
    string? ValidateEmbedSession(string token);
    void InvalidateEmbedSession(string token);
    string CreateSsoTicket(string username, string nextUrl = "/", int ttlSeconds = 60);
    (string username, string nextUrl)? ConsumeSsoTicket(string ticket);
}

public class EmbedSessionService : IEmbedSessionService
{
    private class SessionData
    {
        public string Username { get; set; } = string.Empty;
        public DateTime ExpiresAt { get; set; }
    }

    private class TicketData
    {
        public string Username { get; set; } = string.Empty;
        public string NextUrl { get; set; } = "/";
        public DateTime ExpiresAt { get; set; }
    }

    private readonly ConcurrentDictionary<string, SessionData> _sessions = new();
    private readonly ConcurrentDictionary<string, TicketData> _tickets = new();

    public string CreateEmbedSession(string username, int ttlMinutes = 60)
    {
        PurgeExpired();
        var token = GenerateSecureToken();
        _sessions[token] = new SessionData
        {
            Username = username,
            ExpiresAt = DateTime.UtcNow.AddMinutes(ttlMinutes)
        };
        return token;
    }

    public string? ValidateEmbedSession(string token)
    {
        PurgeExpired();
        if (_sessions.TryGetValue(token, out var data) && data.ExpiresAt > DateTime.UtcNow)
        {
            return data.Username;
        }
        return null;
    }

    public void InvalidateEmbedSession(string token)
    {
        _sessions.TryRemove(token, out _);
    }

    public string CreateSsoTicket(string username, string nextUrl = "/", int ttlSeconds = 60)
    {
        PurgeExpired();
        var ticket = GenerateSecureToken();
        _tickets[ticket] = new TicketData
        {
            Username = username,
            NextUrl = nextUrl,
            ExpiresAt = DateTime.UtcNow.AddSeconds(ttlSeconds)
        };
        return ticket;
    }

    public (string username, string nextUrl)? ConsumeSsoTicket(string ticket)
    {
        PurgeExpired();
        if (_tickets.TryRemove(ticket, out var data) && data.ExpiresAt > DateTime.UtcNow)
        {
            return (data.Username, data.NextUrl);
        }
        return null;
    }

    private void PurgeExpired()
    {
        var now = DateTime.UtcNow;
        foreach (var kv in _sessions)
        {
            if (kv.Value.ExpiresAt <= now) _sessions.TryRemove(kv.Key, out _);
        }
        foreach (var kv in _tickets)
        {
            if (kv.Value.ExpiresAt <= now) _tickets.TryRemove(kv.Key, out _);
        }
    }

    private static string GenerateSecureToken()
    {
        var bytes = new byte[24];
        RandomNumberGenerator.Fill(bytes);
        return Convert.ToBase64String(bytes).Replace("+", "-").Replace("/", "_").TrimEnd('=');
    }
}
