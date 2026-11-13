using System.Text;
using System.Text.Json;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

const double WorkingLeftMargin = 0.050;
const double WorkingRightMargin = 0.020;
const double WorkingLowerReserve = 0.080;
const double WorkingUpperMargin = 0.020;
const double ProjectedViewGap = 0.015;
const double ManualAnnotationReserve = 0.035;
// Coordinates are in metres in the active drawing sheet.
const double TechnicalRequirementsLeftMargin = 0.025;
const double TechnicalRequirementsBottomMargin = 0.010;
const double TechnicalRequirementsLowerReserve = 0.135;
const double TitleBlockLeft = 0.230;
const double TitleBlockTop = 0.060;
const double SpecificationHeaderHeight = 0.012;
const double SpecificationRowHeight = 0.008;
const string AssemblyTechnicalRequirements =
    "1. *Размеры для справок.\n" +
    "2. Сварные соединения по ГОСТ 14771-76.\n" +
    "3. Острые кромки притупить.\n" +
    "4. Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.\n" +
    "5. Общие допуски формы и расположения — ГОСТ 30893.2—К.\n" +
    "6. Остальные ТТ по СТБ 1022-96.\n" +
    "7. Все сварные швы зачистить Rz40.";
const string PartTechnicalRequirements =
    "1. *Размеры для справок.\n" +
    "2. Острые кромки притупить.\n" +
    "3. Общие допуски по ГОСТ 30893.1: Н14, h14, ±IТ14/2.\n" +
    "4. Общие допуски формы и расположения — ГОСТ 30893.2—К.\n" +
    "5. Остальные ТТ по СТБ 1014-95.";

// The host decodes redirected helper output as UTF-8, including Russian paths.
Console.OutputEncoding = new UTF8Encoding(false);

if (args.Length is not 3 and not 4)
{
    Console.Error.WriteLine("Usage: SolidWorksDrawingHelper <template.drwdot> <model> <output.slddrw> [pallet-metadata.json]");
    return 2;
}

try
{
    var appType = Type.GetTypeFromProgID("SldWorks.Application")
        ?? throw new InvalidOperationException("SolidWorks is not registered in Windows.");
    var sw = (SldWorks)(Activator.CreateInstance(appType)
        ?? throw new InvalidOperationException("Unable to start SolidWorks."));
    sw.Visible = true;

    var modelPath = Path.GetFullPath(args[1]);
    var documentType = Path.GetExtension(modelPath).Equals(".sldasm", StringComparison.OrdinalIgnoreCase)
        ? (int)swDocumentTypes_e.swDocASSEMBLY : (int)swDocumentTypes_e.swDocPART;
    var hasAssemblyRequirements = documentType == (int)swDocumentTypes_e.swDocASSEMBLY;
    var hasPartRequirements = documentType == (int)swDocumentTypes_e.swDocPART;
    var hasTechnicalRequirements = hasAssemblyRequirements || hasPartRequirements;
    var errors = 0;
    var warnings = 0;
    var model = sw.OpenDoc6(modelPath, documentType, (int)swOpenDocOptions_e.swOpenDocOptions_Silent, "", ref errors, ref warnings);
    if (model is null)
        throw new InvalidOperationException($"SolidWorks could not open model (errors={errors}, warnings={warnings}).");

    var pallet = args.Length == 4
        ? JsonSerializer.Deserialize<PalletDrawingData>(File.ReadAllText(args[3]), new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
        : null;
    var drawingTemplate = Path.GetFullPath(args[0]);
    // NewDocument's paper-size argument can replace the sheet setup stored in
    // the template. Read all three values from the selected .drwdot instead.
    if (sw.GetTemplateSizes(drawingTemplate) is not Array templateSize || templateSize.Length < 3)
        throw new InvalidOperationException($"Не удалось прочитать размер листа шаблона чертежа: {drawingTemplate}");
    var paperSize = Convert.ToInt32(templateSize.GetValue(0));
    var paperWidth = Convert.ToDouble(templateSize.GetValue(1));
    var paperHeight = Convert.ToDouble(templateSize.GetValue(2));
    if (sw.NewDocument(drawingTemplate, paperSize, paperWidth, paperHeight) is null)
        throw new InvalidOperationException("SolidWorks did not create a drawing document.");
    var drawing = (DrawingDoc)(sw.IActiveDoc2 ?? throw new InvalidOperationException("Drawing document is not active."));
    var sheet = (Sheet)drawing.GetCurrentSheet();
    EnsureTemplateSheetFormat(drawing, sheet, drawingTemplate);
    var drawingModel = (ModelDoc2)drawing;
    PalletViewLayout? palletViewLayout = null;
    if (pallet?.Pallet is not null)
    {
        ApplyGostSheetScale(sw, drawing, pallet, hasTechnicalRequirements);
        palletViewLayout = CreatePalletOrthographicViews(drawing, model, modelPath, pallet, hasTechnicalRequirements);
        ApplyGostSheetScale(sw, drawing, pallet, hasTechnicalRequirements);
    }
    else if (hasPartRequirements || hasAssemblyRequirements)
    {
        if (hasAssemblyRequirements)
            CreatePackagingViews(drawing, drawingModel, model, modelPath, drawingTemplate);
        else
            CreatePartOrthographicViews(drawing, drawingModel, model, modelPath, hasTechnicalRequirements);
    }
    else
    {
        if (!drawing.Create3rdAngleViews2(modelPath))
            throw new InvalidOperationException("SolidWorks did not create standard views.");
        ApplyGostSheetScale(sw, drawing, pallet, hasTechnicalRequirements);
    }
    drawingModel.ForceRebuild3(false);
    RemoveSurfaceFinishSymbols(drawing, drawingModel);
    // Assembly views have an explicitly controlled layout, so the three
    // reference dimensions can be placed precisely on their outside edges.
    if (pallet?.Pallet is not null && palletViewLayout is not null)
        AddOverallDimensions(drawing, pallet.Pallet, palletViewLayout);
    if (hasAssemblyRequirements)
    {
        AddAssemblySpecification(drawing, drawingModel, pallet?.Specification);
        AddAssemblyTechnicalRequirements(drawing, drawingModel);
    }
    else if (hasPartRequirements)
    {
        AddPartTechnicalRequirements(drawing, drawingModel);
    }
    if (pallet?.Pallet is not null)
        AddPalletPlanSheet(drawing, drawingModel, model, modelPath, drawingTemplate);
    drawingModel.ForceRebuild3(false);
    drawingModel.GraphicsRedraw2();
    drawingModel.SaveAs3(Path.GetFullPath(args[2]), (int)swSaveAsVersion_e.swSaveAsCurrentVersion, (int)swSaveAsOptions_e.swSaveAsOptions_Silent);
    if (!File.Exists(args[2]))
        throw new InvalidOperationException("SolidWorks did not save the drawing.");
    Console.WriteLine(args[2]);
    return 0;
}
catch (Exception error)
{
    Console.Error.WriteLine(error.Message);
    return 1;
}

static bool HasSheetFormatGeometry(DrawingDoc drawing)
{
    var model = (ModelDoc2)drawing;
    // The active sketch is available in Edit Sheet Format mode. Looking up
    // the template sketch while editing the sheet can return no geometry even
    // when the selected template contains a frame.
    return SheetFormatPolicy.Inspect(
        () => drawing.EditTemplate(),
        () =>
        {
            if (model.GetActiveSketch2() is not Sketch sketch)
                return false;
            return (sketch.GetSketchSegments() is Array segments && segments.Length > 0)
                || (sketch.GetSketchBlockInstances() is Array blocks && blocks.Length > 0);
        },
        () => drawing.EditSheet());
}

static void EnsureTemplateSheetFormat(DrawingDoc drawing, Sheet sheet, string drawingTemplate)
{
    sheet.SheetFormatVisible = true;
    string ResolveLinkedPath(string linked) => Path.IsPathRooted(linked)
        ? linked : Path.Combine(Path.GetDirectoryName(drawingTemplate)!, linked);
    SheetFormatPolicy.Ensure(
        () => HasSheetFormatGeometry(drawing),
        () => sheet.GetTemplateName(),
        linked => File.Exists(ResolveLinkedPath(linked)),
        () =>
        {
            var linked = sheet.GetTemplateName();
            if (!Path.IsPathRooted(linked))
                sheet.SetTemplateName(ResolveLinkedPath(linked));
            return sheet.ReloadTemplate(false);
        },
        (int)swReloadTemplateResult_e.swReloadTemplate_Success,
        drawingTemplate);
    sheet.SheetFormatVisible = true;
}

static void ApplyGostSheetScale(SldWorks sw, DrawingDoc drawing, PalletDrawingData? pallet, bool reserveTechnicalRequirements)
{
    var sheet = (Sheet)drawing.GetCurrentSheet();
    var allowed = AllowedDrawingScales();
    var properties = (Array)sheet.GetProperties2();
    var sheetWidth = Convert.ToDouble(properties.GetValue(5));
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    var views = GetModelViews(drawing).ToArray();
    var lowerReserve = reserveTechnicalRequirements ? TechnicalRequirementsLowerReserve : WorkingLowerReserve;
    var chosen = allowed.FirstOrDefault(scale => pallet?.Pallet is not null
        ? PalletLayoutFits(pallet.Pallet, scale.Numerator / scale.Denominator, sheetWidth, sheetHeight, lowerReserve)
        : ViewsFitOnSheet(views, scale.Numerator / scale.Denominator, sheetWidth, sheetHeight, lowerReserve));
    if (chosen == default)
        chosen = allowed[^1];
    sheet.SetScale(chosen.Numerator, chosen.Denominator, true, false);
    foreach (var view in views)
        view.UseSheetScale = 1;
    // Pallet views receive their exact projected layout in
    // CreatePalletOrthographicViews.  Re-centering them here would override
    // that layout and can break their native alignment relations.
    if (pallet?.Pallet is null)
        CenterProjectedViewGroup(views, sheetWidth, sheetHeight, lowerReserve);
}

static (double Numerator, double Denominator)[] AllowedDrawingScales() =>
[
    (1d, 1d), (1d, 2d), (1d, 2.5d), (1d, 4d),
    (1d, 5d), (1d, 10d), (1d, 15d), (1d, 20d), (1d, 25d), (1d, 40d),
    (1d, 50d), (1d, 75d), (1d, 100d), (1d, 200d), (1d, 400d),
    (1d, 500d), (1d, 800d), (1d, 1000d),
];

static bool PalletLayoutFits(PalletEnvelope? pallet, double scale, double sheetWidth, double sheetHeight, double lowerReserve)
{
    if (pallet is null)
        return false;
    var length = pallet.Length / 1000d * scale;
    var width = pallet.Width / 1000d * scale;
    var height = pallet.Height / 1000d * scale;
    return length + width + ProjectedViewGap <= sheetWidth - WorkingLeftMargin - WorkingRightMargin
        && height + ManualAnnotationReserve <= sheetHeight - lowerReserve - WorkingUpperMargin
        && length <= sheetWidth - WorkingLeftMargin - WorkingRightMargin
        && width <= sheetHeight - WorkingLowerReserve - WorkingUpperMargin;
}

static void CenterProjectedViewGroup(
    IReadOnlyCollection<SolidWorks.Interop.sldworks.View> views, double sheetWidth, double sheetHeight, double lowerMargin)
{
    var mainView = views.FirstOrDefault(view => view.GetBaseView() is null);
    if (mainView is null)
        return;

    const double upperMargin = 0.020;
    // Create3rdAngleViews2 already produces a valid editable projection
    // group.  Move only the main view; moving projected children directly can
    // persist an invalid relationship in some SolidWorks installations.
    var boxes = views.Select(view => ScaledOutline(view, view.ScaleDecimal)).ToArray();
    var groupCenterX = (boxes.Min(box => box.Left) + boxes.Max(box => box.Right)) / 2d;
    var groupCenterY = (boxes.Min(box => box.Bottom) + boxes.Max(box => box.Top)) / 2d;
    var targetX = sheetWidth / 2d;
    var targetY = lowerMargin + (sheetHeight - lowerMargin - upperMargin) / 2d;
    var mainPosition = (Array)mainView.Position;
    mainView.Position = new[]
    {
        Convert.ToDouble(mainPosition.GetValue(0)) + targetX - groupCenterX,
        Convert.ToDouble(mainPosition.GetValue(1)) + targetY - groupCenterY,
    };
}

static void CreatePartOrthographicViews(
    DrawingDoc drawing, ModelDoc2 drawingModel, ModelDoc2 model, string modelPath, bool reserveTechnicalRequirements)
{
    var sheet = (Sheet)drawing.GetCurrentSheet();
    var properties = (Array)sheet.GetProperties2();
    var sheetWidth = Convert.ToDouble(properties.GetValue(5));
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    var lowerReserve = reserveTechnicalRequirements ? TechnicalRequirementsLowerReserve : WorkingLowerReserve;
    sheet.SetScale(1d, 1d, true, false);

    var frontName = ResolveStandardViewName(model, "front", "сперед");
    var topName = ResolveStandardViewName(model, "top", "сверх");
    var rightName = ResolveStandardViewName(model, "right", "справ");
    var front = drawing.CreateDrawViewFromModelView3(modelPath, frontName, 0d, 0d, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the front part view.");
    var top = drawing.CreateDrawViewFromModelView3(modelPath, topName, 0d, 0d, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the top part view.");
    var right = drawing.CreateDrawViewFromModelView3(modelPath, rightName, 0d, 0d, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the right part view.");
    front.UseSheetScale = 1;
    top.UseSheetScale = 1;
    right.UseSheetScale = 1;
    drawingModel.ForceRebuild3(false);

    var frontSize = GetUnscaledViewSize(front);
    var topSize = GetUnscaledViewSize(top);
    var rightSize = GetUnscaledViewSize(right);
    var availableWidth = sheetWidth - WorkingLeftMargin - WorkingRightMargin;
    var availableHeight = sheetHeight - lowerReserve - WorkingUpperMargin;
    var scale = AllowedDrawingScales().FirstOrDefault(candidate =>
    {
        var factor = candidate.Numerator / candidate.Denominator;
        var columnWidth = Math.Max(frontSize.Width, topSize.Width) * factor;
        var rowHeight = Math.Max(frontSize.Height, rightSize.Height) * factor;
        var groupWidth = columnWidth + ProjectedViewGap + rightSize.Width * factor;
        var groupHeight = rowHeight + ProjectedViewGap + topSize.Height * factor;
        return groupWidth <= availableWidth && groupHeight <= availableHeight;
    });
    if (scale == default)
        throw new InvalidOperationException("No standard drawing scale fits the part views and technical requirements.");

    sheet.SetScale(scale.Numerator, scale.Denominator, true, false);
    front.UseSheetScale = 1;
    top.UseSheetScale = 1;
    right.UseSheetScale = 1;
    drawingModel.ForceRebuild3(false);

    var factorAtScale = scale.Numerator / scale.Denominator;
    var frontWidth = frontSize.Width * factorAtScale;
    var frontHeight = frontSize.Height * factorAtScale;
    var topWidth = topSize.Width * factorAtScale;
    var topHeight = topSize.Height * factorAtScale;
    var rightWidth = rightSize.Width * factorAtScale;
    var rightHeight = rightSize.Height * factorAtScale;
    var columnWidthAtScale = Math.Max(frontWidth, topWidth);
    var rowHeightAtScale = Math.Max(frontHeight, rightHeight);
    var groupWidthAtScale = columnWidthAtScale + ProjectedViewGap + rightWidth;
    var groupHeightAtScale = rowHeightAtScale + ProjectedViewGap + topHeight;
    var groupLeft = WorkingLeftMargin + (availableWidth - groupWidthAtScale) / 2d;
    var groupBottom = lowerReserve + (availableHeight - groupHeightAtScale) / 2d;
    var frontX = groupLeft + columnWidthAtScale / 2d;
    var frontY = groupBottom + rowHeightAtScale / 2d;
    var topY = groupBottom + rowHeightAtScale + ProjectedViewGap + topHeight / 2d;
    var rightX = groupLeft + columnWidthAtScale + ProjectedViewGap + rightWidth / 2d;

    front.Position = new[] { frontX, frontY };
    top.Position = new[] { frontX, topY };
    right.Position = new[] { rightX, frontY };
    if (!top.AlignWithView((int)swAlignViewTypes_e.swAlignViewVerticalCenter, front)
        || !right.AlignWithView((int)swAlignViewTypes_e.swAlignViewHorizontalCenter, front))
        throw new InvalidOperationException("SolidWorks did not preserve the part-view projection alignment.");
    drawingModel.ForceRebuild3(false);
}

static Sheet AddPlanSheet(DrawingDoc drawing, Sheet firstSheet, string drawingTemplate)
{
    var properties = (Array)firstSheet.GetProperties2();
    var format = firstSheet.GetTemplateName();
    if (!Path.IsPathRooted(format))
        format = Path.Combine(Path.GetDirectoryName(drawingTemplate)!, format);
    if (!File.Exists(format))
        throw new InvalidOperationException($"Не найден формат листа для второго листа: {format}");
    if (!drawing.NewSheet4("Вид сверху", Convert.ToInt32(properties.GetValue(0)),
        (int)swDwgTemplates_e.swDwgTemplateCustom,
        Convert.ToDouble(properties.GetValue(2)), Convert.ToDouble(properties.GetValue(3)),
        Convert.ToDouble(properties.GetValue(4)) != 0, format,
        Convert.ToDouble(properties.GetValue(5)), Convert.ToDouble(properties.GetValue(6)),
        "Default", 0, 0, 0, 0, 0, 0))
        throw new InvalidOperationException("SolidWorks не создал второй лист чертежа.");
    return (Sheet)drawing.GetCurrentSheet();
}

static void FitPlanSheet(DrawingDoc drawing, ModelDoc2 drawingModel, Sheet sheet,
    SolidWorks.Interop.sldworks.View top, string drawingTemplate)
{
    // Select only an explicitly named subsequent-sheet format; an A3 frame
    // cannot simply be placed on A4 without clipping its border and stamp.
    var linkedFormat = sheet.GetTemplateName();
    var directories = new[] { Path.GetDirectoryName(drawingTemplate), Path.GetDirectoryName(linkedFormat) }
        .Where(path => !string.IsNullOrWhiteSpace(path) && Directory.Exists(path))
        .Distinct(StringComparer.OrdinalIgnoreCase);
    var formats = directories.SelectMany(path => Directory.EnumerateFiles(path!, "*.slddrt"))
        .Where(path =>
        {
            var name = Path.GetFileNameWithoutExtension(path).Replace(" ", "").ToLowerInvariant();
            return (name.Contains("а4") || name.Contains("a4"))
                && (name.Contains("лист2") || name.Contains("sheet2"));
        }).ToArray();
    var outline = (Array)top.GetOutline();
    var width = Convert.ToDouble(outline.GetValue(2)) - Convert.ToDouble(outline.GetValue(0));
    var height = Convert.ToDouble(outline.GetValue(3)) - Convert.ToDouble(outline.GetValue(1));
    const double left = 0.025, right = 0.010, bottom = 0.070, upper = 0.015;
    var choices = new[] { (Width: 0.210, Height: 0.297, Landscape: false), (Width: 0.297, Height: 0.210, Landscape: true) };
    foreach (var choice in choices)
    {
        if (width > choice.Width - left - right || height > choice.Height - bottom - upper)
            continue;
        var format = formats.FirstOrDefault(path =>
        {
            var name = Path.GetFileNameWithoutExtension(path).ToLowerInvariant();
            var landscape = name.Contains("горизонт") || name.Contains("landscape");
            return choice.Landscape == landscape;
        });
        if (format is null)
            continue;
        var props = (Array)sheet.GetProperties2();
        if (!drawing.SetupSheet6(sheet.GetName(), (int)swDwgPaperSizes_e.swDwgPapersUserDefined,
            (int)swDwgTemplates_e.swDwgTemplateCustom, Convert.ToDouble(props.GetValue(2)),
            Convert.ToDouble(props.GetValue(3)), Convert.ToDouble(props.GetValue(4)) != 0,
            format, choice.Width, choice.Height, "Default", false, 0, 0, 0, 0, 0, 0))
            throw new InvalidOperationException("SolidWorks не настроил формат второго листа.");
        top.Position = new[] { left + (choice.Width - left - right) / 2d, bottom + (choice.Height - bottom - upper) / 2d };
        drawingModel.ForceRebuild3(false);
        return;
    }
}

static void AddPalletPlanSheet(DrawingDoc drawing, ModelDoc2 drawingModel, ModelDoc2 model, string modelPath, string drawingTemplate)
{
    var first = (Sheet)drawing.GetCurrentSheet();
    var firstName = first.GetName();
    var firstProperties = (Array)first.GetProperties2();
    var numerator = Convert.ToDouble(firstProperties.GetValue(2));
    var denominator = Convert.ToDouble(firstProperties.GetValue(3));
    var second = AddPlanSheet(drawing, first, drawingTemplate);
    var properties = (Array)second.GetProperties2();
    var topName = ResolveStandardViewName(model, "top", "сверх");
    var top = drawing.CreateDrawViewFromModelView3(modelPath, topName,
        Convert.ToDouble(properties.GetValue(5)) / 2d,
        WorkingLowerReserve + (Convert.ToDouble(properties.GetValue(6)) - WorkingLowerReserve - WorkingUpperMargin) / 2d, 0d)
        ?? throw new InvalidOperationException("SolidWorks не создал вид поддона сверху.");
    // SolidWorks may automatically change the new sheet's scale when its
    // first view is inserted. Restore the scale selected for the first sheet.
    second.SetScale(numerator, denominator, true, false);
    top.UseSheetScale = 1;
    drawingModel.ForceRebuild3(false);
    FitPlanSheet(drawing, drawingModel, second, top, drawingTemplate);
    if (!drawing.ActivateSheet(firstName))
        throw new InvalidOperationException("SolidWorks не активировал первый лист чертежа.");
}

static void CreatePackagingViews(DrawingDoc drawing, ModelDoc2 drawingModel, ModelDoc2 model, string modelPath, string drawingTemplate)
{
    var first = (Sheet)drawing.GetCurrentSheet();
    var firstName = first.GetName();
    var properties = (Array)first.GetProperties2();
    var sheetWidth = Convert.ToDouble(properties.GetValue(5));
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    first.SetScale(1, 1, true, false);
    var front = drawing.CreateDrawViewFromModelView3(modelPath, ResolveStandardViewName(model, "front", "сперед"), 0, 0, 0)
        ?? throw new InvalidOperationException("SolidWorks не создал главный вид упаковочной сборки.");
    var right = drawing.CreateDrawViewFromModelView3(modelPath, ResolveStandardViewName(model, "right", "справ"), 0, 0, 0)
        ?? throw new InvalidOperationException("SolidWorks не создал боковой вид упаковочной сборки.");
    front.UseSheetScale = 1;
    right.UseSheetScale = 1;
    drawingModel.ForceRebuild3(false);
    var frontSize = GetUnscaledViewSize(front);
    var rightSize = GetUnscaledViewSize(right);
    var second = AddPlanSheet(drawing, first, drawingTemplate);
    second.SetScale(1, 1, true, false);
    var top = drawing.CreateDrawViewFromModelView3(modelPath, ResolveStandardViewName(model, "top", "сверх"), 0, 0, 0)
        ?? throw new InvalidOperationException("SolidWorks не создал вид упаковочной сборки сверху.");
    top.UseSheetScale = 1;
    drawingModel.ForceRebuild3(false);
    var topSize = GetUnscaledViewSize(top);
    var availableWidth = sheetWidth - WorkingLeftMargin - WorkingRightMargin;
    var elevationHeight = sheetHeight - TechnicalRequirementsLowerReserve - WorkingUpperMargin;
    var planHeight = sheetHeight - WorkingLowerReserve - WorkingUpperMargin;
    var scale = AllowedDrawingScales().FirstOrDefault(candidate =>
    {
        var factor = candidate.Numerator / candidate.Denominator;
        return (frontSize.Width + rightSize.Width) * factor + ProjectedViewGap <= availableWidth
            && Math.Max(frontSize.Height, rightSize.Height) * factor <= elevationHeight
            && topSize.Width * factor <= availableWidth && topSize.Height * factor <= planHeight;
    });
    if (scale == default)
        throw new InvalidOperationException("Не удалось подобрать масштаб для упаковочного чертежа.");
    second.SetScale(scale.Numerator, scale.Denominator, true, false);
    top.UseSheetScale = 1;
    top.Position = new[] { WorkingLeftMargin + availableWidth / 2d, WorkingLowerReserve + planHeight / 2d };
    drawingModel.ForceRebuild3(false);
    FitPlanSheet(drawing, drawingModel, second, top, drawingTemplate);
    if (!drawing.ActivateSheet(firstName))
        throw new InvalidOperationException("SolidWorks не активировал первый лист чертежа.");
    first.SetScale(scale.Numerator, scale.Denominator, true, false);
    front.UseSheetScale = 1;
    right.UseSheetScale = 1;
    var ratio = scale.Numerator / scale.Denominator;
    var groupWidth = (frontSize.Width + rightSize.Width) * ratio + ProjectedViewGap;
    var left = WorkingLeftMargin + (availableWidth - groupWidth) / 2d;
    var centerY = TechnicalRequirementsLowerReserve + elevationHeight / 2d;
    front.Position = new[] { left + frontSize.Width * ratio / 2d, centerY };
    right.Position = new[] { left + frontSize.Width * ratio + ProjectedViewGap + rightSize.Width * ratio / 2d, centerY };
    if (!right.AlignWithView((int)swAlignViewTypes_e.swAlignViewHorizontalCenter, front))
        throw new InvalidOperationException("SolidWorks не выровнял виды упаковочной сборки.");
    drawingModel.ForceRebuild3(false);
}

static (double Width, double Height) GetUnscaledViewSize(SolidWorks.Interop.sldworks.View view)
{
    var outline = (Array)view.GetOutline();
    var viewScale = view.ScaleDecimal;
    if (viewScale <= 0d)
        throw new InvalidOperationException("SolidWorks returned an invalid scale for a part view.");
    var width = Convert.ToDouble(outline.GetValue(2)) - Convert.ToDouble(outline.GetValue(0));
    var height = Convert.ToDouble(outline.GetValue(3)) - Convert.ToDouble(outline.GetValue(1));
    return (width / viewScale, height / viewScale);
}

static PalletViewLayout CreatePalletOrthographicViews(
    DrawingDoc drawing, ModelDoc2 model, string modelPath, PalletDrawingData pallet, bool reserveTechnicalRequirements)
{
    var sheet = (Sheet)drawing.GetCurrentSheet();
    var properties = (Array)sheet.GetProperties2();
    var sheetWidth = Convert.ToDouble(properties.GetValue(5));
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    // ISheet::GetProperties2 returns the scale numerator and denominator at
    // indexes 2 and 3 respectively (there is no Sheet.ScaleDecimal property).
    var scale = Convert.ToDouble(properties.GetValue(2)) / Convert.ToDouble(properties.GetValue(3));
    var sideWidth = pallet.Pallet!.Length / 1000d * scale;
    var sideHeight = pallet.Pallet.Height / 1000d * scale;
    var topHeight = pallet.Pallet.Width / 1000d * scale;
    var endWidth = pallet.Pallet.Width / 1000d * scale;
    var groupWidth = sideWidth + ProjectedViewGap + endWidth;
    var groupHeight = sideHeight + ManualAnnotationReserve;
    var workingWidth = sheetWidth - WorkingLeftMargin - WorkingRightMargin;
    var lowerReserve = reserveTechnicalRequirements ? TechnicalRequirementsLowerReserve : WorkingLowerReserve;
    var workingHeight = sheetHeight - lowerReserve - WorkingUpperMargin;
    if (groupWidth > workingWidth || groupHeight > workingHeight)
        throw new InvalidOperationException("The selected GOST scale does not leave space for the projected views.");

    // Centre the entire orthographic group in the usable sheet area.  The
    // title block below and the left frame are deliberately excluded, so the
    // views are neither pressed against the border nor drawn over the stamp.
    var groupLeft = WorkingLeftMargin + (workingWidth - groupWidth) / 2d;
    var groupBottom = lowerReserve + (workingHeight - groupHeight) / 2d;
    var sideX = groupLeft + sideWidth / 2d;
    var sideY = groupBottom + ManualAnnotationReserve + sideHeight / 2d;
    var topX = sideX;
    var topY = groupBottom + topHeight / 2d;
    var endX = groupLeft + sideWidth + ProjectedViewGap + endWidth / 2d;
    var endY = sideY;

    // A standard view is localized in the model (for example, *Спереди in a
    // Russian SolidWorks installation).  Resolve it from the actual model
    // rather than assuming the English API display name.
    var sideName = ResolveStandardViewName(model, "front", "сперед");
    var topName = ResolveStandardViewName(model, "top", "сверх");
    var endName = ResolveStandardViewName(model, "right", "справ");
    // Use fixed standard model views instead of Create3rdAngleViews2.  Its
    // primary view is document-dependent, which produced a plan as the main
    // view for some pallet assemblies.
    var side = drawing.CreateDrawViewFromModelView3(modelPath, sideName, sideX, sideY, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the side view.");
    var end = drawing.CreateDrawViewFromModelView3(modelPath, endName, endX, endY, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the end view.");
    side.UseSheetScale = 1;
    end.UseSheetScale = 1;
    // Keep the end view aligned with the elevation; the plan is on sheet two.
    if (!end.AlignWithView((int)swAlignViewTypes_e.swAlignViewHorizontalCenter, side))
        throw new InvalidOperationException("SolidWorks did not preserve the projected-view alignment.");
    return new PalletViewLayout(
        sideX - sideWidth / 2d, sideY - sideHeight / 2d, sideWidth, sideHeight,
        topX - sideWidth / 2d, topY - topHeight / 2d, topHeight,
        endX - endWidth / 2d, endY - sideHeight / 2d, endWidth);
}

static string ResolveStandardViewName(ModelDoc2 model, params string[] fragments)
{
    if (model.GetModelViewNames() is not Array names)
        throw new InvalidOperationException("SolidWorks did not return the model view names.");
    var viewNames = names.Cast<object>().OfType<string>().ToArray();
    var result = viewNames.FirstOrDefault(name => fragments.Any(fragment =>
        name.Contains(fragment, StringComparison.OrdinalIgnoreCase)));
    return result ?? throw new InvalidOperationException(
        $"The model has no required standard view ({string.Join("/", fragments)}). Available views: {string.Join(", ", viewNames)}");
}

static IEnumerable<SolidWorks.Interop.sldworks.View> GetModelViews(DrawingDoc drawing)
{
    for (var view = (SolidWorks.Interop.sldworks.View)((SolidWorks.Interop.sldworks.View)drawing.GetFirstView()).GetNextView(); view is not null; view = (SolidWorks.Interop.sldworks.View)view.GetNextView())
        yield return view;
}

static bool ViewsFitOnSheet(
    IReadOnlyCollection<SolidWorks.Interop.sldworks.View> views, double scale, double sheetWidth, double sheetHeight, double lowerMargin)
{
    const double horizontalMargin = 0.025;
    const double upperMargin = 0.02;
    var boxes = views.Select(view => ScaledOutline(view, scale)).ToArray();
    if (boxes.Length == 0)
        return true;
    var width = boxes.Max(box => box.Right) - boxes.Min(box => box.Left);
    var height = boxes.Max(box => box.Top) - boxes.Min(box => box.Bottom);
    return width <= sheetWidth - 2 * horizontalMargin
        && height <= sheetHeight - lowerMargin - upperMargin
        && !boxes.Where((first, index) => boxes.Skip(index + 1).Any(second => Overlaps(first, second))).Any();
}

static (double Left, double Bottom, double Right, double Top) ScaledOutline(SolidWorks.Interop.sldworks.View view, double targetScale)
{
    var outline = (Array)view.GetOutline();
    var left = Convert.ToDouble(outline.GetValue(0));
    var bottom = Convert.ToDouble(outline.GetValue(1));
    var right = Convert.ToDouble(outline.GetValue(2));
    var top = Convert.ToDouble(outline.GetValue(3));
    var multiplier = targetScale / view.ScaleDecimal;
    var centerX = (left + right) / 2;
    var centerY = (bottom + top) / 2;
    return (centerX - (right - left) * multiplier / 2, centerY - (top - bottom) * multiplier / 2,
        centerX + (right - left) * multiplier / 2, centerY + (top - bottom) * multiplier / 2);
}

static bool Overlaps((double Left, double Bottom, double Right, double Top) first, (double Left, double Bottom, double Right, double Top) second)
    => first.Left < second.Right && first.Right > second.Left && first.Bottom < second.Top && first.Top > second.Bottom;

static void RemoveSurfaceFinishSymbols(DrawingDoc drawing, ModelDoc2 drawingModel)
{
    for (var view = (SolidWorks.Interop.sldworks.View)drawing.GetFirstView(); view is not null; view = (SolidWorks.Interop.sldworks.View)view.GetNextView())
    {
        if (view.GetAnnotations() is not Array symbols)
            continue;
        foreach (var item in symbols)
        {
            if (item is not Annotation symbol || symbol.GetType() != (int)swAnnotationType_e.swSFSymbol)
                continue;
            drawingModel.ClearSelection2(true);
            symbol.Select3(false, null);
            drawingModel.Extension.DeleteSelection2(0);
        }
    }
}

static void AddAssemblyTechnicalRequirements(DrawingDoc drawing, ModelDoc2 drawingModel)
{
    AddTechnicalRequirements(drawing, drawingModel, AssemblyTechnicalRequirements);
}

static void AddPartTechnicalRequirements(DrawingDoc drawing, ModelDoc2 drawingModel)
{
    AddTechnicalRequirements(drawing, drawingModel, PartTechnicalRequirements);
}

static void AddTechnicalRequirements(DrawingDoc drawing, ModelDoc2 drawingModel, string requirements)
{
    // Insert a free-standing native note, rather than an annotation tied to a
    // projected view.  It therefore survives view edits and remains directly
    // editable in the drawing, as technical requirements should be.
    drawingModel.ClearSelection2(true);
    var note = drawingModel.InsertNote(requirements) as Note
        ?? throw new InvalidOperationException("SolidWorks did not create the technical requirements note.");
    var annotation = note.GetAnnotation() as Annotation
        ?? throw new InvalidOperationException("SolidWorks did not expose the requirements note annotation.");
    if (!annotation.SetTextFormat(0, true, null))
        throw new InvalidOperationException("SolidWorks did not apply the template text style to the technical requirements.");
    // A note's position is its upper-left corner, not its lower-left corner.
    // Seed it at the upper edge of the sheet, measure its actual text bounds,
    // then translate those bounds so their lower-left corner has the requested
    // margins: 25 mm from the left sheet edge and 10 mm from the bottom edge.
    // This remains correct if a drafting standard changes the font, line
    // spacing, or number of requirement lines.
    var sheet = (Sheet)drawing.GetCurrentSheet();
    var properties = (Array)sheet.GetProperties2();
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    if (!annotation.SetPosition2(
            TechnicalRequirementsLeftMargin,
            sheetHeight - TechnicalRequirementsBottomMargin,
            0.0))
        throw new InvalidOperationException("SolidWorks did not set the initial position of the technical requirements.");

    drawingModel.ForceRebuild3(false);
    var initialExtent = GetNoteExtent(note);
    var initialPosition = (Array)annotation.GetPosition();
    var targetX = Convert.ToDouble(initialPosition.GetValue(0))
        + TechnicalRequirementsLeftMargin - initialExtent.Left;
    var targetY = Convert.ToDouble(initialPosition.GetValue(1))
        + TechnicalRequirementsBottomMargin - initialExtent.Bottom;
    if (!annotation.SetPosition2(targetX, targetY, 0.0))
        throw new InvalidOperationException("SolidWorks did not position the technical requirements on the sheet.");

    // SetPosition2 is the current API and SolidWorks may apply its own
    // display rounding while rebuilding a sheet. The calculated position is
    // still retained; do not turn that benign normalization into a failed
    // drawing export.
    drawingModel.ForceRebuild3(false);
}

static (double Left, double Bottom, double Right, double Top) GetNoteExtent(Note note)
{
    if (note.GetExtent() is not Array extent || extent.Length < 6)
        throw new InvalidOperationException("SolidWorks did not return the technical requirements bounds.");
    return (
        Convert.ToDouble(extent.GetValue(0)), Convert.ToDouble(extent.GetValue(1)),
        Convert.ToDouble(extent.GetValue(3)), Convert.ToDouble(extent.GetValue(4)));
}

static void AddOverallDimensions(DrawingDoc drawing, PalletEnvelope dimensions, PalletViewLayout layout)
{
    // CreateLinearDim4 makes native dimension objects with extension lines
    // and arrows.  The dimensions are deliberately non-associative reference
    // dimensions: they show only the pallet envelope, exactly as requested.
    CreateReferenceLinearDimension(
        drawing, layout.SideLeft, layout.SideBottom - 0.015, layout.SideLeft + layout.SideWidth, layout.SideBottom - 0.015,
        layout.SideLeft, layout.SideBottom, layout.SideLeft + layout.SideWidth, layout.SideBottom,
        dimensions.Length, 0d);
    CreateReferenceLinearDimension(
        drawing, layout.EndLeft, layout.EndBottom - 0.015, layout.EndLeft + layout.EndWidth, layout.EndBottom - 0.015,
        layout.EndLeft, layout.EndBottom, layout.EndLeft + layout.EndWidth, layout.EndBottom,
        dimensions.Width, 0d);
    CreateReferenceLinearDimension(
        drawing, layout.EndLeft + layout.EndWidth + 0.015, layout.EndBottom, layout.EndLeft + layout.EndWidth + 0.015, layout.EndBottom + layout.SideHeight,
        layout.EndLeft + layout.EndWidth, layout.EndBottom, layout.EndLeft + layout.EndWidth, layout.EndBottom + layout.SideHeight,
        dimensions.Height, Math.PI / 2d);
}

static void CreateReferenceLinearDimension(
    DrawingDoc drawing, double dimensionX1, double dimensionY1, double dimensionX2, double dimensionY2,
    double extensionX1, double extensionY1, double extensionX2, double extensionY2, double value, double textAngle)
{
    var center = new[] { (dimensionX1 + dimensionX2) / 2d, (dimensionY1 + dimensionY2) / 2d, 0d };
    var result = drawing.CreateLinearDim4(
        new[] { dimensionX1, dimensionY1, 0d }, new[] { dimensionX2, dimensionY2, 0d }, new[] { 0d, 0d, 1d },
        new[] { extensionX1, extensionY1, 0d }, new[] { extensionX2, extensionY2, 0d }, center,
        value / 1000d, textAngle, 0.004d) as DisplayDimension
        ?? throw new InvalidOperationException("SolidWorks did not create an overall dimension.");
    var dimensionAnnotation = result.GetAnnotation() as Annotation
        ?? throw new InvalidOperationException("SolidWorks did not expose the dimension annotation.");
    if (!dimensionAnnotation.SetTextFormat(0, true, null))
        throw new InvalidOperationException("SolidWorks did not apply the template dimension text style.");
    result.SetText((int)swDimensionTextParts_e.swDimensionTextSuffix, "*");
}

static void AddAssemblySpecification(DrawingDoc drawing, ModelDoc2 drawingModel, SpecificationRow[]? rows)
{
    if (rows is not { Length: > 0 })
        return;

    // A native General Table is deliberately used instead of an image or a
    // pasted spreadsheet: every cell remains editable in SolidWorks.
    // The table shares the title block's left edge and rests directly on its
    // upper edge.  Its grid remains editable in SolidWorks.
    var tableRowCount = rows.Length + 4;
    var tableHeight = SpecificationHeaderHeight + (tableRowCount - 1) * SpecificationRowHeight;
    var table = drawingModel.Extension.InsertGeneralTableAnnotation(
        true, TitleBlockLeft, TitleBlockTop + tableHeight,
        (int)swBOMConfigurationAnchorType_e.swBOMConfigurationAnchor_TopLeft,
        "", tableRowCount, 7)
        ?? throw new InvalidOperationException("SolidWorks did not create the assembly specification table.");
    var annotation = table.GetAnnotation()
        ?? throw new InvalidOperationException("SolidWorks did not expose the specification table annotation.");
    if (!table.SetTextFormat(true, null))
        throw new InvalidOperationException("SolidWorks did not apply the template text style to the specification table.");
    table.BorderLineWeight = (int)swLineWeights_e.swLW_THIN;
    table.GridLineWeight = (int)swLineWeights_e.swLW_THIN;
    if (!annotation.SetPosition(TitleBlockLeft, TitleBlockTop + tableHeight, 0.0))
        throw new InvalidOperationException("SolidWorks did not position the assembly specification table on the sheet.");
    var headers = new[] { "", "", "", "Обозначение детали", "Наименование", "", "Приме-\nчание" };
    for (var column = 0; column < headers.Length; column++)
        table.Text[0, column] = headers[column];

    // Preserve the conventional empty separation rows and section heading.
    table.Text[2, 4] = "Прочие изделия";
    for (var rowIndex = 0; rowIndex < rows.Length; rowIndex++)
    {
        var row = rows[rowIndex];
        var tableRow = rowIndex + 4;
        table.Text[tableRow, 2] = row.Position.ToString();
        table.Text[tableRow, 3] = row.Designation;
        table.Text[tableRow, 4] = string.Join(" ", new[] { row.Name, row.Dimensions }.Where(value => !string.IsNullOrWhiteSpace(value)));
        table.Text[tableRow, 5] = row.Quantity.ToString();
    }
    // 185 mm total: exactly the standard A3 main-title-block width.
    var columnWidths = new[] { 0.007, 0.007, 0.009, 0.064, 0.058, 0.010, 0.030 };
    for (var column = 0; column < columnWidths.Length; column++)
        table.SetColumnWidth(column, columnWidths[column], 0);
    table.SetRowHeight(0, SpecificationHeaderHeight, 0);
    for (var row = 1; row < tableRowCount; row++)
        table.SetRowHeight(row, SpecificationRowHeight, 0);
    drawingModel.ForceRebuild3(false);

    // Table row styles can override requested heights.  Read the actual row
    // heights after rebuilding and use them to keep the lower border exactly
    // on the title block's upper border.
    var actualTableHeight = Enumerable.Range(0, tableRowCount).Sum(table.GetRowHeight);
    if (!annotation.SetPosition(TitleBlockLeft, TitleBlockTop + actualTableHeight, 0.0))
        throw new InvalidOperationException("SolidWorks did not align the assembly specification with the title block.");
    AddRotatedSpecificationHeaders(drawing, drawingModel, TitleBlockTop + actualTableHeight, columnWidths);
}

static void AddRotatedSpecificationHeaders(
    DrawingDoc drawing, ModelDoc2 drawingModel, double tableTop, IReadOnlyList<double> columnWidths)
{
    // General Table ignores Escapement for some document styles.  Native notes
    // render the angle reliably, so they are used for the four narrow headers.
    var captions = new Dictionary<int, (string Text, double Height)>
    {
        [0] = ("Формат", 0.0020),
        [1] = ("Зона", 0.0025),
        [2] = ("Поз.", 0.0025),
        [5] = ("Кол.", 0.0030),
    };
    var x = TitleBlockLeft;
    var notes = new List<(Note Note, double CenterX, double CenterY, double Height)>();
    for (var column = 0; column < columnWidths.Count; column++)
    {
        if (captions.TryGetValue(column, out var caption)
            && drawing.CreateText2(
                caption.Text,
                x + columnWidths[column] / 2d,
                tableTop - SpecificationHeaderHeight / 2d,
                0.0,
                caption.Height,
                Math.PI / 2d) is Note note)
        {
            notes.Add((note, x + columnWidths[column] / 2d, tableTop - SpecificationHeaderHeight / 2d, caption.Height));
        }
        else if (captions.ContainsKey(column))
            throw new InvalidOperationException("SolidWorks did not create a rotated specification header.");
        x += columnWidths[column];
    }
    drawingModel.ForceRebuild3(false);
    foreach (var (note, centerX, centerY, height) in notes)
    {
        var annotation = note.GetAnnotation() as Annotation
            ?? throw new InvalidOperationException("SolidWorks did not expose a rotated specification header.");
        var format = annotation.GetTextFormat(0) as TextFormat
            ?? throw new InvalidOperationException("SolidWorks did not expose the specification header text format.");
        format.CharHeight = height;
        if (!annotation.SetTextFormat(0, false, format))
            throw new InvalidOperationException("SolidWorks did not apply the specification header text format.");
        note.Angle = Math.PI / 2d;
        drawingModel.ForceRebuild3(false);
        var extent = GetNoteExtent(note);
        var position = (Array)annotation.GetPosition();
        var targetX = Convert.ToDouble(position.GetValue(0)) + centerX - (extent.Left + extent.Right) / 2d;
        var targetY = Convert.ToDouble(position.GetValue(1)) + centerY - (extent.Bottom + extent.Top) / 2d;
        if (!annotation.SetPosition2(targetX, targetY, 0.0))
            throw new InvalidOperationException("SolidWorks did not center a rotated specification header.");
    }
}

sealed class PalletDrawingData
{
    public PalletEnvelope? Pallet { get; init; }
    public SpecificationRow[]? Specification { get; init; }
}

sealed class SpecificationRow
{
    public int Position { get; init; }
    public string Name { get; init; } = "";
    public string Dimensions { get; init; } = "";
    public int Quantity { get; init; }
    public string Designation { get; init; } = "";
}

sealed class PalletEnvelope
{
    public double Length { get; init; }
    public double Width { get; init; }
    public double Height { get; init; }
}

sealed record PalletViewLayout(
    double SideLeft, double SideBottom, double SideWidth, double SideHeight,
    double TopLeft, double TopBottom, double TopHeight,
    double EndLeft, double EndBottom, double EndWidth);

