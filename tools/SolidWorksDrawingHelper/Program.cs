using System.Text.Json;
using SolidWorks.Interop.sldworks;
using SolidWorks.Interop.swconst;

const double WorkingLeftMargin = 0.050;
const double WorkingRightMargin = 0.020;
const double WorkingLowerReserve = 0.080;
const double WorkingUpperMargin = 0.020;
const double ProjectedViewGap = 0.015;
const double ManualAnnotationReserve = 0.035;

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
    var errors = 0;
    var warnings = 0;
    var model = sw.OpenDoc6(modelPath, documentType, (int)swOpenDocOptions_e.swOpenDocOptions_Silent, "", ref errors, ref warnings);
    if (model is null)
        throw new InvalidOperationException($"SolidWorks could not open model (errors={errors}, warnings={warnings}).");

    var pallet = args.Length == 4
        ? JsonSerializer.Deserialize<PalletDrawingData>(File.ReadAllText(args[3]), new JsonSerializerOptions { PropertyNameCaseInsensitive = true })
        : null;
    if (sw.NewDocument(Path.GetFullPath(args[0]), 0, 0.0, 0.0) is null)
        throw new InvalidOperationException("SolidWorks did not create a drawing document.");
    var drawing = (DrawingDoc)(sw.IActiveDoc2 ?? throw new InvalidOperationException("Drawing document is not active."));
    var drawingModel = (ModelDoc2)drawing;
    ApplyGostSheetScale(sw, drawing, pallet);
    if (pallet?.Pallet is not null)
        CreatePalletOrthographicViews(drawing, model, modelPath, pallet);
    else if (!drawing.Create3rdAngleViews2(modelPath))
        throw new InvalidOperationException("SolidWorks did not create standard views.");
    // View insertion can apply the user's automatic-scale preference.  Apply
    // the selected GOST scale again after the three views are present.
    ApplyGostSheetScale(sw, drawing, pallet);
    drawingModel.ForceRebuild3(false);
    RemoveSurfaceFinishSymbols(drawing, drawingModel);
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
    Console.Error.WriteLine(error);
    return 1;
}

static void ApplyGostSheetScale(SldWorks sw, DrawingDoc drawing, PalletDrawingData? pallet)
{
    var sheet = (Sheet)drawing.GetCurrentSheet();
    (double Numerator, double Denominator)[] allowed =
    {
        (Numerator: 1d, Denominator: 1d), (1d, 2d), (1d, 2.5d), (1d, 4d),
        (1d, 5d), (1d, 10d), (1d, 15d), (1d, 20d), (1d, 25d), (1d, 40d),
        (1d, 50d), (1d, 75d), (1d, 100d), (1d, 200d), (1d, 400d),
        (1d, 500d), (1d, 800d), (1d, 1000d),
    };
    var properties = (Array)sheet.GetProperties2();
    var sheetWidth = Convert.ToDouble(properties.GetValue(5));
    var sheetHeight = Convert.ToDouble(properties.GetValue(6));
    var views = GetModelViews(drawing).ToArray();
    var chosen = allowed.FirstOrDefault(scale => pallet is not null
        ? PalletLayoutFits(pallet.Pallet, scale.Numerator / scale.Denominator, sheetWidth, sheetHeight)
        : ViewsFitOnSheet(views, scale.Numerator / scale.Denominator, sheetWidth, sheetHeight));
    if (chosen == default)
        chosen = allowed[^1];
    sheet.SetScale(chosen.Numerator, chosen.Denominator, true, false);
    foreach (var view in views)
        view.UseSheetScale = 1;
    // Pallet views receive their exact projected layout in
    // CreatePalletOrthographicViews.  Re-centering them here would override
    // that layout and can break their native alignment relations.
    if (pallet?.Pallet is null)
        CenterProjectedViewGroup(views, sheetWidth, sheetHeight);
}

static bool PalletLayoutFits(PalletEnvelope? pallet, double scale, double sheetWidth, double sheetHeight)
{
    if (pallet is null)
        return false;
    var length = pallet.Length / 1000d * scale;
    var width = pallet.Width / 1000d * scale;
    var height = pallet.Height / 1000d * scale;
    return length + width + ProjectedViewGap <= sheetWidth - WorkingLeftMargin - WorkingRightMargin
        && width + ManualAnnotationReserve + ProjectedViewGap + height
            <= sheetHeight - WorkingLowerReserve - WorkingUpperMargin;
}

static void CenterProjectedViewGroup(
    IReadOnlyCollection<SolidWorks.Interop.sldworks.View> views, double sheetWidth, double sheetHeight)
{
    var mainView = views.FirstOrDefault(view => view.GetBaseView() is null);
    if (mainView is null)
        return;

    const double lowerMargin = 0.085;
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

static void CreatePalletOrthographicViews(DrawingDoc drawing, ModelDoc2 model, string modelPath, PalletDrawingData pallet)
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
    var groupHeight = sideHeight + ManualAnnotationReserve + ProjectedViewGap + topHeight;
    var workingWidth = sheetWidth - WorkingLeftMargin - WorkingRightMargin;
    var workingHeight = sheetHeight - WorkingLowerReserve - WorkingUpperMargin;
    if (groupWidth > workingWidth || groupHeight > workingHeight)
        throw new InvalidOperationException("The selected GOST scale does not leave space for the projected views.");

    // Centre the entire orthographic group in the usable sheet area.  The
    // title block below and the left frame are deliberately excluded, so the
    // views are neither pressed against the border nor drawn over the stamp.
    var groupLeft = WorkingLeftMargin + (workingWidth - groupWidth) / 2d;
    var groupBottom = WorkingLowerReserve + (workingHeight - groupHeight) / 2d;
    var sideX = groupLeft + sideWidth / 2d;
    var sideY = groupBottom + topHeight + ManualAnnotationReserve + ProjectedViewGap + sideHeight / 2d;
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
    var top = drawing.CreateDrawViewFromModelView3(modelPath, topName, topX, topY, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the top view.");
    var end = drawing.CreateDrawViewFromModelView3(modelPath, endName, endX, endY, 0d)
        ?? throw new InvalidOperationException("SolidWorks did not create the end view.");
    side.UseSheetScale = 1;
    top.UseSheetScale = 1;
    end.UseSheetScale = 1;
    // Retain the projection relationship: the top view may move only along
    // the vertical projection line, and the end view only along the horizontal
    // one.  Use the documented object-based API rather than the name-based
    // convenience methods; the latter produced invalid dependent views in
    // some SolidWorks installations after a user drag.
    if (!top.AlignWithView((int)swAlignViewTypes_e.swAlignViewVerticalCenter, side)
        || !end.AlignWithView((int)swAlignViewTypes_e.swAlignViewHorizontalCenter, side))
        throw new InvalidOperationException("SolidWorks did not preserve the projected-view alignment.");
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

static bool ViewsFitOnSheet(IReadOnlyCollection<SolidWorks.Interop.sldworks.View> views, double scale, double sheetWidth, double sheetHeight)
{
    const double horizontalMargin = 0.025;
    const double lowerMargin = 0.085;
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
        if (view.GetAnnotationsByType((int)swAnnotationType_e.swSFSymbol) is not Array symbols)
            continue;
        foreach (var item in symbols)
        {
            if (item is not Annotation symbol)
                continue;
            drawingModel.ClearSelection2(true);
            symbol.Select3(false, null);
            drawingModel.Extension.DeleteSelection2(0);
        }
    }
}

sealed class PalletDrawingData
{
    public PalletEnvelope? Pallet { get; init; }
}

sealed class PalletEnvelope
{
    public double Length { get; init; }
    public double Width { get; init; }
    public double Height { get; init; }
}

