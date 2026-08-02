param(
    [Parameter(Mandatory = $true)]
    [string] $TargetPath
)

$ErrorActionPreference = "Stop"
$target = [IO.Path]::GetFullPath($TargetPath)
$processName = [IO.Path]::GetFileNameWithoutExtension($target)
$processes = @(
    Get-Process -Name $processName -ErrorAction SilentlyContinue |
        Where-Object {
            try {
                $candidatePath = $_.Path
            } catch {
                return $false
            }
            $candidatePath -and [string]::Equals(
                [IO.Path]::GetFullPath($candidatePath),
                $target,
                [StringComparison]::OrdinalIgnoreCase
            )
        }
)

foreach ($process in $processes) {
    Stop-Process -Id $process.Id -Force -ErrorAction Stop
    if (-not $process.WaitForExit(5000)) {
        throw "Timed out stopping the installed Plasma backend."
    }
}
