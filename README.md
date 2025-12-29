# 🛠️ Watchforge — Homelab Service Dashboard

Watchforge is a self‑hosted homelab dashboard for monitoring service health, host metrics (via Beszel), and container logs (via Dozzle), with a fully customizable theme system.

It is designed to run cleanly in Docker, be easy to extend, and *not make future‑you hate present‑you*.

---

## ✨ Features

* ✅ Service health checks (HTTP)
* 📊 Host + container metrics via **Beszel**
* 📜 One‑click container logs via **Dozzle**
* 🎨 Per‑user theme system with live editor
* 🔐 Simple admin login
* 🐳 Docker‑first deployment

---

## 🚀 Deployment

### Prerequisites

* Docker + Docker Compose
* (Optional) Beszel for metrics
* (Optional) Dozzle for container logs

---

### 1️⃣ Clone the repository

```bash
git clone https://github.com/iampaulmata/watchforge.git
cd watchforge
```

---

### 2️⃣ Create secrets

Watchforge uses Docker secrets for sensitive values.

```bash
echo "strong-admin-password" | docker secret create dash_admin_password -
echo "beszel@email" | docker secret create beszel_email -
echo "beszel-password" | docker secret create beszel_password -
echo "long-random-encryption-key" | docker secret create app_encryption_key -
```

---

### 3️⃣ docker-compose.yml

Minimal example:

```yaml
services:
  dashboard:
    build: .
    container_name: homelab-dashboard
    ports:
      - "5000:5000"
    environment:
      TZ: America/New_York
      DASH_DB_PATH: /data/dashboard.db
      DASH_WARN_PCT: "80"
      DASH_DANGER_PCT: "95"
      BESZEL_BASE_URL: http://paranor:8090
      DOZZLE_BASE_URL: http://paranor:8080
      DASH_ADMIN_USER: admin
    secrets:
      - dash_admin_password
      - beszel_email
      - beszel_password
      - app_encryption_key
    volumes:
      - dashboard_data:/data
      # Optional: live‑edit templates during development
      - ./app:/app/app
    restart: unless-stopped

volumes:
  dashboard_data:
```

---

### 4️⃣ Build & run

```bash
docker compose build
docker compose up -d
```

Access the UI:

```
http://<host>:5000
```

---

## 🔐 Login

* **Username:** value of `DASH_ADMIN_USER`
* **Password:** value stored in `dash_admin_password` secret

---

## ➕ Adding a New Service

Navigate to:

```
Dashboard → Manage → New Service
```

### Field reference

| Field                | Purpose                             |
| -------------------- | ----------------------------------- |
| **Slug**             | Internal ID (lowercase, no spaces)  |
| **Name**             | Display name                        |
| **URL**              | Click‑through URL                   |
| **Health URL**       | Endpoint returning HTTP 200         |
| **Group**            | Visual grouping label               |
| **Beszel host**      | Host name as shown in Beszel        |
| **Beszel container** | Container name in Beszel            |
| **Dozzle container** | Container name in Dozzle (optional) |
| **Headers**          | JSON headers for health checks      |
| **Enabled**          | Show on dashboard                   |

---

### Example: Immich

```text
Slug: immich
Name: Immich
URL: http://<HOSTNAME_OR_IP_ADDRESS>:<PORT>
Health URL: http://<HOSTNAME_OR_IP_ADDRESS>:<PORT>/api/server/ping
Group: Photos
Beszel host: arborlon
Beszel container: immich_server
Headers: {}
Enabled: ✓
```

---

## 🎨 Themes & Customization

### Accessing Themes

```
Dashboard → Themes
```

Each user can:

* Create private themes
* Live‑edit CSS tokens
* Export / import themes
* Activate a theme instantly

---

### Theme Editor

The editor provides:

* Live preview
* Token‑based CSS editing
* Color pickers for key tokens
* Density (compact) toggle

All tokens map directly to CSS variables.

---

### Theme JSON Format

```json
{
  "schema": "homelab-dashboard-theme@1",
  "name": "Emberforge Dark",
  "author": "@iampaulmata",
  "description": "Dark slate with ember accents",
  "mode": "dark",
  "tokens": {
    "--bg": "#0b0f14",
    "--accent": "#ff7a18",
    "--radius": "18px"
  }
}
```

---

### Starter Themes

Starter themes live in:

```
app/themes/*.json
```

They are automatically seeded on first run and updated on restart.

---

## 🧪 Development Tips

* Mount `./app:/app/app` for live template edits
* Use `docker logs homelab-dashboard` for debugging
* Health endpoints should be fast and unauthenticated

---

## 🧭 Roadmap Ideas

* Multi‑user support
* Role‑based permissions
* Theme marketplace
* Alerting / notifications

---

Built for homelabs that deserve better dashboards ⚔️
