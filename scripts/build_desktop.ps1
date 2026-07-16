param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

$arguments = @(
    "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed",
    "--name", "耳廓工程分析",
    "--add-data", "desktop_app\assets;desktop_app\assets",
    "--collect-all", "pyvista",
    "--collect-all", "pyvistaqt",
    "--collect-all", "vtkmodules",
    "--hidden-import", "scripts.run_full_pipeline",
    "--hidden-import", "scripts.parameterize_ear_remesh",
    "--hidden-import", "scripts.visualize_remesh_qc",
    "--hidden-import", "scripts.build_whole_ear",
    "--hidden-import", "scripts.align_whole_ear",
    "--hidden-import", "scripts.build_average_ear",
    "desktop_app\__main__.py"
)
if ($OneFile) { $arguments += "--onefile" }

& python @arguments
if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败，退出码：$LASTEXITCODE" }

Write-Host "构建完成：dist\耳廓工程分析"
