# Deploy Family Portal to AWS (EC2 + SQLite on EBS)
#
# Usage:
#   .\deploy\aws\deploy.ps1 -KeyName "your-ec2-key" [-KeyPath "C:\path\to\key.pem"]
#
param(
    [Parameter(Mandatory = $true)]
    [string]$KeyName,

    [string]$KeyPath = "",

    [string]$StackName = "family-portal",
    [string]$Region = "eu-west-2",
    [string]$InstanceType = "t4g.micro",
    [int]$AppPort = 8090,
    [string]$AllowedSshCidr = "0.0.0.0/0",
    [string]$AllowedAppCidr = "0.0.0.0/0",
    [switch]$CreateElasticIp,
    [switch]$SkipUpload
)

$ErrorActionPreference = "Stop"
$Root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$Cfn = Join-Path $PSScriptRoot "cloudformation.yaml"

$vpcId = aws ec2 describe-vpcs --region $Region --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text
if (-not $vpcId -or $vpcId -eq "None") {
    throw "No default VPC found in $Region. Create one or pass a VPC manually."
}

$eipFlag = if ($CreateElasticIp) { "true" } else { "false" }

Write-Host "==> Deploying CloudFormation stack '$StackName' in $Region (VPC $vpcId)..." -ForegroundColor Cyan
aws cloudformation deploy `
    --template-file $Cfn `
    --stack-name $StackName `
    --region $Region `
    --parameter-overrides `
        KeyName=$KeyName `
        VpcId=$vpcId `
        InstanceType=$InstanceType `
        AppPort=$AppPort `
        AllowedSshCidr=$AllowedSshCidr `
        AllowedAppCidr=$AllowedAppCidr `
        CreateElasticIp=$eipFlag `
    --capabilities CAPABILITY_IAM `
    --no-fail-on-empty-changeset

$outputs = aws cloudformation describe-stacks `
    --stack-name $StackName `
    --region $Region `
    --query "Stacks[0].Outputs" `
    --output json | ConvertFrom-Json

$ip = ($outputs | Where-Object { $_.OutputKey -eq "PublicIp" }).OutputValue
$portalUrl = ($outputs | Where-Object { $_.OutputKey -eq "PortalUrl" }).OutputValue

Write-Host ""
Write-Host "Stack deployed. Public IP: $ip" -ForegroundColor Green
Write-Host "Portal (after upload): $portalUrl" -ForegroundColor Green

if ($SkipUpload) {
    Write-Host "Skipped file upload (-SkipUpload)." -ForegroundColor Yellow
    Write-Host "Next: upload code and run deploy/install-ubuntu.sh on the server."
    exit 0
}

if (-not $KeyPath) {
    Write-Host ""
    Write-Host "No -KeyPath provided. Upload app manually:" -ForegroundColor Yellow
    Write-Host "  scp -i YOUR_KEY.pem -r `"$Root\server`" `"$Root\shared`" `"$Root\deploy`" `"$Root\requirements.txt`" ubuntu@${ip}:/tmp/family-upload/"
    Write-Host "  ssh -i YOUR_KEY.pem ubuntu@$ip 'sudo mkdir -p /opt/family-portal && sudo rsync -a /tmp/family-upload/ /opt/family-portal/ && sudo bash /opt/family-portal/deploy/install-ubuntu.sh'"
    exit 0
}

Write-Host "==> Waiting for SSH on $ip..." -ForegroundColor Cyan
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    $test = ssh -i $KeyPath -o StrictHostKeyChecking=no -o ConnectTimeout=5 "ubuntu@$ip" "test -f /opt/family-portal/.bootstrap && echo ok" 2>$null
    if ($test -match "ok") { $ready = $true; break }
    Start-Sleep -Seconds 10
}
if (-not $ready) {
    Write-Host "Instance not ready for SSH yet. Retry upload manually." -ForegroundColor Yellow
    exit 1
}

Write-Host "==> Uploading project to /opt/family-portal..." -ForegroundColor Cyan
scp -i $KeyPath -o StrictHostKeyChecking=no -r "$Root\server" "$Root\shared" "$Root\deploy" "$Root\requirements.txt" "ubuntu@${ip}:/tmp/family-upload/"

ssh -i $KeyPath -o StrictHostKeyChecking=no "ubuntu@$ip" @"
sudo mkdir -p /opt/family-portal
sudo rsync -a /tmp/family-upload/ /opt/family-portal/
sudo chown -R ubuntu:ubuntu /opt/family-portal
sudo bash /opt/family-portal/deploy/install-ubuntu.sh
"@

Write-Host ""
Write-Host "==============================================" -ForegroundColor Green
Write-Host "  Family Portal is live at $portalUrl"
Write-Host "  Set PUBLIC_URL and GOOGLE_REDIRECT_URI in .env"
Write-Host "  Default logins: luke@example.com / family123"
Write-Host "==============================================" -ForegroundColor Green
