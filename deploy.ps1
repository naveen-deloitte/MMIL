[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('dev', 'test', 'prod')]
    [string]$Stage,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]+[a-z0-9]$')]
    [string]$Region,

    [Parameter(Mandatory = $true)]
    [string]$WebImage,

    [Parameter(Mandatory = $true)]
    [string]$ApiImage,

    [Parameter(Mandatory = $true)]
    [string]$WorkerImage,

    [string]$Profile,

    [switch]$Execute,

    [switch]$Bootstrap,

    [switch]$ApproveProduction
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Assert-Command {
    param([Parameter(Mandatory = $true)][string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Required command '$Name' was not found on PATH."
    }
}

function Invoke-Cdk {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    & cdk @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "AWS CDK failed with exit code $LASTEXITCODE."
    }
}

function Assert-ImageDigest {
    param([Parameter(Mandatory = $true)][string]$Image, [Parameter(Mandatory = $true)][string]$Name)
    if ($Image -notmatch '^[^@\s]+@sha256:[0-9a-fA-F]{64}$') {
        throw "$Name must be an immutable container image reference ending in @sha256:<64 hex characters>."
    }
}

Assert-Command -Name 'aws'
Assert-Command -Name 'cdk'
Assert-ImageDigest -Image $WebImage -Name 'WebImage'
Assert-ImageDigest -Image $ApiImage -Name 'ApiImage'
Assert-ImageDigest -Image $WorkerImage -Name 'WorkerImage'

$infraPath = Join-Path $PSScriptRoot 'infra'
$cdkConfig = Join-Path $infraPath 'cdk.json'
$cdkApp = Join-Path $infraPath 'app.py'
if (-not (Test-Path -LiteralPath $cdkConfig -PathType Leaf) -or
    -not (Test-Path -LiteralPath $cdkApp -PathType Leaf)) {
    throw "CDK application not found. Implement infra\cdk.json and infra\app.py per aws-deployment-plan.md before deploying."
}

$awsArgs = @('sts', 'get-caller-identity', '--query', 'Account', '--output', 'text', '--region', $Region)
if ($Profile) {
    $awsArgs += @('--profile', $Profile)
}
$accountId = (& aws @awsArgs)
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($accountId)) {
    throw 'Unable to verify the active AWS account; deployment stopped.'
}
$accountId = $accountId.Trim()

Write-Host "Verified AWS account: $accountId"
Write-Host "Stage: $Stage | Region: $Region"
Write-Host 'Images are pinned by digest.'

if ($Stage -eq 'prod' -and -not $ApproveProduction) {
    throw "Production deployment requires the explicit -ApproveProduction switch."
}

$cdkArgs = @(
    'diff',
    'DocumentAgent-' + $Stage,
    '--no-color',
    '-c', "stage=$Stage",
    '-c', "region=$Region",
    '-c', "account=$accountId",
    '-c', "webImage=$WebImage",
    '-c', "apiImage=$ApiImage",
    '-c', "workerImage=$WorkerImage"
)
if ($Profile) {
    $cdkArgs += @('--profile', $Profile)
}

Push-Location $infraPath
try {
    if (-not $Execute) {
        Write-Host 'Diff only. No AWS resources will be changed.'
        Invoke-Cdk -Arguments $cdkArgs
        Write-Host 'Review the diff, then rerun with -Execute to deploy.'
    }
    else {
        if ($Bootstrap) {
            $bootstrapArgs = @('bootstrap', "$accountId/$Region")
            if ($Profile) {
                $bootstrapArgs += @('--profile', $Profile)
            }
            Invoke-Cdk -Arguments $bootstrapArgs
        }

        Invoke-Cdk -Arguments $cdkArgs

        $deployArgs = @(
            'deploy',
            'DocumentAgent-' + $Stage,
            '--require-approval', 'broadening',
            '--concurrency', '1',
            '-c', "stage=$Stage",
            '-c', "region=$Region",
            '-c', "account=$accountId",
            '-c', "webImage=$WebImage",
            '-c', "apiImage=$ApiImage",
            '-c', "workerImage=$WorkerImage"
        )
        if ($Profile) {
            $deployArgs += @('--profile', $Profile)
        }
        Invoke-Cdk -Arguments $deployArgs
    }
}
finally {
    Pop-Location
}
