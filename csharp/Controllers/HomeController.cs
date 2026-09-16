using DbQuery.Services;
using Microsoft.AspNetCore.Mvc;

namespace DbQuery.Controllers;

public class HomeController : Controller
{
    private readonly IFormParserService _formParser;
    private readonly IEmbedSessionService _embedSession;
    private readonly IAuthService _authService;

    public HomeController(
        IFormParserService formParser,
        IEmbedSessionService embedSession,
        IAuthService authService)
    {
        _formParser = formParser;
        _embedSession = embedSession;
        _authService = authService;
    }

    private string? GetCurrentUser()
    {
        // 1. Check Embed Session Token in route or header
        if (HttpContext.Items.TryGetValue("EmbedUser", out var eu) && eu is string embedUser)
        {
            return embedUser;
        }

        // 2. Check Standard Session
        return HttpContext.Session.GetString("AuthUser");
    }

    [HttpGet("/")]
    public IActionResult Index([FromQuery] string? embed, [FromQuery] string? hide_header, [FromQuery] string? sidebar)
    {
        var currentUser = GetCurrentUser();
        if (string.IsNullOrEmpty(currentUser))
        {
            return Redirect("/login?next=/");
        }

        var isEmbed = embed == "1" || hide_header == "1" || HttpContext.Items.ContainsKey("EmbedUser");
        var isSidebarHidden = sidebar == "0" || (isEmbed && sidebar != "1");

        ViewBag.CurrentUser = currentUser;
        ViewBag.EmbedMode = isEmbed;
        ViewBag.HideHeader = isEmbed;
        ViewBag.SidebarHidden = isSidebarHidden;
        ViewBag.FormsData = _formParser.LoadAllForms(true);

        return View();
    }

    [HttpGet("/login")]
    public IActionResult Login([FromQuery] string? next)
    {
        if (!string.IsNullOrEmpty(GetCurrentUser()))
        {
            return Redirect(!string.IsNullOrEmpty(next) && next.StartsWith('/') ? next : "/");
        }

        ViewBag.NextUrl = next ?? string.Empty;
        ViewBag.Error = string.Empty;
        return View();
    }

    [HttpPost("/login")]
    public async Task<IActionResult> ProcessLogin([FromForm] string username, [FromForm] string password, [FromForm] string? next)
    {
        var nextUrl = !string.IsNullOrEmpty(next) && next.StartsWith('/') ? next : "/";

        var (success, displayName, err) = await _authService.AuthenticateAsync(username ?? "", password ?? "");
        if (success)
        {
            HttpContext.Session.SetString("AuthUser", username!.Trim());
            return Redirect(nextUrl);
        }

        ViewBag.NextUrl = nextUrl;
        ViewBag.Error = err ?? "账号或密码错误。演示账号：admin / 123456";
        return View("Login");
    }

    [HttpPost("/logout")]
    public IActionResult Logout()
    {
        HttpContext.Session.Clear();
        return Redirect("/login");
    }

    [HttpGet("/query/{**filePath}")]
    public IActionResult Query(string? filePath, [FromQuery] string? embed, [FromQuery] string? hide_header, [FromQuery] string? sidebar)
    {
        var currentUser = GetCurrentUser();
        if (string.IsNullOrEmpty(currentUser))
        {
            var target = HttpContext.Request.Path + HttpContext.Request.QueryString;
            return Redirect($"/login?next={Uri.EscapeDataString(target)}");
        }

        if (string.IsNullOrWhiteSpace(filePath))
        {
            return NotFound("查询方案路径不能为空。");
        }

        var form = _formParser.ParseQryFile(filePath);
        if (form == null)
        {
            return NotFound("查询方案不存在或已停用。");
        }

        var isEmbed = embed == "1" || hide_header == "1" || HttpContext.Items.ContainsKey("EmbedUser");
        var isSidebarHidden = sidebar == "0" || (isEmbed && sidebar != "1");

        ViewBag.CurrentUser = currentUser;
        ViewBag.EmbedMode = isEmbed;
        ViewBag.HideHeader = isEmbed;
        ViewBag.SidebarHidden = isSidebarHidden;
        ViewBag.Form = form;
        ViewBag.FilePath = form.FilePath;

        return View();
    }
}
