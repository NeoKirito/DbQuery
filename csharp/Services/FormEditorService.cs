using System.Text;
using DbQuery.Models;

namespace DbQuery.Services;

public interface IFormEditorService
{
    bool SaveQryFile(string relativeFilePath, QryForm form);
    bool DeleteQryFile(string relativeFilePath);
    List<string> GetAllQryFiles();
}

public class FormEditorService : IFormEditorService
{
    private readonly string _contentRoot;

    public FormEditorService(IWebHostEnvironment env)
    {
        _contentRoot = env.ContentRootPath;
    }

    public List<string> GetAllQryFiles()
    {
        var formsDir = Path.Combine(_contentRoot, "forms");
        if (!Directory.Exists(formsDir)) return new List<string>();

        return Directory.EnumerateFiles(formsDir, "*.qry", SearchOption.AllDirectories)
            .Select(f => Path.GetRelativePath(_contentRoot, f).Replace('\\', '/'))
            .ToList();
    }

    public bool SaveQryFile(string relativeFilePath, QryForm form)
    {
        var fullPath = Path.IsPathRooted(relativeFilePath)
            ? relativeFilePath
            : Path.Combine(_contentRoot, relativeFilePath);

        var dir = Path.GetDirectoryName(fullPath);
        if (!string.IsNullOrEmpty(dir) && !Directory.Exists(dir))
        {
            Directory.CreateDirectory(dir);
        }

        var sb = new StringBuilder();
        sb.AppendLine("[meta]");
        sb.AppendLine($"title = {form.Title}");
        sb.AppendLine($"group = {form.Group}");
        if (!string.IsNullOrEmpty(form.Description))
        {
            sb.AppendLine($"description = {form.Description}");
        }
        sb.AppendLine($"web_enabled = {(form.WebEnabled ? "true" : "false")}");
        sb.AppendLine($"type = {form.QueryType}");
        sb.AppendLine();

        sb.AppendLine("[params]");
        foreach (var p in form.Params)
        {
            var ptypeStr = p.Ptype;
            if (p.Ptype == "select" && p.Options.Count > 0)
            {
                ptypeStr = $"select:{string.Join(",", p.Options)}";
            }
            else if (p.Ptype == "radio" && p.Options.Count > 0)
            {
                ptypeStr = $"radio:{string.Join(",", p.Options)}";
            }

            var extraParts = new List<string>();
            if (!string.IsNullOrEmpty(p.Placeholder)) extraParts.Add($"placeholder={p.Placeholder}");
            if (p.Required) extraParts.Add("required");
            if (!string.IsNullOrEmpty(p.Width)) extraParts.Add($"width={p.Width}");
            if (p.AllowCustom) extraParts.Add("allow_custom=true");
            if (p.DynamicOptions && !string.IsNullOrEmpty(p.OptionsSql)) extraParts.Add($"options_sql={p.OptionsSql}");

            var rawDef = !string.IsNullOrEmpty(p.RawDefault) ? p.RawDefault : p.Default;
            var line = $"{p.Name} = {p.Label} | {ptypeStr} | {rawDef}";
            if (extraParts.Count > 0)
            {
                line += " | " + string.Join(" | ", extraParts);
            }
            sb.AppendLine(line);
        }
        sb.AppendLine();

        sb.AppendLine("[sql]");
        sb.AppendLine(form.Sql);

        File.WriteAllText(fullPath, sb.ToString(), Encoding.UTF8);
        return true;
    }

    public bool DeleteQryFile(string relativeFilePath)
    {
        var fullPath = Path.IsPathRooted(relativeFilePath)
            ? relativeFilePath
            : Path.Combine(_contentRoot, relativeFilePath);

        if (File.Exists(fullPath))
        {
            File.Delete(fullPath);
            return true;
        }
        return false;
    }
}
