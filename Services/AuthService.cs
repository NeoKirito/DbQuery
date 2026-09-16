using Microsoft.Data.SqlClient;

namespace DbQuery.Services;

public interface IAuthService
{
    Task<(bool Success, string? DisplayName, string? Error)> AuthenticateAsync(string username, string password);
}

public class AuthService : IAuthService
{
    private readonly string _connectionString;

    // 默认内置演示操作员
    private static readonly Dictionary<string, (string Password, string DisplayName)> BuiltinUsers = new(StringComparer.OrdinalIgnoreCase)
    {
        { "admin", ("123456", "系统管理员") },
        { "czybm", ("123456", "操作员") },
        { "demo_user", ("secretpassword", "演示用户") }
    };

    public AuthService(IConfiguration config)
    {
        _connectionString = config.GetConnectionString("DefaultConnection") ?? string.Empty;
    }

    public async Task<(bool Success, string? DisplayName, string? Error)> AuthenticateAsync(string username, string password)
    {
        if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
        {
            return (false, null, "账号或密码不能为空。");
        }

        username = username.Trim();

        // 1. 若配置了 SQL Server 连接，优先尝试从 qx_czyxx 表中验证操作员
        if (!string.IsNullOrWhiteSpace(_connectionString))
        {
            try
            {
                await using var conn = new SqlConnection(_connectionString);
                await conn.OpenAsync();

                await using var cmd = conn.CreateCommand();
                cmd.CommandText = "SELECT czybm, czyxm, czymm, qybz FROM qx_czyxx WHERE czybm = @username";
                cmd.Parameters.AddWithValue("@username", username);

                await using var reader = await cmd.ExecuteReaderAsync();
                if (await reader.ReadAsync())
                {
                    var dbPwd = reader.IsDBNull(2) ? "" : reader.GetString(2).Trim();
                    var qybz = reader.IsDBNull(3) ? 1 : Convert.ToInt32(reader.GetValue(3));
                    var displayName = reader.IsDBNull(1) ? username : reader.GetString(1).Trim();

                    if (qybz != 1)
                    {
                        return (false, null, "该操作员已被禁用，无法登录。");
                    }

                    if (string.Equals(dbPwd, password.Trim(), StringComparison.Ordinal))
                    {
                        return (true, displayName, null);
                    }

                    return (false, null, "操作员密码错误，请重新输入。");
                }
            }
            catch
            {
                // 若数据库不存在该表或未连接，降级到内置用户验证
            }
        }

        // 2. 内置用户降级验证
        if (BuiltinUsers.TryGetValue(username, out var uInfo))
        {
            if (uInfo.Password == password.Trim())
            {
                return (true, uInfo.DisplayName, null);
            }
            return (false, null, "操作员密码错误，请重新输入。");
        }

        // 允许任意开发/演示账号登录
        return (true, username, null);
    }
}
