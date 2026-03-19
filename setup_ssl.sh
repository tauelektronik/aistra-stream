#!/usr/bin/env bash
# setup_ssl.sh — Install Nginx + Let's Encrypt for aistra-stream
# Usage: sudo bash setup_ssl.sh yourdomain.com your@email.com
set -e

DOMAIN="${1:?Usage: $0 <domain> <email>}"
EMAIL="${2:?Usage: $0 <domain> <email>}"

echo "==> Installing Nginx + Certbot"
apt-get update -y
apt-get install -y nginx certbot python3-certbot-nginx

echo "==> Copying Nginx config"
cp nginx.conf /etc/nginx/sites-available/aistra-stream
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" /etc/nginx/sites-available/aistra-stream
ln -sf /etc/nginx/sites-available/aistra-stream /etc/nginx/sites-enabled/aistra-stream
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

echo "==> Obtaining SSL certificate"
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect

echo "==> Setting up auto-renewal"
systemctl enable certbot.timer 2>/dev/null || true
(crontab -l 2>/dev/null; echo "0 3 * * * certbot renew --quiet && systemctl reload nginx") | sort -u | crontab -

echo "==> Done! aistra-stream is now available at https://$DOMAIN"
