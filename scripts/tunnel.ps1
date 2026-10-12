# HTTPS-туннель к бэкенду для Mini App.
# .\scripts\tunnel.ps1             - localhost.run через ssh
# .\scripts\tunnel.ps1 -Cloudflare - cloudflared (с VPN может не работать)
# адрес потом прописать в .env как WEBAPP_URL и перезапустить бота
param([switch]$Cloudflare, [int]$Port = 8000)
if ($Cloudflare) {
  & "C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url "http://127.0.0.1:$Port" --no-autoupdate
} else {
  Write-Host "Адрес вида https://xxxx.lhr.life появится ниже; окно не закрывайте." -ForegroundColor Green
  ssh -o StrictHostKeyChecking=no -o ServerAliveInterval=30 -R "80:127.0.0.1:$Port" nokey@localhost.run
}
