using System;
using System.IO;

internal static class SheetFormatPolicy
{
    // Return to sheet editing even if COM inspection fails, so all subsequent
    // views and annotations are created on the drawing rather than the format.
    public static bool Inspect(Action enterFormat, Func<bool> readGeometry, Action leaveFormat)
    {
        enterFormat();
        try { return readGeometry(); }
        finally { leaveFormat(); }
    }

    // A sheet format is embedded in many drawing templates. Prefer its actual
    // contents; reload only its own linked file if the embedded format is empty.
    public static void Ensure(Func<bool> hasGeometry, Func<string?> linkedPath,
        Func<string, bool> exists, Func<int> reload, int successCode, string drawingTemplate)
    {
        if (hasGeometry())
            return;
        var linked = linkedPath();
        if (!string.IsNullOrWhiteSpace(linked) && exists(linked))
        {
            var result = reload();
            if (result != successCode)
                throw new InvalidOperationException($"SolidWorks не загрузил формат листа «{linked}» (код {result}).");
            if (hasGeometry())
                return;
        }
        throw new InvalidOperationException(
            $"В шаблоне чертежа «{drawingTemplate}» не найдены рамка и формат листа. " +
            "Проверьте связанный файл .slddrt или сохраните шаблон с форматом листа.");
    }
}
