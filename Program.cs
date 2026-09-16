using DbQuery.Services;
using Microsoft.Extensions.FileProviders;

var builder = WebApplication.CreateBuilder(args);

// 注册 MVC 与 API 控制器
builder.Services.AddControllersWithViews()
    .AddJsonOptions(options =>
    {
        options.JsonSerializerOptions.PropertyNamingPolicy = null;
    });

// 注册 Session 服务
builder.Services.AddDistributedMemoryCache();
builder.Services.AddSession(options =>
{
    options.IdleTimeout = TimeSpan.FromHours(8);
    options.Cookie.HttpOnly = true;
    options.Cookie.IsEssential = true;
    options.Cookie.SameSite = SameSiteMode.Lax;
});

// 注册核心业务单例服务
builder.Services.AddSingleton<IFormParserService, FormParserService>();
builder.Services.AddSingleton<ISqlSafetyService, SqlSafetyService>();
builder.Services.AddSingleton<IQueryExecutionService, QueryExecutionService>();
builder.Services.AddSingleton<IExcelExportService, ExcelExportService>();
builder.Services.AddSingleton<IEmbedSessionService, EmbedSessionService>();
builder.Services.AddSingleton<IAuthService, AuthService>();
builder.Services.AddSingleton<IFormEditorService, FormEditorService>();
builder.Services.AddSingleton<IConfigManagerService, ConfigManagerService>();

var app = builder.Build();

// 静态文件目录映射
var staticDir = Path.Combine(builder.Environment.ContentRootPath, "static");
if (!Directory.Exists(staticDir))
{
    staticDir = Path.Combine(builder.Environment.ContentRootPath, "..", "static");
}

if (Directory.Exists(staticDir))
{
    app.UseStaticFiles(new StaticFileOptions
    {
        FileProvider = new PhysicalFileProvider(staticDir),
        RequestPath = "/static"
    });
}
else
{
    app.UseStaticFiles();
}

// 安全头与 iframe 跨域嵌入支持
app.Use(async (context, next) =>
{
    if (!context.Request.Path.StartsWithSegments("/static"))
    {
        context.Response.Headers.Append("Cache-Control", "no-store, max-age=0");
        context.Response.Headers.Append("Pragma", "no-cache");
    }
    context.Response.Headers.Append("X-Content-Type-Options", "nosniff");
    context.Response.Headers.Append("Referrer-Policy", "same-origin");
    context.Response.Headers.Append("Content-Security-Policy", "frame-ancestors 'self' *");
    await next();
});

// 宿主 iframe 嵌入 Session 中间件: /embed-session/{token}/...
app.Use(async (context, next) =>
{
    var path = context.Request.Path.Value ?? string.Empty;
    if (path.StartsWith("/embed-session/"))
    {
        var parts = path["/embed-session/".Length..].Split('/', 2);
        var token = parts[0];
        var subPath = "/" + (parts.Length > 1 ? parts[1] : string.Empty);

        var embedService = context.RequestServices.GetRequiredService<IEmbedSessionService>();
        var user = embedService.ValidateEmbedSession(token);
        if (!string.IsNullOrEmpty(user))
        {
            context.Items["EmbedUser"] = user;
            context.Items["EmbedToken"] = token;
            context.Request.Path = subPath;
        }
    }
    await next();
});

app.UseRouting();
app.UseSession();

app.MapControllers();
app.MapDefaultControllerRoute();

var port = Environment.GetEnvironmentVariable("PORT") ?? "3000";
Console.WriteLine($"DbQuery C# (.NET 8) Web Server running on port {port}");
app.Run($"http://0.0.0.0:{port}");
