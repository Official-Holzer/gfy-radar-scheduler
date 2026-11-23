$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$catalog = Get-Content -Raw (Join-Path $PSScriptRoot '../catalog.json') | ConvertFrom-Json
# Partition the catalog across the 168 hourly runs in a week.
$runsPerWeek = 7 * 24
$runNumber = if ($env:GITHUB_RUN_NUMBER) { [long]$env:GITHUB_RUN_NUMBER } else { 1 }
$slot = ($runNumber - 1) % $runsPerWeek
$start = [int][Math]::Floor($slot * $catalog.Count / $runsPerWeek)
$end = [int][Math]::Floor(($slot + 1) * $catalog.Count / $runsPerWeek)
$batch = for ($i = $start; $i -lt $end; $i++) {
  $catalog[$i]
}
$historyDir = Join-Path $PSScriptRoot '../prices'
New-Item -ItemType Directory -Force $historyDir | Out-Null
$saved = 0
$unavailable = 0
$failures = 0
foreach ($product in $batch) {
  $asin = $product.id
  try {
    $page = Invoke-WebRequest "https://www.amazon.de/dp/$asin" -TimeoutSec 25
    $cents = $page.Content | python -B (Join-Path $PSScriptRoot 'collect.py') $asin
    if ($LASTEXITCODE) { throw 'Parser failed.' }
    if (!$cents) {
      $unavailable++
      Write-Host "$asin skipped (no unambiguous one-time price)"
      continue
    }
    if ($asin -cnotmatch '^[A-Z0-9]{10}$' -or [int]$cents -le 0) { throw 'Invalid observation.' }
    $path = Join-Path $historyDir "$asin.json"
    $previous = if (Test-Path -LiteralPath $path) { Get-Content -Raw -LiteralPath $path | ConvertFrom-Json }
    $points = @($previous | Where-Object { $null -ne $_ }) + @(@{
      observed_at = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
      cents = [int]$cents
      source = 'amazon'
    })
    ConvertTo-Json -InputObject $points -Compress | Set-Content -LiteralPath $path -Encoding utf8NoBOM
    Write-Host "$asin recorded $cents cents"
    $saved++
  }
  catch {
    Write-Warning "$asin collection failed: $($_.Exception.Message)"
    $failures++
  }
}
$summary = "$($batch.Count) of $($catalog.Count) catalog products checked: $saved saved, $unavailable without a clear price, $failures errors."
Write-Host $summary
if ($env:GITHUB_STEP_SUMMARY) {
  Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $summary
}
if ($failures) { exit 1 }
