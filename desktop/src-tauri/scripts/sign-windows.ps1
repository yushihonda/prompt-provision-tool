param(
    [Parameter(Mandatory = $true)]
    [string]$TargetPath
)

$thumbprint = $env:PPT_WINDOWS_CERTIFICATE_THUMBPRINT
if ([string]::IsNullOrWhiteSpace($thumbprint)) {
    throw "PPT_WINDOWS_CERTIFICATE_THUMBPRINT is required for Windows release signing."
}

$timestampUrl = $env:PPT_WINDOWS_TIMESTAMP_URL
if ([string]::IsNullOrWhiteSpace($timestampUrl)) {
    $timestampUrl = "https://timestamp.digicert.com"
}

$signtoolPath = $env:TAURI_WINDOWS_SIGNTOOL_PATH
if ([string]::IsNullOrWhiteSpace($signtoolPath)) {
    $signtool = Get-Command signtool.exe -ErrorAction Stop
    $signtoolPath = $signtool.Source
}

Write-Host "Signing $TargetPath with thumbprint $thumbprint"
& $signtoolPath sign /sha1 $thumbprint /fd sha256 /tr $timestampUrl /td sha256 $TargetPath

if ($LASTEXITCODE -ne 0) {
    throw "signtool failed for $TargetPath"
}
