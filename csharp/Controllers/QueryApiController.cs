using DbQuery.Models;
using DbQuery.Services;
using Microsoft.AspNetCore.Mvc;

namespace DbQuery.Controllers;

[ApiController]
public class QueryApiController : ControllerBase
{
    private readonly IFormParserService _formParser;
    private readonly IQueryExecutionService _queryExecution;
    private readonly IExcelExportService _excelExport;
    private readonly IEmbedSessionService _embedSession;
    private readonly IAuthService _authService;

    public QueryApiController(
        IFormParserService formParser,
        IQueryExecutionService queryExecution,
        IExcelExportService excelExport,
        IEmbedSessionService embedSession,
        IAuthService authService)
    {
        _formParser = formParser;
        _queryExecution = queryExecution;
        _excelExport = excelExport;
        _embedSession = embedSession;
        _authService = authService;
    }

    [HttpGet("api/forms")]
    public IActionResult GetForms()
    {
        var isAuth = HttpContext.Session.GetString("AuthUser") != null || HttpContext.Items.ContainsKey("EmbedUser");
        if (!isAuth)
        {
            return Unauthorized(new { error = "未登录或登录已失效，请重新登录。" });
        }

        var forms = _formParser.LoadAllForms(true);
        return Ok(forms);
    }

    [HttpPost("api/options")]
    public async Task<IActionResult> GetOptions([FromBody] OptionsRequest req)
    {
        var isAuth = HttpContext.Session.GetString("AuthUser") != null || HttpContext.Items.ContainsKey("EmbedUser");
        if (!isAuth)
        {
            return Unauthorized(new { error = "未登录或登录已失效，请重新登录。" });
        }

        if (string.IsNullOrWhiteSpace(req.FilePath) || string.IsNullOrWhiteSpace(req.ParamName))
        {
            return BadRequest(new { error = "查询条件信息不完整，请重新操作。" });
        }

        var form = _formParser.ParseQryFile(req.FilePath);
        if (form == null) return NotFound(new { error = "查询方案不存在或已停用。" });

        var param = form.Params.FirstOrDefault(p => p.Name == req.ParamName);
        if (param == null) return NotFound(new { error = "查询条件不存在或不支持候选项加载。" });

        var options = await _queryExecution.GetOptionsAsync(param);
        return Ok(new OptionsResponse
        {
            Options = options,
            Warning = string.Empty
        });
    }

    [HttpGet("api/test-connection")]
    public async Task<IActionResult> TestConnection()
    {
        var ok = await _queryExecution.TestConnectionAsync();
        return Ok(new ConnectionTestResponse
        {
            Success = ok,
            Message = ok ? "数据服务连接正常" : "数据服务连接异常"
        });
    }

    [HttpPost("api/query")]
    public async Task<IActionResult> ExecuteQuery([FromBody] QueryRequest req)
    {
        var isAuth = HttpContext.Session.GetString("AuthUser") != null || HttpContext.Items.ContainsKey("EmbedUser");
        if (!isAuth)
        {
            return Unauthorized(new { error = "未登录或登录已失效，请重新登录。" });
        }

        if (string.IsNullOrWhiteSpace(req.FilePath))
        {
            return BadRequest(new { error = "请求信息不完整，请重新操作。" });
        }

        var form = _formParser.ParseQryFile(req.FilePath);
        if (form == null)
        {
            return NotFound(new { error = "查询方案不存在或已停用。" });
        }

        var result = await _queryExecution.ExecuteAsync(form, req.Params ?? new Dictionary<string, string>());
        if (!string.IsNullOrEmpty(result.Error))
        {
            return BadRequest(new { error = result.Error });
        }
        return Ok(result);
    }

    [HttpPost("api/export")]
    public IActionResult Export([FromBody] ExportRequest req)
    {
        var isAuth = HttpContext.Session.GetString("AuthUser") != null || HttpContext.Items.ContainsKey("EmbedUser");
        if (!isAuth)
        {
            return Unauthorized(new { error = "未登录或登录已失效，请重新登录。" });
        }

        if (req.Columns == null || req.Rows == null)
        {
            return BadRequest(new { error = "导出信息不完整，请重新操作。" });
        }

        var form = string.IsNullOrWhiteSpace(req.FilePath) ? null : _formParser.ParseQryFile(req.FilePath);
        var title = form?.Title ?? "数据查询结果";

        var bytes = _excelExport.GenerateExcel(req, form);
        var timestamp = DateTime.Now.ToString("yyyyMMddHHmmss");
        var filename = $"{title}_{timestamp}.xlsx";

        return File(bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename);
    }

    [HttpGet("api/integration/session")]
    public IActionResult GetIntegrationSession()
    {
        var isAuth = HttpContext.Session.GetString("AuthUser") != null;
        return Ok(new { authenticated = isAuth });
    }

    [HttpPost("api/integration/frontend-login")]
    public async Task<IActionResult> FrontendLogin([FromBody] Dictionary<string, string> body)
    {
        body.TryGetValue("username", out var username);
        body.TryGetValue("password", out var password);

        var (success, displayName, err) = await _authService.AuthenticateAsync(username ?? "", password ?? "");
        if (!success)
        {
            return Unauthorized(new { error = err ?? "账号或密码错误。", error_type = "AUTH_FAILED" });
        }

        var token = _embedSession.CreateEmbedSession(username!);
        HttpContext.Session.SetString("AuthUser", username!);

        var embedPath = $"/embed-session/{token}/?embed=1&hide_header=1&sidebar=0";
        return Ok(new
        {
            success = true,
            authenticated = true,
            embed_path = embedPath,
            embed_session = token,
            user = new { username = username!, display_name = displayName ?? username! }
        });
    }

    [HttpPost("api/integration/logout")]
    public IActionResult FrontendLogout([FromBody] Dictionary<string, string>? body)
    {
        if (body != null && body.TryGetValue("embed_session", out var token) && !string.IsNullOrEmpty(token))
        {
            _embedSession.InvalidateEmbedSession(token);
        }
        HttpContext.Session.Clear();
        return Ok(new { success = true, authenticated = false });
    }

    [HttpPost("api/integration/sso-ticket")]
    public IActionResult CreateSsoTicket([FromBody] Dictionary<string, string>? body)
    {
        var username = body != null && body.TryGetValue("username", out var u) ? u : "admin";
        var ticket = _embedSession.CreateSsoTicket(username ?? "admin");
        return Ok(new
        {
            ticket,
            expires_in = 60,
            consume_path = "/sso/consume"
        });
    }

    [HttpPost("sso/consume")]
    public IActionResult ConsumeSsoTicket([FromForm] string ticket)
    {
        var ticketInfo = _embedSession.ConsumeSsoTicket(ticket);
        if (ticketInfo == null)
        {
            return Unauthorized("宿主登录票据已失效，请返回宿主程序重新进入。");
        }

        HttpContext.Session.SetString("AuthUser", ticketInfo.Value.username);
        return Redirect(ticketInfo.Value.nextUrl);
    }
}
