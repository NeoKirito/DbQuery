using System.Text.Json;
using System.Text.Json.Nodes;

namespace DbQuery.Services;

public class DbConfigModel
{
    public string Server { get; set; } = "localhost,1433";
    public string Database { get; set; } = "master";
    public string User { get; set; } = "sa";
    public string Password { get; set; } = string.Empty;
    public int QueryTimeout { get; set; } = 60;
    public int MaxRows { get; set; } = 5000;
}

public interface IConfigManagerService
{
    DbConfigModel GetConfig();
    bool SaveConfig(DbConfigModel config);
    string BuildConnectionString(DbConfigModel config);
}

public class ConfigManagerService : IConfigManagerService
{
    private readonly string _appSettingsPath;
    private readonly IConfiguration _config;

    public ConfigManagerService(IWebHostEnvironment env, IConfiguration config)
    {
        _appSettingsPath = Path.Combine(env.ContentRootPath, "appsettings.json");
        _config = config;
    }

    public DbConfigModel GetConfig()
    {
        var model = new DbConfigModel
        {
            QueryTimeout = _config.GetValue<int>("WebConfig:QueryTimeout", 60),
            MaxRows = _config.GetValue<int>("WebConfig:MaxRows", 5000)
        };

        var connStr = _config.GetConnectionString("DefaultConnection") ?? "";
        foreach (var part in connStr.Split(';', StringSplitOptions.RemoveEmptyEntries))
        {
            var kv = part.Split('=', 2);
            if (kv.Length == 2)
            {
                var k = kv[0].Trim().ToLowerInvariant();
                var v = kv[1].Trim();
                if (k == "server" || k == "data source") model.Server = v;
                else if (k == "database" || k == "initial catalog") model.Database = v;
                else if (k == "user id" || k == "uid" || k == "user") model.User = v;
                else if (k == "password" || k == "pwd") model.Password = v;
            }
        }

        return model;
    }

    public string BuildConnectionString(DbConfigModel config)
    {
        return $"Server={config.Server};Database={config.Database};User Id={config.User};Password={config.Password};TrustServerCertificate=True;";
    }

    public bool SaveConfig(DbConfigModel config)
    {
        if (!File.Exists(_appSettingsPath)) return false;

        try
        {
            var json = File.ReadAllText(_appSettingsPath);
            var node = JsonNode.Parse(json);
            if (node == null) return false;

            if (node["ConnectionStrings"] == null) node["ConnectionStrings"] = new JsonObject();
            node["ConnectionStrings"]!["DefaultConnection"] = BuildConnectionString(config);

            if (node["WebConfig"] == null) node["WebConfig"] = new JsonObject();
            node["WebConfig"]!["QueryTimeout"] = config.QueryTimeout;
            node["WebConfig"]!["MaxRows"] = config.MaxRows;

            File.WriteAllText(_appSettingsPath, node.ToJsonString(new JsonSerializerOptions { WriteIndented = true }));
            return true;
        }
        catch
        {
            return false;
        }
    }
}
