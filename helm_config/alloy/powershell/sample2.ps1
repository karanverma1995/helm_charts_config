
# This script checks for the existence of a current alloy config on a target and adds/replaces it if necessary
# https://engjira.int.kronos.com/browse/FS-178669
# Query-DWH is a custom PowerShell module courtesy of Christian Kruger
# contributers: Doug Maguire

$hostname = $env:COMPUTERNAME

Write-Output "Running on $($hostname)`n"

# Set the regex based on which system this script is run on
switch -Wildcard ($hostname) {
  "E*" { $r = '^e(?!.*(old|new)$).*$' }
  "N*" { $r = '^n(?!.*(old|new)$).*$' }
  "T*" { $r = '^t(?!.*(old|new)$).*$' }
}

# Collect the list of servers from DWH
$servers = Query-DWH "select server_name,data_center,site,pod,server_function,product from inv.server" | 
    ?{$_.product -match "UltiPro|UES" -and $_.server_function -match "auth|dpm|integration|hub" -and $_.server_name -match $r }

$targetPath = "C:\Program Files\GrafanaLabs\Alloy\config\flex.alloy"
$templateBasePath = "C:\users\usgdmaguire\Documents" # find a better location for this
$serviceName = "Alloy"

$currentServer = 0
$totalServers = $servers.Count

foreach ($server in $servers) {
  
  $currentServer++
  Write-Host "Processing server: $($server.server_name) [$currentServer/$totalServers]"

  # Select the appropriate template based on server_function
  if ($server.server_function -eq "auth") {
    $sourceTemplate = "$templateBasePath\flex-auth.alloy"
    Write-Host "Using auth-specific template for $($server.server_name)"
  } else {
    $sourceTemplate = "$templateBasePath\flex.alloy"
    Write-Host "Using standard template for $($server.server_name)"
  }

  $sourceFile = "$templateBasePath\build_files\flex.alloy.$($server.server_name)" # find a better location for this
  $remoteTargetFile = "\\$($server.server_name)\$($targetPath -replace ':', '$')"
  
  $replacements = @{
    '{{ vars.site }}'      = $server.site
    '{{ vars.pod }}'       = $server.pod
    '{{ vars.datacenter }}' = $server.data_center
    '{{ vars.function }}'  = $server.server_function
    '{{ vars.app }}'       = $server.product
  }
  
  # Check if the template file exists
  if (-not (Test-Path -Path $sourceTemplate)) {
    Write-Host "ERROR: Template file not found: $sourceTemplate" -ForegroundColor Red
    continue
  }
  
  $buildFile = Get-Content $sourceTemplate -Raw

  foreach ($key in $replacements.Keys) {
    $buildFile = $buildFile.Replace($key, $replacements[$key])
  }
  
  # Ensure build_files directory exists
  $buildFilesDir = "$templateBasePath\build_files"
  if (-not (Test-Path -Path $buildFilesDir)) {
    New-Item -Path $buildFilesDir -ItemType Directory -Force | Out-Null
  }
  
  $buildFile | Set-Content $sourceFile

  $fileExists = Test-Path -Path $remoteTargetFile
  
  if ($fileExists) {
    $sourceHash = (Get-FileHash -Path $sourceFile -Algorithm SHA256).Hash
    $targetHash = (Get-FileHash -Path $remoteTargetFile -Algorithm SHA256).Hash

    if ($sourceHash -eq $targetHash) {
      Write-Host "File on $($server.server_name) matches source. No action needed`n"
      Remove-Item -path $sourceFile
      continue
    } else {
      Write-Host "File on $($server.server_name) differs from source. Overwriting"
    }
  } else {
    Write-Host "File missing on $($server.server_name). Copying source to target"
  }

  Copy-Item -Path $sourceFile -Destination $remoteTargetFile -Force

  if (Test-Path $remoteTargetFile) {
    Write-Host "File copied to $($server.server_name)."
  } else {
    Write-Host "Failed to copy file to $($server.server_name)" -ForegroundColor Red
  }
  
  try {
    Invoke-Command -ComputerName $server.server_name -ScriptBlock {
      param($service)
      Restart-Service -Name $service -Force
    } -ArgumentList $serviceName
    Write-Host "Service '$($serviceName)' restarted on $($server.server_name).`n"
  } catch { 
    Write-Host "Failed to restart service on $($server.server_name). Error: $($_)`n" -ForegroundColor Red
  }
}
