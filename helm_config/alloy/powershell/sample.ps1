# This script copies a powershell script to a target and creates a scheduled task to run that powershell script every 15 minutes.
# https://engconf.int.kronos.com/display/COS/%5BImportant%5D:+UltiproIntegration.ServiceConfig.xml+file+is+empty+on+NODE.us.saas
# SCOM alert migration: Alert Name = UltiproIntegration.ServiceConfig.xml file is empty
# https://engjira.int.kronos.com/browse/FS-178669
# Query-DWH is a custom PowerShell module courtesy of Christian Kruger
# contributers: Doug Maguire

$hostname = $env:COMPUTERNAME

# Set the regex based on which utlity system this script is run on
switch -Wildcard ($hostname) {
  "E*" { $r = '^e(?!.*(old|new)$).*$' }
  "N*" { $r = '^n(?!.*(old|new)$).*$' }
  "T*" { $r = '^t(?!.*(old|new)$).*$' }
}

# get a list of UES/UltiPro Auth servers
$servers = Query-DWH "select * from inv.server" | ?{$_.product -match "UltiPro|UES" -and $_.server_function -match "auth" -and $_.server_name -match $r } | ForEach-Object { $_.server_name }

$scriptSourcePath = "C:\Users\usgdmaguire\Documents\file_status.ps1" # FIX find a better spot for this... #Location of the source .prom generation script
$scriptTargetDir = "C:\Program Files\GrafanaLabs\scripts" # Where .prom generation script will be copied to on the target
$scriptTargetPath = "$($scriptTargetDir)\file_status.ps1" # Full path of .prom generation script on the target
$taskName = "GenerateFileStatusPromFile"
$taskDescription = "Runs the file_status.ps1 script every 15 minutes to update Prometheus metrics"
$promDir = "C:\Program Files\GrafanaLabs\Alloy\textfile_inputs" # Where the .prom file is stored on the target

if (-Not (Test-Path $scriptSourcePath)) {
    Write-Error "Source script not found at $($scriptSourcePath). Please check the path."
    exit 1
}

$remoteScript = {
    param ($scriptContent, $scriptTargetPath, $scriptTargetDir, $promDir, $taskName, $taskDescription)

    if (-not (Test-Path $scriptTargetDir)) {
        New-Item -Path $scriptTargetDir -ItemType Directory -Force | Out-Null
        Write-Host "Created directory: $($scriptTargetDir)"
    }
    if (-not (Test-Path $promDir)) {
        New-Item -Path $promDir -ItemType Directory -Force | Out-Null
        Write-Host "Created directory: $($promDir)"
    }

    if (-not (Test-Path $scriptTargetPath)) {
        $scriptContent | Out-File -FilePath $scriptTargetPath -Encoding UTF8 -Force
        Write-Host "Deployed script to: $($scriptTargetPath)"
    } else {
        Write-Host "Script file_status.ps1 already exists."
    }

    # Check if the scheduled task already exists
    $taskExists = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

    # Create scheduled task if not exists
    if ($taskExists) {
        Write-Host "Scheduled task '$($taskName)' already exists."
    } else {
        $action = New-ScheduledTaskAction -Execute "powershell.exe" `
            -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$scriptTargetPath`""

        $trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 15)

        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

        $principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount

        Register-ScheduledTask -TaskName $taskName `
            -Action $action `
            -Trigger $trigger `
            -Settings $settings `
            -Principal $principal `
            -Description $taskDescription `
            -TaskPath "\Flex" `
            -Force

        # Verify the scheduled task was created
        if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
            Write-Host "Scheduled task '$($taskName)' created successfully. Runs every 15 minutes."
        } else {
            Write-Error "Failed to create scheduled task '$($taskName)'."
            exit 1
        }
    }
}

# Add server counting variables
$currentServer = 0
$totalServers = $servers.Count

foreach ($server in $servers) {
    $currentServer++
    Write-Host "`nDeploying to $($server) [$currentServer/$totalServers]"
    
    try {
        $scriptContent = Get-Content $scriptSourcePath -Raw

        Invoke-Command -ComputerName $server `
            -ScriptBlock $remoteScript `
            -ArgumentList $scriptContent, $scriptTargetPath, $scriptTargetDir, $promDir, $taskName, $taskDescription `
            -ErrorAction Stop 
    } catch {
        Write-Error "Failed to deploy to $($server). Error: $($_)"
    }
}
