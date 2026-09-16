using System.Text.Json.Serialization;

namespace DbQuery.Models;

public class OptionItem
{
    [JsonPropertyName("value")]
    public string Value { get; set; } = string.Empty;

    [JsonPropertyName("label")]
    public string Label { get; set; } = string.Empty;
}

public class ParamDef
{
    [JsonPropertyName("name")]
    public string Name { get; set; } = string.Empty;

    [JsonPropertyName("label")]
    public string Label { get; set; } = string.Empty;

    [JsonPropertyName("ptype")]
    public string Ptype { get; set; } = "text";

    [JsonPropertyName("options")]
    public List<string> Options { get; set; } = new();

    [JsonPropertyName("option_items")]
    public List<OptionItem> OptionItems { get; set; } = new();

    [JsonPropertyName("default")]
    public string Default { get; set; } = string.Empty;

    [JsonPropertyName("raw_default")]
    public string RawDefault { get; set; } = string.Empty;

    [JsonPropertyName("placeholder")]
    public string Placeholder { get; set; } = string.Empty;

    [JsonPropertyName("required")]
    public bool Required { get; set; }

    [JsonPropertyName("width")]
    public string Width { get; set; } = string.Empty;

    [JsonPropertyName("dynamic_options")]
    public bool DynamicOptions { get; set; }

    [JsonPropertyName("searchable")]
    public bool Searchable { get; set; }

    [JsonPropertyName("allow_custom")]
    public bool AllowCustom { get; set; }

    [JsonPropertyName("options_sql")]
    public string? OptionsSql { get; set; }
}

public class QryForm
{
    [JsonPropertyName("title")]
    public string Title { get; set; } = string.Empty;

    [JsonPropertyName("group")]
    public string Group { get; set; } = "默认";

    [JsonPropertyName("description")]
    public string Description { get; set; } = string.Empty;

    [JsonPropertyName("web_enabled")]
    public bool WebEnabled { get; set; }

    [JsonPropertyName("query_type")]
    public string QueryType { get; set; } = "select";

    [JsonPropertyName("file_path")]
    public string FilePath { get; set; } = string.Empty;

    [JsonPropertyName("params")]
    public List<ParamDef> Params { get; set; } = new();

    [JsonIgnore]
    public string Sql { get; set; } = string.Empty;
}
