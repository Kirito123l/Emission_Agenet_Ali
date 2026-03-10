# Deployment Guide

## GitHub Actions CI/CD Setup

This project uses GitHub Actions for automatic deployment to Alibaba Cloud server.

### Workflow

```
Local Development
    ↓
git push origin main
    ↓
GitHub Actions Triggered
    ↓
SSH to Server (139.196.235.238)
    ↓
Pull Latest Code
    ↓
Install Dependencies
    ↓
Restart Service
    ↓
Verify Deployment
```

### Files Structure

```
.github/
└── workflows/
    └── deploy.yml          # GitHub Actions workflow

deploy/
└── deploy.sh              # Deployment script (executable)
```

### GitHub Secrets Configuration

The following secrets must be configured in GitHub repository settings:

- `SERVER_HOST`: 139.196.235.238
- `SERVER_USER`: root (or your server username)
- `SERVER_SSH_KEY`: Private SSH key for server access

### Automatic Deployment

Every push to `main` branch will automatically:

1. Connect to server via SSH
2. Pull latest code from GitHub
3. Activate Python virtual environment
4. Install/update dependencies
5. Restart systemd service
6. Verify service is running

### Manual Deployment

You can also trigger deployment manually:

1. Go to GitHub repository → Actions tab
2. Select "Deploy to Alibaba Cloud" workflow
3. Click "Run workflow" button

### Server-Side Manual Deployment

If you need to deploy manually on the server:

```bash
ssh root@139.196.235.238
cd /opt/emission_agent
./deploy/deploy.sh
```

### Troubleshooting

**Check deployment logs:**
```bash
# On GitHub: Actions tab → Select workflow run → View logs

# On server:
sudo journalctl -u emission-agent -f
sudo systemctl status emission-agent
```

**If deployment fails:**
```bash
# SSH to server
ssh root@139.196.235.238

# Check service status
sudo systemctl status emission-agent

# View service logs
sudo journalctl -u emission-agent -n 50

# Manually restart service
sudo systemctl restart emission-agent
```

**Rollback to previous version:**
```bash
cd /opt/emission_agent
git log --oneline -10
git reset --hard <commit-hash>
sudo systemctl restart emission-agent
```

### Service Management

```bash
# Start service
sudo systemctl start emission-agent

# Stop service
sudo systemctl stop emission-agent

# Restart service
sudo systemctl restart emission-agent

# Check status
sudo systemctl status emission-agent

# View logs
sudo journalctl -u emission-agent -f
```

### Security Notes

- SSH private key is stored securely in GitHub Secrets
- Server uses SSH key authentication (no password)
- Deployment script runs with sudo privileges for service restart
- All sensitive data (.env files) are excluded from Git

### Next Steps

After setting up CI/CD:

1. Make code changes locally
2. Commit and push to main branch
3. GitHub Actions will automatically deploy
4. Check Actions tab for deployment status
5. Verify service at http://139.196.235.238:8000
