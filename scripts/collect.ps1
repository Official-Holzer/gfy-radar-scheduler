$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$catalog = Get-Content -Raw (Join-Path $PSScriptRoot '../catalog.json') | ConvertFrom-Json
$key = $env:COLLECTOR_KEY
$saved = 0
$failures = 0
foreach ($product in $catalog) {
  $asin = $product.id
  try {
    $page = Invoke-WebRequest "https://www.amazon.de/dp/$asin" -TimeoutSec 25
    $cents = $page.Content | python -B (Join-Path $PSScriptRoot 'collect.py') $asin
    if ($LASTEXITCODE) { throw 'Parser failed.' }
    if (!$cents) {
      Write-Host "$asin skipped (no unambiguous one-time price)"
      continue
    }
    if (!$key) { Write-Host "$asin verified $cents cents (unpublished)"; continue }
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
Write-Host "$saved of $($catalog.Count) products recorded"
if (!$saved -or $failures) { exit 1 }
