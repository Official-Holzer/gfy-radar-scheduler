$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$catalog = Get-Content -Raw (Join-Path $PSScriptRoot '../catalog.json') | ConvertFrom-Json
# Visit the next slice per workflow run to keep free-runner traffic bounded.
$batchSize = 20
$runNumber = if ($env:GITHUB_RUN_NUMBER) { [long]$env:GITHUB_RUN_NUMBER } else { 1 }
$offset = (($runNumber - 1) * $batchSize) % $catalog.Count
$batch = for ($i = 0; $i -lt [Math]::Min($batchSize, $catalog.Count); $i++) {
  $catalog[($offset + $i) % $catalog.Count]
}
$key = $env:COLLECTOR_KEY
$saved = 0
$unavailable = 0
$unpublished = 0
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
    if (!$key) {
      $unpublished++
      Write-Host "$asin verified $cents cents (unpublished)"
      continue
    }
    $body = @{cents = [int]$cents; observedAt = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()} | ConvertTo-Json
    $uri = "$env:GFY_ORIGIN/api/catalog/$asin"
    $result = Invoke-RestMethod $uri -Method Post -MaximumRedirection 0 -Headers @{Authorization = "Bearer $key"} -ContentType application/json -Body $body -TimeoutSec 20
    if (!$result.saved) { throw 'Database write was not acknowledged.' }
    Write-Host "$asin recorded $cents cents"
    $saved++
  }
  catch {
    Write-Warning "$asin collection failed: $($_.Exception.Message)"
    $failures++
  }
}
$summary = "$($batch.Count) of $($catalog.Count) catalog products checked: $saved saved, $unavailable without a clear price, $unpublished verified in read-only mode, $failures errors."
Write-Host $summary
if ($env:GITHUB_STEP_SUMMARY) {
  Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $summary
  if (!$key) { Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value 'Read-only run. Website publishing is not configured.' }
}
if ($failures) { exit 1 }
