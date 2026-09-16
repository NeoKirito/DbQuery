using System.Text.Json.Serialization;

namespace DbQuery.Models;

public class QueryRequest
{
    [JsonPropertyName("file_path")]
    public string FilePath { get; set; } = string.Empty;

    [JsonPropertyName("params")]
    public Dictionary<string, string> Params { get; set; } = new();
}

public class QueryResult
{
    [JsonPropertyName("columns")]
    public List<string> Columns { get; set; } = new();

    [JsonPropertyName("rows")]
    public List<List<object?>> Rows { get; set; } = new();

    [JsonPropertyName("elapsed")]
    public double Elapsed { get; set; }

    [JsonPropertyName("row_count")]
    public int RowCount { get; set; }

    [JsonPropertyName("col_count")]
    public int ColCount { get; set; }

    [JsonPropertyName("truncated")]
    public bool Truncated { get; set; }

    [JsonPropertyName("max_rows")]
    public int MaxRows { get; set; } = 5000;

    [JsonPropertyName("option_warnings")]
    public List<string> OptionWarnings { get; set; } = new();

    [JsonPropertyName("error")]
    public string? Error { get; set; }
}

public class ExportRequest
{
    [JsonPropertyName("file_path")]
    public string FilePath { get; set; } = string.Empty;

    [JsonPropertyName("params")]
    public Dictionary<string, object?>? Params { get; set; }

    [JsonPropertyName("columns")]
    public List<string> Columns { get; set; } = new();

    [JsonPropertyName("rows")]
    public List<List<object?>> Rows { get; set; } = new();

    [JsonPropertyName("elapsed")]
    public double Elapsed { get; set; }
}

public class OptionsRequest
{
    [JsonPropertyName("file_path")]
    public string FilePath { get; set; } = string.Empty;

    [JsonPropertyName("param_name")]
    public string ParamName { get; set; } = string.Empty;
}

public class OptionsResponse
{
    [JsonPropertyName("options")]
    public List<OptionItem> Options { get; set; } = new();

    [JsonPropertyName("warning")]
    public string Warning { get; set; } = string.Empty;
}

public class ConnectionTestResponse
{
    [JsonPropertyName("success")]
    public bool Success { get; set; }

    [JsonPropertyName("message")]
    public string Message { get; set; } = string.Empty;
}
