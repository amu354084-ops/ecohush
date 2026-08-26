param(
    [string]$ServerUrl = $env:ERP_SERVER_URL,
    [string]$Username = $env:ERP_BACKUP_USERNAME,
    [string]$Password = $env:ERP_BACKUP_PASSWORD,
    [string]$Destination = $env:ERP_BACKUP_DIRECTORY
)

$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($ServerUrl) -or [string]::IsNullOrWhiteSpace($Username) -or [string]::IsNullOrWhiteSpace($Password)) {
    throw "Set ERP_SERVER_URL, ERP_BACKUP_USERNAME and ERP_BACKUP_PASSWORD."
}
if ([string]::IsNullOrWhiteSpace($Destination)) {
    $Destination = Join-Path $env:ProgramData "ERP-Local\backups"
}

$ServerUrl = $ServerUrl.TrimEnd('/')
New-Item -ItemType Directory -Path $Destination -Force | Out-Null
$loginBody = @{ username = $Username; password = $Password } | ConvertTo-Json
$login = Invoke-RestMethod -Uri "$ServerUrl/api/v1/login" -Method Post -ContentType "application/json" -Body $loginBody
if ([string]::IsNullOrWhiteSpace($login.access_token) -or $login.role -ne "ADMIN") {
    throw "The backup account must have the ADMIN role."
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$temporary = Join-Path $Destination "erp_backup_$stamp.db.tmp"
$target = Join-Path $Destination "erp_backup_$stamp.db"
try {
    Invoke-WebRequest -Uri "$ServerUrl/api/v1/admin/backup/database-download" -Headers @{ Authorization = "Bearer $($login.access_token)" } -OutFile $temporary -UseBasicParsing
    if ((Get-Item $temporary).Length -le 0) {
        throw "The server returned an empty backup."
    }
    Move-Item -Path $temporary -Destination $target
    Get-ChildItem -Path $Destination -Filter "erp_backup_*.db" |
        Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
        Remove-Item -Force
    Write-Output "Backup saved to $target"
}
finally {
    if (Test-Path $temporary) {
        Remove-Item $temporary -Force
    }
}
