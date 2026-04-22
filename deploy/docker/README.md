# Docker deployment for `lonelydoll.cn`

This setup runs everything with Docker Compose:

- `db` -> PostgreSQL
- `redis` -> Redis
- `api` -> FastAPI on internal port `8000`
- `ui` -> Streamlit on internal port `8501`
- `nginx` -> public HTTP entry on port `80`

## 1. DNS

In your domain provider console, create these A records and point all of them to the same server public IP:

- `@` -> `<YOUR_SERVER_IP>`
- `www` -> `<YOUR_SERVER_IP>`
- `api` -> `<YOUR_SERVER_IP>`
- `app` -> `<YOUR_SERVER_IP>`

## 2. Prepare the env file

```bash
cd /root/project/CodeReview-Agent
```

You can now edit the generated project-level file directly:

- [/.env.docker](/root/project/CodeReview-Agent/.env.docker)

If you want a mixed multi-LLM layout as a reference, also see:

- [deploy/docker/.env.docker.lonelydoll.multi-llm.example](/root/project/CodeReview-Agent/deploy/docker/.env.docker.lonelydoll.multi-llm.example)

Fill in at least:

- `ANTHROPIC_API_KEY` or your chosen provider key
- `GITHUB_TOKEN`
- `GITHUB_WEBHOOK_SECRET`
- `DASHBOARD_PASSWORD`
- `SECRET_KEY`

If you enable per-agent overrides, also fill those component-specific `*_LLM_API_KEY` values.

## 3. Start the stack

```bash
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml up -d --build
```

## 4. Check the containers

```bash
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml ps
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml logs -f api
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml logs -f ui
```

## 5. Verify access

After DNS takes effect:

- `http://app.lonelydoll.cn`
- `http://api.lonelydoll.cn/health`
- `http://api.lonelydoll.cn/docs`

The root domain should redirect:

- `http://lonelydoll.cn` -> `http://app.lonelydoll.cn`

## 6. GitHub webhook

In GitHub repository settings, configure:

- Payload URL: `http://api.lonelydoll.cn/webhook/github`
- Content type: `application/json`
- Secret: same value as `GITHUB_WEBHOOK_SECRET`
- Events: `Pull requests`

## 7. Stop or rebuild

Stop:

```bash
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml down
```

Rebuild after code changes:

```bash
docker compose -f deploy/docker/docker-compose.lonelydoll.cn.yml up -d --build
```

## 8. Notes

- This Docker setup serves HTTP on port `80`.
- If you want HTTPS later, the cleanest next step is to place a TLS reverse proxy in front of this stack or move Nginx certificate handling to the host.
