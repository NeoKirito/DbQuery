using ClosedXML.Excel;
using DbQuery.Models;

namespace DbQuery.Services;

public interface IExcelExportService
{
    byte[] GenerateExcel(ExportRequest request, QryForm? form);
}

public class ExcelExportService : IExcelExportService
{
    public byte[] GenerateExcel(ExportRequest request, QryForm? form)
    {
        using var workbook = new XLWorkbook();
        var formTitle = form?.Title ?? "数据查询结果";
        var formDesc = form?.Description ?? string.Empty;

        // Sheet 1: 数据结果
        var safeSheetName = formTitle.Length > 28 ? formTitle[..28] : formTitle;
        // 清除特殊字符
        safeSheetName = string.Concat(safeSheetName.Split(Path.GetInvalidFileNameChars()));
        if (string.IsNullOrWhiteSpace(safeSheetName)) safeSheetName = "数据";

        var dataSheet = workbook.Worksheets.Add(safeSheetName);

        // 表头
        for (int col = 0; col < request.Columns.Count; col++)
        {
            var cell = dataSheet.Cell(1, col + 1);
            cell.Value = request.Columns[col];
            cell.Style.Font.Bold = true;
            cell.Style.Font.FontColor = XLColor.White;
            cell.Style.Fill.BackgroundColor = XLColor.FromHtml("#1A6EB5");
            cell.Style.Alignment.Horizontal = XLAlignmentHorizontalValues.Center;
            cell.Style.Alignment.Vertical = XLAlignmentVerticalValues.Center;
        }

        // 数据行
        for (int row = 0; row < request.Rows.Count; row++)
        {
            var rData = request.Rows[row];
            for (int col = 0; col < rData.Count; col++)
            {
                var val = rData[col];
                var cell = dataSheet.Cell(row + 2, col + 1);
                if (val != null)
                {
                    if (val is int i) cell.Value = i;
                    else if (val is long l) cell.Value = l;
                    else if (val is double d) cell.Value = d;
                    else if (val is decimal dec) cell.Value = dec;
                    else if (val is DateTime dt) cell.Value = dt.ToString("yyyy-MM-dd HH:mm:ss");
                    else cell.Value = val.ToString();
                }
            }
        }

        dataSheet.Columns().AdjustToContents(12, 40);

        // Sheet 2: 查询信息
        var infoSheet = workbook.Worksheets.Add("查询信息");
        infoSheet.Cell("A1").Value = "查询项目";
        infoSheet.Cell("B1").Value = formTitle;
        infoSheet.Cell("A2").Value = "项目说明";
        infoSheet.Cell("B2").Value = formDesc;
        infoSheet.Cell("A3").Value = "导出时间";
        infoSheet.Cell("B3").Value = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");
        infoSheet.Cell("A4").Value = "导出记录数";
        infoSheet.Cell("B4").Value = request.Rows.Count;
        infoSheet.Cell("A5").Value = "字段数";
        infoSheet.Cell("B5").Value = request.Columns.Count;
        infoSheet.Cell("A6").Value = "查询耗时";
        infoSheet.Cell("B6").Value = $"{request.Elapsed:F2} 秒";

        infoSheet.Cell("A8").Value = "—— 查询条件 ——";
        infoSheet.Cell("A8").Style.Font.Bold = true;

        int infoRow = 9;
        if (request.Params != null)
        {
            foreach (var kv in request.Params)
            {
                infoSheet.Cell(infoRow, 1).Value = kv.Key;
                infoSheet.Cell(infoRow, 2).Value = kv.Value?.ToString() ?? string.Empty;
                infoRow++;
            }
        }

        infoSheet.Column(1).Width = 20;
        infoSheet.Column(2).Width = 50;

        using var ms = new MemoryStream();
        workbook.SaveAs(ms);
        return ms.ToArray();
    }
}
