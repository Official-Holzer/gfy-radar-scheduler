$ErrorActionPreference = 'Stop'
$OutputEncoding = [Text.UTF8Encoding]::new($false)
$repo = Split-Path $PSScriptRoot
$origin = 'https://gfy-preisradar.lucaholzerlz.chatgpt.site'
$catalog = Get-Content -Raw (Join-Path $repo 'catalog.json') | ConvertFrom-Json
$seedIds = [Collections.Generic.HashSet[string]]::new([string[]]$catalog.id)
$historyDir = Join-Path $repo 'prices'
$progressPath = Join-Path $repo 'rotation.json'
$progress = Get-Content -Raw $progressPath | ConvertFrom-Json
$runsPerWeek = 168

function Get-Batch([int]$slot) {
  $start = [int][Math]::Floor($slot * $catalog.Count / $runsPerWeek)
  $end = [int][Math]::Floor(($slot + 1) * $catalog.Count / $runsPerWeek)
  $enrolled = Invoke-RestMethod "$origin/api/enrollments/$slot" -TimeoutSec 30
  if ($null -eq $enrolled.products) { throw 'Missing weekly enrollment list.' }
  for ($i = $start; $i -lt $end; $i++) { $catalog[$i].id }
  foreach ($product in $enrolled.products) {
    if ($product.id -cmatch '^[A-Z0-9]{10}$' -and !$seedIds.Contains($product.id)) { $product.id }
  }
}

function Get-SeedPrice([string]$asin) {
  $page = Invoke-WebRequest "https://www.amazon.de/dp/$asin" -Headers @{'Accept-Language'='de-DE'} -TimeoutSec 25 -SkipHttpErrorCheck
  if ($page.StatusCode -in 404,410) { return 'missing' }
  if ($page.StatusCode -ne 200) { throw "Amazon HTTP $($page.StatusCode)" }
  $result = $page.Content | python -B (Join-Path $PSScriptRoot 'collect.py') $asin
  if ($LASTEXITCODE) { throw 'Parser failed.' }
  if ($result -in 'unmatched','no-price') { return $result }
  if ($result -notmatch '^[1-9][0-9]{0,7}$') { throw 'Invalid price output.' }
  return @{ observed_at=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds(); cents=[int]$result; source='amazon' }
}

function Get-EnrolledPrice([string]$asin) {
  $history = Invoke-RestMethod "$origin/api/history/$asin" -TimeoutSec 30
  if ($history.tracked -ne $true -or $null -eq $history.observations) { throw 'Invalid tracked history response.' }
  $now = [DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  foreach ($point in $history.observations) {
    if ($point.source -ceq 'amazon' -and ($point.cents -is [int] -or $point.cents -is [long]) -and
        $point.cents -gt 0 -and $point.cents -le 99999999 -and $point.observed_at -eq $history.lastAttempt -and
        $point.observed_at -ge ($now - 3600000) -and $point.observed_at -le $now) {
      return @{ observed_at=[long]$point.observed_at; cents=[int]$point.cents; source='amazon' }
    }
  }
  return 'no-price'
}

function Save-Price([string]$asin, $point) {
  $path = Join-Path $historyDir "$asin.json"
  $points = @(if (Test-Path -LiteralPath $path) { Get-Content -Raw -LiteralPath $path | ConvertFrom-Json })
  if ($points | Where-Object { $_.observed_at -eq $point.observed_at -and $_.source -eq $point.source }) { return $false }
  $points += $point
  ConvertTo-Json -InputObject $points -Compress | Set-Content -LiteralPath $path -Encoding utf8NoBOM
  return $true
}

# Catch up at most two due hourly slices. Leave five minutes for publication.
$deadline = [DateTimeOffset]::UtcNow.AddMinutes(51)
$now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$checked = 0
$saved = 0
$failures = 0
$unmatched = 0
$missing = 0
$noPrice = 0
$reused = 0
for ($slice = 0; $slice -lt 2 -and $progress.due_at -le $now; $slice++) {
  $batch = @(Get-Batch $progress.slot | Sort-Object -Unique)
  $completed = $true
  foreach ($asin in $batch) {
    if ([string]::CompareOrdinal($asin, $progress.after_asin) -le 0) { continue }
    if ([DateTimeOffset]::UtcNow -ge $deadline) { $completed = $false; break }
    try {
      $result = if ($seedIds.Contains($asin)) { Get-SeedPrice $asin } else { Get-EnrolledPrice $asin }
      switch ($result) {
        'unmatched' { $unmatched++ }
        'missing' { $missing++ }
        'no-price' { $noPrice++ }
        default {
          if (Save-Price $asin $result) { $saved++ } else { $reused++ }
        }
      }
    } catch {
      Write-Warning "$asin collection failed: $($_.Exception.Message)"
      $failures++
    }
    $checked++
    $progress.after_asin = $asin
  }
  if ($completed) {
    $progress.slot = ($progress.slot + 1) % $runsPerWeek
    $progress.due_at += 3600
    $progress.after_asin = ''
  }
  $progress | ConvertTo-Json -Compress | Set-Content -LiteralPath $progressPath -Encoding utf8NoBOM
  if (!$completed) { break }
}
$due = [Math]::Max(0, [Math]::Floor(($now - $progress.due_at) / 3600) + 1)
$summary = "$checked checks: $saved saved, $reused already archived, $noPrice without a current price, $missing listings unavailable, $unmatched responses without a matching product, $failures errors. $due overdue hourly slices remain."
Write-Host $summary
if ($env:GITHUB_STEP_SUMMARY) { Add-Content -LiteralPath $env:GITHUB_STEP_SUMMARY -Value $summary }
if ($checked -gt 0 -and $unmatched -eq $checked) { Write-Warning 'Amazon did not return a matching product page for any listing in this batch.' }
if ($failures) { exit 1 }
