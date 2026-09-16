using System.Text;
using DbQuery.Models;

namespace DbQuery.Services;

public interface IFormParserService
{
    QryForm? ParseQryFile(string filePath);
    Dictionary<string, List<QryForm>> LoadAllForms(bool webOnly = true);
}

public class FormParserService : IFormParserService
{
    private readonly string _contentRoot;

    public FormParserService(IWebHostEnvironment env)
    {
        _contentRoot = env.ContentRootPath;
    }

    public QryForm? ParseQryFile(string filePath)
    {
        var fullPath = Path.IsPathRooted(filePath) ? filePath : Path.Combine(_contentRoot, filePath);
        if (!File.Exists(fullPath)) return null;

        var lines = File.ReadAllLines(fullPath, Encoding.UTF8);
        string currentSection = string.Empty;

        var form = new QryForm
        {
            Title = Path.GetFileNameWithoutExtension(fullPath),
            Group = "默认",
            QueryType = "select"
        };

        var sqlBuilder = new StringBuilder();

        foreach (var rawLine in lines)
        {
            var line = rawLine.Trim();
            if (string.IsNullOrWhiteSpace(line) || line.StartsWith('#') || line.StartsWith("--"))
            {
                if (currentSection == "sql" && !rawLine.TrimStart().StartsWith('#'))
                {
                    sqlBuilder.AppendLine(rawLine);
                }
                continue;
            }

            if (line.StartsWith('[') && line.EndsWith(']'))
            {
                currentSection = line[1..^1].Trim().ToLowerInvariant();
                continue;
            }

            if (currentSection == "meta")
            {
                var eqIdx = line.IndexOf('=');
                if (eqIdx != -1)
                {
                    var key = line[..eqIdx].Trim().ToLowerInvariant();
                    var val = line[(eqIdx + 1)..].Trim();
                    switch (key)
                    {
                        case "title": form.Title = val; break;
                        case "group": form.Group = val; break;
                        case "description": form.Description = val; break;
                        case "web_enabled": form.WebEnabled = string.Equals(val, "true", StringComparison.OrdinalIgnoreCase); break;
                        case "type": form.QueryType = val.ToLowerInvariant(); break;
                    }
                }
            }
            else if (currentSection == "params")
            {
                var eqIdx = line.IndexOf('=');
                if (eqIdx != -1)
                {
                    var name = line[..eqIdx].Trim();
                    var rest = line[(eqIdx + 1)..].Trim();
                    var parts = rest.Split('|').Select(p => p.Trim()).ToList();

                    var label = parts.Count > 0 && !string.IsNullOrEmpty(parts[0]) ? parts[0] : name;
                    var ptypeFull = parts.Count > 1 ? parts[1] : "text";
                    var rawDef = parts.Count > 2 ? parts[2] : string.Empty;
                    var extra = parts.Skip(3).ToList();

                    var ptype = ptypeFull;
                    var staticOptions = new List<string>();

                    if (ptypeFull.StartsWith("select:", StringComparison.OrdinalIgnoreCase))
                    {
                        ptype = "select";
                        staticOptions = ptypeFull[7..].Split(',').Select(s => s.Trim()).Where(s => !string.IsNullOrEmpty(s)).ToList();
                    }
                    else if (ptypeFull.StartsWith("radio:", StringComparison.OrdinalIgnoreCase))
                    {
                        ptype = "radio";
                        staticOptions = ptypeFull[6..].Split(',').Select(s => s.Trim()).Where(s => !string.IsNullOrEmpty(s)).ToList();
                    }

                    string placeholder = string.Empty;
                    bool required = false;
                    string width = string.Empty;
                    bool allowCustom = false;
                    bool dynamicOptions = false;
                    string? optionsSql = null;

                    foreach (var ext in extra)
                    {
                        if (ext.StartsWith("placeholder=")) placeholder = ext[12..].Trim();
                        else if (ext.Equals("required", StringComparison.OrdinalIgnoreCase)) required = true;
                        else if (ext.StartsWith("width=")) width = ext[6..].Trim();
                        else if (ext.StartsWith("allow_custom=")) allowCustom = string.Equals(ext[13..].Trim(), "true", StringComparison.OrdinalIgnoreCase);
                        else if (ext.StartsWith("options_sql="))
                        {
                            dynamicOptions = true;
                            optionsSql = ext[12..].Trim();
                        }
                    }

                    string resolvedDefault = rawDef;
                    if (rawDef.Contains("{today}"))
                    {
                        resolvedDefault = ptype == "datetime"
                            ? DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss")
                            : DateTime.Now.ToString("yyyy-MM-dd");
                    }

                    form.Params.Add(new ParamDef
                    {
                        Name = name,
                        Label = label,
                        Ptype = ptype,
                        Options = staticOptions,
                        OptionItems = staticOptions.Select(o => new OptionItem { Value = o, Label = o }).ToList(),
                        Default = resolvedDefault,
                        RawDefault = rawDef,
                        Placeholder = placeholder,
                        Required = required,
                        Width = width,
                        DynamicOptions = dynamicOptions,
                        Searchable = ptype == "select",
                        AllowCustom = allowCustom,
                        OptionsSql = optionsSql
                    });
                }
            }
            else if (currentSection == "sql")
            {
                sqlBuilder.AppendLine(rawLine);
            }
        }

        form.Sql = sqlBuilder.ToString();
        form.FilePath = Path.GetRelativePath(_contentRoot, fullPath).Replace('\\', '/');
        return form;
    }

    public Dictionary<string, List<QryForm>> LoadAllForms(bool webOnly = true)
    {
        var result = new Dictionary<string, List<QryForm>>();
        var formsDir = Path.Combine(_contentRoot, "forms");
        if (!Directory.Exists(formsDir)) return result;

        foreach (var file in Directory.EnumerateFiles(formsDir, "*.qry", SearchOption.AllDirectories))
        {
            var form = ParseQryFile(file);
            if (form == null) continue;
            if (webOnly && !form.WebEnabled) continue;

            if (!result.ContainsKey(form.Group))
            {
                result[form.Group] = new List<QryForm>();
            }
            result[form.Group].Add(form);
        }

        return result;
    }
}
