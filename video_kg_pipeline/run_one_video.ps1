param(
    [Parameter(Mandatory=$true)][string]$VideoPath,
    [Parameter(Mandatory=$true)][string]$Label,
    [Parameter(Mandatory=$true)][string]$PipelineRoot,
    [Parameter(Mandatory=$true)][string]$PythonExe
)

$ErrorActionPreference = "Stop"

$outDir = Join-Path $PipelineRoot "outputs_batch\$Label"
New-Item -ItemType Directory -Force -Path $outDir | Out-Null

$env:VIDEO_PATH = $VideoPath
$env:OUTPUT_DIR = $outDir

Set-Location $PipelineRoot
$logFile = Join-Path $outDir "run.log"
$errFile = Join-Path $outDir "run.err.log"

$proc = Start-Process -FilePath $PythonExe -ArgumentList @("run_pipeline.py", "--full") `
    -WorkingDirectory $PipelineRoot -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile
$exitCode = $proc.ExitCode

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$ni = New-Object System.Windows.Forms.NotifyIcon
$ni.Icon = [System.Drawing.SystemIcons]::Information
$ni.Visible = $true
if ($exitCode -eq 0) {
    $ni.BalloonTipTitle = "视频知识提取完成: $Label"
    $ni.BalloonTipText = "已完成: $VideoPath"
} else {
    $ni.BalloonTipTitle = "视频知识提取失败: $Label"
    $ni.BalloonTipText = "退出码 $exitCode, 查看 $logFile"
}
$ni.ShowBalloonTip(10000)
Start-Sleep -Seconds 2
$ni.Dispose()

Write-Output "EXIT_CODE=$exitCode"
Write-Output "OUTPUT_DIR=$outDir"

if ($exitCode -eq 0) {
    $kgPath = Join-Path $outDir "05_knowledge_graph.json"
    if (Test-Path $kgPath) {
        $kg = [System.IO.File]::ReadAllText($kgPath, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
        Write-Output "NODE_COUNT=$($kg.Count)"
        $conflicts = @($kg | Where-Object { $_.conflict -eq $true }).Count
        Write-Output "CONFLICT_COUNT=$conflicts"
    }
}
