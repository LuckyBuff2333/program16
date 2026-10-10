# Clean Edge cache dirs after verifying Edge is fully closed (whitelist only)
# User confirmed: terminate background msedge processes (all windowless), then clean immediately
Write-Host "--- Step 1: terminate Edge background processes ---"
$edge = Get-Process msedge -ErrorAction SilentlyContinue
if ($edge) {
    $edge | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    $left = Get-Process msedge -ErrorAction SilentlyContinue
    Write-Host ('Killed. Remaining msedge processes: ' + @( $left ).Count)
} else {
    Write-Host 'No msedge process found.'
}

function Get-DirSize($p) {
    if (-not (Test-Path $p)) { return 0 }
    $s = (Get-ChildItem $p -Recurse -Force -ErrorAction SilentlyContinue | Where-Object { -not $_.PSIsContainer } | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $s) { return 0 }
    return $s
}

$targets = @(
    'C:\Users\20637\AppData\Local\Microsoft\Edge\User Data\Default\Cache',
    'C:\Users\20637\AppData\Local\Microsoft\Edge\User Data\Default\Code Cache'
)

# safety guard: only delete paths under Edge cache whitelist
$allowedPrefix = 'C:\Users\20637\AppData\Local\Microsoft\Edge\User Data\Default\'

Write-Host ""
Write-Host "--- Step 2: delete cache dirs ---"
$freed = 0
foreach ($t in $targets) {
    if (-not $t.StartsWith($allowedPrefix)) { Write-Host ('SKIP(forbidden): ' + $t); continue }
    if (Test-Path $t) {
        $before = Get-DirSize $t
        try {
            Remove-Item $t -Recurse -Force -ErrorAction Stop
        } catch {
            Write-Host ('ERROR: ' + $_.Exception.Message)
        }
        if (Test-Path $t) {
            $after = Get-DirSize $t
            Write-Host ('PARTIAL (some files in use): ' + $t + ', removed ' + [math]::Round(($before-$after)/1MB,1) + ' MB')
            $freed += ($before - $after)
        } else {
            Write-Host ('DELETED: ' + $t + ' (' + [math]::Round($before/1MB,1) + ' MB)')
            $freed += $before
        }
    } else {
        Write-Host ('NOT FOUND (already gone): ' + $t)
    }
}

Write-Host ""
Write-Host ('Total freed: ' + [math]::Round($freed/1MB,1) + ' MB')
Get-PSDrive C | ForEach-Object { Write-Host ('C free = ' + [math]::Round($_.Free/1GB,2) + ' GB') }
