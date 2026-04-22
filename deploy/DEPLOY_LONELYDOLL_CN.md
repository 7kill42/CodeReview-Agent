# `lonelydoll.cn` deployment notes

This project already separates the API and UI:

- `api.lonelydoll.cn` -> FastAPI on `127.0.0.1:8000`
- `app.lonelydoll.cn` -> Streamlit on `127.0.0.1:8501`
- `lonelydoll.cn` and `www.lonelydoll.cn` -> redirect to `app.lonelydoll.cn`

## 1. DNS records

Point these records to your server public IP:

- `A` record: `@` -> `<YOUR_SERVER_IP>`
- `A` record: `www` -> `<YOUR_SERVER_IP>`
- `A` record: `api` -> `<YOUR_SERVER_IP>`
- `A` record: `app` -> `<YOUR_SERVER_IP>`

## 2. Prepare Python environment

```bash
cd /root/project/CodeReview-Agent
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If you want a mostly automated Ubuntu setup, you can also use:

```bash
chmod +x deploy/scripts/bootstrap_lonelydoll_cn.sh
SKIP_CERTBOT=1 ./deploy/scripts/bootstrap_lonelydoll_cn.sh
```

Then, after DNS resolves correctly, run:

```bash
CERTBOT_EMAIL=you@example.com ./deploy/scripts/bootstrap_lonelydoll_cn.sh
```

## 3. Prepare runtime services

Start PostgreSQL and Redis first, or adjust the URLs in `.env.production`.

Example:

```bash
docker run -d --name codereview-postgres \
  -p 5432:5432 \
  -e POSTGRES_PASSWORD=postgres \
  -e POSTGRES_DB=codereview \
  postgres:15

docker run -d --name codereview-redis \
  -p 6379:6379 \
  redis:7
```

## 4. Create production env file

```bash
cp deploy/env/production.lonelydoll.cn.example .env.production
```

Fill in at least these values before starting services:

- `ANTHROPIC_API_KEY` or your selected provider key
- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `DASHBOARD_PASSWORD`
- `SECRET_KEY`

## 5. Install systemd services

```bash
cp deploy/systemd/codereview-agent-api.service /etc/systemd/system/
cp deploy/systemd/codereview-agent-ui.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now codereview-agent-api
systemctl enable --now codereview-agent-ui
```

Check status:

```bash
systemctl status codereview-agent-api
systemctl status codereview-agent-ui
```

## 6. Install Nginx site

```bash
cp deploy/nginx/lonelydoll.cn.conf /etc/nginx/sites-available/lonelydoll.cn.conf
ln -s /etc/nginx/sites-available/lonelydoll.cn.conf /etc/nginx/sites-enabled/lonelydoll.cn.conf
nginx -t
systemctl reload nginx
```

## 7. Issue HTTPS certificates

After DNS resolves to your server and Nginx is serving HTTP correctly:

```bash
certbot --nginx -d lonelydoll.cn -d www.lonelydoll.cn -d api.lonelydoll.cn -d app.lonelydoll.cn
```

That will update the Nginx site with TLS and redirects.

The bootstrap script can do the same automatically when `CERTBOT_EMAIL` is set.

## 8. GitHub webhook URL

In GitHub repository settings, configure:

- Payload URL: `https://api.lonelydoll.cn/webhook/github`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: `Pull requests`

## 9. Smoke tests

```bash
curl http://127.0.0.1:8000/health
curl https://api.lonelydoll.cn/health
curl -I https://app.lonelydoll.cn
curl -I https://lonelydoll.cn
```

Expected results:

- `/health` returns JSON with service status
- `https://lonelydoll.cn` redirects to `https://app.lonelydoll.cn`
- Streamlit UI loads from `https://app.lonelydoll.cn`

## 10. Useful URLs after deployment

- UI: `https://app.lonelydoll.cn`
- API docs: `https://api.lonelydoll.cn/docs`
- GitHub webhook: `https://api.lonelydoll.cn/webhook/github`

## 11. Automated bootstrap summary

The helper script at [deploy/scripts/bootstrap_lonelydoll_cn.sh](/root/project/CodeReview-Agent/deploy/scripts/bootstrap_lonelydoll_cn.sh) does all of this:

- installs `python3-venv`, `nginx`, `certbot`, and `docker`
- creates `.venv` and installs Python dependencies
- creates `.env.production` from the template if missing
- starts PostgreSQL and Redis in Docker containers
- installs the `systemd` service units
- installs the Nginx config
- optionally requests HTTPS certificates
