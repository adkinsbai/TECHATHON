# 打包小暖团队测试版：.\packaging\build_app.ps1 -ModelsDir D:\models
# 需要 Python 3.12，以及 body-requirements.txt、companion/requirements.txt 和 pyinstaller。
param(
    [Parameter(Mandatory = $true)][string]$ModelsDir,
    [string]$OutDir = (Join-Path (Split-Path $PSScriptRoot -Parent) '..\appbuild'),
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$model = 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2025-09-09'
if (-not (Test-Path (Join-Path $ModelsDir "$model\model.int8.onnx"))) { throw "Missing $model in $ModelsDir (python -m voice_pack.download --models-dir ...)" }
$OutDir = [IO.Path]::GetFullPath($OutDir)
New-Item -ItemType Directory -Force $OutDir | Out-Null

& $Python -m PyInstaller --noconfirm --clean --distpath (Join-Path $OutDir 'dist') --workpath (Join-Path $OutDir 'work') (Join-Path $PSScriptRoot 'xiaonuan.spec')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

$app = Join-Path $OutDir 'dist\Xiaonuan'
$target = Join-Path $app "models\$model"
New-Item -ItemType Directory -Force $target | Out-Null
Copy-Item (Join-Path $ModelsDir "$model\*") $target -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot 'README-team-test.txt') (Join-Path $app 'README.txt') -Force

$zip = Join-Path $OutDir 'Xiaonuan-team-test.zip'
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
Write-Host "Built $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB)"
