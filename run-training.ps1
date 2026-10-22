param(
    [ValidateSet('sft','grpo')][string]$Mode = 'sft',
    [switch]$DryRun,
    [int]$MaxSteps = 0,
    [string]$Output = '',
    [string]$SftAdapter = ''
)
$taskWorkspace = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$taskPython = Join-Path $taskWorkspace 'work\training-venv\Scripts\python.exe'
if (Test-Path -LiteralPath $taskPython) {
    $env:HF_HOME = Join-Path $taskWorkspace 'work\model-cache'
} else {
    $taskPython = 'python'
    $env:HF_HOME = Join-Path $PSScriptRoot '.model-cache'
}
$env:HF_HUB_DISABLE_TELEMETRY = '1'
$env:HF_HUB_DISABLE_IMPLICIT_TOKEN = '1'
$env:HF_HUB_DISABLE_XET = '1'
$taskArguments = @('-m','training.train',$Mode)
$taskLocalModel = Join-Path $taskWorkspace 'work\models\Qwen2.5-0.5B-Instruct'
if (Test-Path -LiteralPath (Join-Path $taskLocalModel 'download_provenance.json')) {
    $taskArguments += @('--model',$taskLocalModel)
} elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot '.model-cache\Qwen2.5-0.5B-Instruct\download_provenance.json')) {
    $taskArguments += @('--model',(Join-Path $PSScriptRoot '.model-cache\Qwen2.5-0.5B-Instruct'))
}
if ($DryRun) { $taskArguments += '--dry-run' }
if ($MaxSteps -gt 0) { $taskArguments += @('--max-steps',"$MaxSteps") }
if ($Output) { $taskArguments += @('--output',$Output) }
if ($SftAdapter) { $taskArguments += @('--sft-adapter',$SftAdapter) }
$taskPreviousLocation = Get-Location
$taskExitCode = 0
try {
    Set-Location -LiteralPath $PSScriptRoot
    & $taskPython @taskArguments
    $taskExitCode = $LASTEXITCODE
} finally {
    Set-Location -LiteralPath $taskPreviousLocation
}
exit $taskExitCode
