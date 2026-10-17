# 打包小暖团队测试版：.\packaging\build_app.ps1 -ModelsDir D:\models [-Publish]
# 需要 Python 3.12，以及 body-requirements.txt、companion/requirements.txt 和 pyinstaller。
# -Publish：把 zip 上传到 GitHub Release “team-test-latest”（覆盖旧的同名附件），需要已登录的 gh。
#           zip 约 200MB，超过 Git 单文件 100MB 上限，所以放 Release 附件而不是提交进仓库。
param(
    [Parameter(Mandatory = $true)][string]$ModelsDir,
    [string]$OutDir = (Join-Path (Split-Path $PSScriptRoot -Parent) '..\appbuild'),
    [string]$Python = 'python',
    [switch]$Publish,
    [string]$Tag = 'team-test-latest'
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

if ($Publish) {
    Push-Location $repo
    try {
        $commit = (git rev-parse --short HEAD).Trim()
        $branch = (git rev-parse --abbrev-ref HEAD).Trim()
        $dirty = if (git status --porcelain --untracked-files=no) { '（含未提交改动）' } else { '' }
        $sha = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
        $notes = @"
小暖团队测试版（始终是最新一次构建）

- 构建自 ``$branch`` @ ``$commit``$dirty，$(Get-Date -Format 'yyyy-MM-dd HH:mm')
- 下载下面的 **Xiaonuan-team-test.zip**，解压后双击 Xiaonuan.exe，按压缩包里的 README.txt 操作
- SHA256: ``$sha``

压缩包不含任何密钥或聊天数据；密钥在每台电脑的设置页里填写。
"@
        gh release view $Tag *> $null
        if ($LASTEXITCODE -ne 0) {
            gh release create $Tag --prerelease --target main --title '小暖团队测试版（最新）' --notes $notes
            if ($LASTEXITCODE -ne 0) { throw 'gh release create failed' }
        }
        gh release upload $Tag $zip --clobber
        if ($LASTEXITCODE -ne 0) { throw 'gh release upload failed' }
        gh release edit $Tag --notes $notes
        if ($LASTEXITCODE -ne 0) { throw 'gh release edit failed' }
        $url = (gh release view $Tag --json url -q .url).Trim()
        Write-Host "Published $url"
    } finally {
        Pop-Location
    }
}
