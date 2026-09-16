using System.Text.RegularExpressions;

namespace DbQuery.Services;

public interface ISqlSafetyService
{
    (bool IsSafe, string? ErrorMessage) ValidateSql(string sql, string queryType = "select");
}

public class SqlSafetyService : ISqlSafetyService
{
    private static readonly HashSet<string> AllowedStatements = new(StringComparer.OrdinalIgnoreCase)
    {
        "SELECT", "WITH", "EXEC", "EXECUTE"
    };

    private static readonly HashSet<string> BlockedKeywords = new(StringComparer.OrdinalIgnoreCase)
    {
        "DROP", "TRUNCATE", "ALTER", "GRANT", "REVOKE", "SHUTDOWN", "XP_CMDSHELL"
    };

    public (bool IsSafe, string? ErrorMessage) ValidateSql(string sql, string queryType = "select")
    {
        if (string.IsNullOrWhiteSpace(sql))
        {
            return (false, "SQL 语句不能为空。");
        }

        // 去除 SQL 注释
        var cleanSql = Regex.Replace(sql, @"--.*?$", "", RegexOptions.Multiline);
        cleanSql = Regex.Replace(cleanSql, @"/\*.*?\*/", "", RegexOptions.Singleline).Trim();

        if (string.IsNullOrWhiteSpace(cleanSql))
        {
            return (false, "SQL 语句不能为空。");
        }

        // 提取第一个关键字
        var match = Regex.Match(cleanSql, @"^\s*([A-Za-z]+)");
        if (!match.Success)
        {
            return (false, "无法识别 SQL 语句类型。");
        }

        var firstWord = match.Groups[1].Value.ToUpperInvariant();
        if (!AllowedStatements.Contains(firstWord))
        {
            return (false, $"仅支持只读查询语句 (SELECT, WITH, EXEC)，检测到不支持的开头部语句: {firstWord}");
        }

        // 检查高危词
        var words = Regex.Matches(cleanSql, @"\b([A-Za-z_]+)\b")
            .Select(m => m.Groups[1].Value)
            .ToList();

        foreach (var w in words)
        {
            if (BlockedKeywords.Contains(w))
            {
                return (false, $"检测到受限或高风险 SQL 关键字: {w}");
            }
        }

        return (true, null);
    }
}
