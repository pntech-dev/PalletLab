"""Exercise the actual .NET sheet-format policy without requiring SolidWorks."""

from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(shutil.which("dotnet") is None, reason=".NET SDK is required")
def test_sheet_format_policy_preserves_embedded_and_checks_reload(tmp_path):
    source = Path(__file__).resolve().parents[1] / "tools" / "SolidWorksDrawingHelper" / "SheetFormatPolicy.cs"
    (tmp_path / "SheetFormatPolicy.cs").write_text(source.read_text(encoding="utf-8-sig"), encoding="utf-8")
    (tmp_path / "PolicyTests.csproj").write_text(
        '<Project Sdk="Microsoft.NET.Sdk"><PropertyGroup><OutputType>Exe</OutputType>'
        '<TargetFramework>net10.0</TargetFramework><Nullable>enable</Nullable>'
        '</PropertyGroup></Project>', encoding="utf-8",
    )
    (tmp_path / "Program.cs").write_text(r'''
using System;

var inFormat = false;
if (!SheetFormatPolicy.Inspect(() => inFormat = true, () => inFormat, () => inFormat = false) || inFormat)
    throw new Exception("Sheet format must be inspected in format-edit mode and restored afterwards.");
try
{
    SheetFormatPolicy.Inspect(() => inFormat = true, () => throw new InvalidOperationException(), () => inFormat = false);
}
catch (InvalidOperationException) { }
if (inFormat) throw new Exception("Edit mode was not restored after a failed inspection.");

var reloads = 0;
// Embedded format stays untouched even if the linked file is missing.
SheetFormatPolicy.Ensure(() => true, () => "missing.slddrt", _ => false,
    () => { reloads++; return 0; }, 0, "embedded.drwdot");
if (reloads != 0) throw new Exception("Embedded format must not be reloaded.");

// An empty format can be restored only from its own linked format.
var hasGeometry = false;
SheetFormatPolicy.Ensure(() => hasGeometry, () => "linked.slddrt", path => path == "linked.slddrt",
    () => { reloads++; hasGeometry = true; return 0; }, 0, "linked.drwdot");
if (reloads != 1) throw new Exception("The linked format was not loaded.");

void MustFail(Action action, string expected)
{
    try { action(); }
    catch (InvalidOperationException error) when (error.Message.Contains(expected)) { return; }
    throw new Exception("Missing expected error: " + expected);
}
MustFail(() => SheetFormatPolicy.Ensure(() => false, () => "missing.slddrt", _ => false,
    () => throw new Exception("Must not reload a missing format"), 0, "missing.drwdot"), "missing.drwdot");
MustFail(() => SheetFormatPolicy.Ensure(() => false, () => "linked.slddrt", _ => true,
    () => 2, 0, "drawing.drwdot"), "код 2");
MustFail(() => SheetFormatPolicy.Ensure(() => false, () => "linked.slddrt", _ => true,
    () => 0, 0, "drawing.drwdot"), "не найдены");
''', encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - runs the local SDK and a test-created project.
        [shutil.which("dotnet"), "run", "--project", str(tmp_path / "PolicyTests.csproj"), "--configuration", "Release"],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
