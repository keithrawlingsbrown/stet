# STET Production Deployment Guide

## Table of Contents
- [Prerequisites](#prerequisites)
- [Infrastructure Requirements](#infrastructure-requirements)
- [Security Hardening](#security-hardening)
- [Database Setup](#database-setup)
- [Application Deployment](#application-deployment)
- [TLS/SSL Configuration](#tlsssl-configuration)
- [Monitoring & Alerting](#monitoring--alerting)
- [Backup & Recovery](#backup--recovery)
- [Performance Tuning](#performance-tuning)
- [Operational Procedures](#operational-procedures)
- [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Knowledge
- [ ] Linux system administration
- [ ] Docker/container orchestration
- [ ] PostgreSQL database administration
- [ ] TLS/SSL certificate management
- [ ] Basic networking (DNS, load balancers, firewalls)

### Required Access
- [ ] Cloud provider account (AWS, GCP, Azure, or DigitalOcean)
- [ ] Domain name with DNS control
- [ ] SSL certificate provider access (Let's Encrypt recommended)
- [ ] Git repository access (for deployment artifacts)

---

## Infrastructure Requirements

### Minimum Production Specs

**For Pilot (1-10 tenants):**
```
API Server:
- vCPU: 2
- RAM: 4GB
- Disk: 20GB SSD
- OS: Ubuntu 24.04 LTS

Database Server:
- vCPU: 2
- RAM: 8GB
- Disk: 50GB SSD (NVMe preferred)
- OS: Ubuntu 24.04 LTS

Load Balancer:
- Managed service (e.g., AWS ALB, DigitalOcean LB)
```

**For Production (10-100 tenants):**
```
API Servers (2+ instances):
- vCPU: 4 each
- RAM: 8GB each
- Disk: 20GB SSD each

Database Server:
- vCPU: 4
- RAM: 16GB
- Disk: 100GB SSD (NVMe required)

Database Replica (read-only):
- vCPU: 4
- RAM: 16GB
- Disk: 100GB SSD
```

### Network Architecture
```
Internet
   |
   v
[Load Balancer] (TLS termination)
   |
   +---> [API Server 1] (10.0.1.10)
   |
   +---> [API Server 2] (10.0.1.11)
   |
   v
[PostgreSQL Primary] (10.0.2.10)
   |
   v (replication)
[PostgreSQL Replica] (10.0.2.11)
```

---

## Security Hardening

### 1. Operating System

**Ubuntu 24.04 LTS Setup:**
```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install security updates automatically
sudo apt install unattended-upgrades -y
sudo dpkg-reconfigure -plow unattended-upgrades

# Configure firewall
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 443/tcp   # HTTPS
sudo ufw enable

# Disable root login
sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# Install fail2ban
sudo apt install fail2ban -y
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
```

### 2. Docker Security

**docker-compose.prod.yml:**
```yaml
services:
  postgres:
    image: postgres:15-alpine
    container_name: stet-postgres
    restart: unless-stopped
    environment:
      POSTGRES_DB: stet
      POSTGRES_USER: stet
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./migrations:/docker-entrypoint-initdb.d:ro
    networks:
      - stet_internal
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 4G
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U stet -d stet"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  api:
    image: ghcr.io/keithrawlingsbrown/stet:v1.2.1
    container_name: stet-api
    restart: unless-stopped
    environment:
      DATABASE_URL_FILE: /run/secrets/database_url
      STET_HEARTBEAT_INTERVAL_SECONDS: "60"
      STET_HEARTBEAT_GRACE_MULTIPLIER: "2"
      STET_ENV: "production"
      STET_VERSION: "v1.2.1"
    secrets:
      - database_url
    depends_on:
      postgres:
        condition: service_healthy
    networks:
      - stet_internal
      - stet_public
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
      replicas: 2
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

secrets:
  db_password:
    file: /etc/stet/secrets/db_password
  database_url:
    file: /etc/stet/secrets/database_url

networks:
  stet_internal:
    driver: bridge
    internal: true
  stet_public:
    driver: bridge

volumes:
  postgres_data:
    driver: local
```

### 3. Secrets Management

**Create secrets directory:**
```bash
sudo mkdir -p /etc/stet/secrets
sudo chmod 700 /etc/stet/secrets

# Generate strong database password
openssl rand -base64 32 | sudo tee /etc/stet/secrets/db_password

# Create database URL
echo "postgresql://stet:$(cat /etc/stet/secrets/db_password)@postgres:5432/stet" | \
  sudo tee /etc/stet/secrets/database_url

# Secure permissions
sudo chmod 600 /etc/stet/secrets/*
```

### 4. Network Security

**Restrict database access:**
```bash
# PostgreSQL only accessible from API servers
sudo ufw allow from 10.0.1.10 to any port 5432
sudo ufw allow from 10.0.1.11 to any port 5432
sudo ufw deny 5432
```

---

## Database Setup

### 1. PostgreSQL Configuration

**/etc/postgresql/15/main/postgresql.conf:**
```ini
# Connection settings
listen_addresses = '*'
max_connections = 100
superuser_reserved_connections = 3

# Memory settings
shared_buffers = 2GB
effective_cache_size = 6GB
maintenance_work_mem = 512MB
work_mem = 16MB

# Write-ahead log
wal_level = replica
max_wal_size = 2GB
min_wal_size = 1GB
checkpoint_completion_target = 0.9

# Replication (if using replicas)
hot_standby = on
max_wal_senders = 3
wal_keep_size = 512MB

# Query performance
random_page_cost = 1.1  # For SSD
effective_io_concurrency = 200

# Logging
log_destination = 'stderr'
logging_collector = on
log_directory = '/var/log/postgresql'
log_filename = 'postgresql-%Y-%m-%d.log'
log_rotation_age = 1d
log_rotation_size = 100MB
log_line_prefix = '%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h '
log_checkpoints = on
log_connections = on
log_disconnections = on
log_lock_waits = on
log_statement = 'ddl'
log_min_duration_statement = 1000  # Log slow queries (>1s)
```

### 2. Apply Migrations
```bash
# Clone repository
git clone https://github.com/keithrawlingsbrown/stet.git /opt/stet
cd /opt/stet

# Apply migrations in order
docker compose -f docker-compose.prod.yml exec postgres \
  psql -U stet -d stet -f /docker-entrypoint-initdb.d/001_init.sql

docker compose -f docker-compose.prod.yml exec postgres \
  psql -U stet -d stet -f /docker-entrypoint-initdb.d/002_add_origin.sql

docker compose -f docker-compose.prod.yml exec postgres \
  psql -U stet -d stet -f /docker-entrypoint-initdb.d/003_add_origin_to_corrections.sql
```

### 3. Database Maintenance Jobs

**/etc/cron.d/stet-db-maintenance:**
```cron
# Run VACUUM ANALYZE daily at 2 AM
0 2 * * * postgres /usr/bin/psql -U stet -d stet -c "VACUUM ANALYZE;"

# Backup daily at 3 AM
0 3 * * * root /opt/stet/scripts/backup-database.sh

# Archive old enforcement heartbeats (>90 days) monthly
0 4 1 * * postgres /opt/stet/scripts/archive-heartbeats.sh
```

---

## Application Deployment

### 1. Build and Push Container
```bash
# Build production image
docker build -t ghcr.io/keithrawlingsbrown/stet:v1.2.1 .

# Push to registry
docker push ghcr.io/keithrawlingsbrown/stet:v1.2.1
```

### 2. Deploy with Docker Compose
```bash
# Copy production compose file
cd /opt/stet
cp docker-compose.prod.yml docker-compose.yml

# Start services
docker compose up -d

# Verify health
docker compose ps
docker compose exec api curl http://localhost:8000/health
```

### 3. Systemd Service (Alternative)

**/etc/systemd/system/stet.service:**
```ini
[Unit]
Description=STET API Service
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/stet
ExecStart=/usr/bin/docker compose -f docker-compose.prod.yml up -d
ExecStop=/usr/bin/docker compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```
```bash
sudo systemctl daemon-reload
sudo systemctl enable stet
sudo systemctl start stet
```

---

## TLS/SSL Configuration

### 1. Obtain Let's Encrypt Certificate
```bash
# Install certbot
sudo apt install certbot python3-certbot-nginx -y

# Obtain certificate
sudo certbot certonly --standalone -d api.yourdomain.com

# Certificate location:
# /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem
# /etc/letsencrypt/live/api.yourdomain.com/privkey.pem
```

### 2. Nginx Reverse Proxy

**/etc/nginx/sites-available/stet:**
```nginx
upstream stet_api {
    least_conn;
    server 127.0.0.1:8000 max_fails=3 fail_timeout=30s;
    server 127.0.0.1:8001 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name api.yourdomain.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;

    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;

    client_max_body_size 10M;
    client_body_timeout 60s;

    access_log /var/log/nginx/stet_access.log;
    error_log /var/log/nginx/stet_error.log;

    location / {
        proxy_pass http://stet_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    location /health {
        proxy_pass http://stet_api/health;
        access_log off;
    }
}
```
```bash
sudo ln -s /etc/nginx/sites-available/stet /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

---

## Monitoring & Alerting

### 1. Health Check Monitoring

**/opt/stet/scripts/health-check.sh:**
```bash
#!/bin/bash
set -e

API_URL="https://api.yourdomain.com"
ALERT_EMAIL="ops@yourdomain.com"

# Check API health
if ! curl -sf "$API_URL/health" > /dev/null; then
    echo "ALERT: STET API health check failed at $(date)" | \
        mail -s "STET API Down" "$ALERT_EMAIL"
    exit 1
fi

# Check escalation status
ESCALATION=$(curl -sf "$API_URL/v1/enforcement/escalation" \
    -H "X-Tenant-Id: <monitoring-tenant-id>" | \
    jq -r '.escalation')

if [ "$ESCALATION" = "CRITICAL" ]; then
    echo "ALERT: CRITICAL escalation detected at $(date)" | \
        mail -s "STET Enforcement CRITICAL" "$ALERT_EMAIL"
elif [ "$ESCALATION" = "WARN" ]; then
    echo "WARNING: WARN escalation detected at $(date)" | \
        mail -s "STET Enforcement WARN" "$ALERT_EMAIL"
fi
```

**Cron schedule:**
```cron
# Check health every 5 minutes
*/5 * * * * /opt/stet/scripts/health-check.sh
```

### 2. Log Aggregation

**Configure rsyslog to forward logs:**
```bash
# /etc/rsyslog.d/50-stet.conf
$ModLoad imfile

# Docker logs
$InputFileName /var/lib/docker/containers/*/*-json.log
$InputFileTag docker:
$InputFileStateFile docker-state
$InputFileSeverity info
$InputFileFacility local0
$InputRunFileMonitor

# Forward to centralized logging
*.* @@logs.yourdomain.com:514
```

### 3. Prometheus Metrics (Optional Enhancement)

**Add prometheus_client to requirements.txt**, then instrument endpoints:
```python
from prometheus_client import Counter, Histogram, generate_latest

correction_requests = Counter('stet_correction_requests_total', 'Total correction requests')
fact_requests = Counter('stet_fact_requests_total', 'Total fact requests')
request_duration = Histogram('stet_request_duration_seconds', 'Request duration')

@router.get("/metrics")
async def metrics():
    return Response(content=generate_latest(), media_type="text/plain")
```

---

## Backup & Recovery

### 1. Database Backup Script

**/opt/stet/scripts/backup-database.sh:**
```bash
#!/bin/bash
set -e

BACKUP_DIR="/var/backups/stet"
RETENTION_DAYS=30
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="stet"

mkdir -p "$BACKUP_DIR"

# Create backup
docker compose exec -T postgres pg_dump -U stet -Fc "$DB_NAME" > \
    "$BACKUP_DIR/stet_${DATE}.dump"

# Compress
gzip "$BACKUP_DIR/stet_${DATE}.dump"

# Remove old backups
find "$BACKUP_DIR" -name "stet_*.dump.gz" -mtime +$RETENTION_DAYS -delete

# Upload to S3 (optional)
# aws s3 cp "$BACKUP_DIR/stet_${DATE}.dump.gz" s3://your-bucket/backups/

echo "Backup completed: stet_${DATE}.dump.gz"
```

### 2. Restore Procedure
```bash
#!/bin/bash
set -e

BACKUP_FILE="$1"

if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: $0 <backup-file.dump.gz>"
    exit 1
fi

# Stop API
docker compose stop api

# Restore database
gunzip -c "$BACKUP_FILE" | \
    docker compose exec -T postgres pg_restore -U stet -d stet --clean

# Start API
docker compose start api

echo "Restore completed from: $BACKUP_FILE"
```

### 3. Test Restore Monthly
```bash
# Automated restore test on staging
0 5 15 * * /opt/stet/scripts/test-restore.sh
```

---

## Performance Tuning

### 1. Database Indexes

**Verify critical indexes exist:**
```sql
-- Check corrections table indexes
SELECT indexname, indexdef 
FROM pg_indexes 
WHERE tablename = 'corrections';

-- Expected indexes:
-- corrections_pkey (correction_id)
-- idx_tenant_subject (tenant_id, subject_type, subject_id)
-- uniq_active_per_field (unique on tenant_id, subject_type, subject_id, field_key WHERE status='ACTIVE')
```

### 2. Connection Pooling

**Use PgBouncer for connection pooling:**
```ini
# /etc/pgbouncer/pgbouncer.ini
[databases]
stet = host=localhost port=5432 dbname=stet

[pgbouncer]
listen_addr = 127.0.0.1
listen_port = 6432
auth_type = md5
auth_file = /etc/pgbouncer/userlist.txt
pool_mode = transaction
max_client_conn = 200
default_pool_size = 25
```

Update DATABASE_URL to use port 6432.

### 3. API Rate Limiting

**Add rate limiting middleware:**
```python
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@router.post("/v1/corrections")
@limiter.limit("100/minute")
async def create_correction(...):
    ...
```

---

## Operational Procedures

### 1. Zero-Downtime Deployment
```bash
#!/bin/bash
# /opt/stet/scripts/deploy.sh

NEW_VERSION="$1"

# Pull new image
docker pull ghcr.io/keithrawlingsbrown/stet:$NEW_VERSION

# Update one instance at a time
docker compose stop api_1
docker compose up -d api_1

# Wait for health check
sleep 10
curl -f http://localhost:8000/health || exit 1

# Update second instance
docker compose stop api_2
docker compose up -d api_2

sleep 10
curl -f http://localhost:8001/health || exit 1

echo "Deployment complete: $NEW_VERSION"
```

### 2. Scaling Procedure

**Add more API instances:**
```yaml
# docker-compose.prod.yml
services:
  api:
    deploy:
      replicas: 4  # Scale from 2 to 4
```
```bash
docker compose up -d --scale api=4
```

### 3. Database Migration Procedure
```bash
# 1. Backup database
/opt/stet/scripts/backup-database.sh

# 2. Test migration on staging first
# [staging tests]

# 3. Apply to production during maintenance window
docker compose exec postgres psql -U stet -d stet -f /path/to/new_migration.sql

# 4. Verify schema
docker compose exec postgres psql -U stet -d stet -c "\d corrections"

# 5. Run smoke tests
/opt/stet/scripts/smoke-test.sh
```

---

## Troubleshooting

### Common Issues

**1. High Database CPU Usage**
```sql
-- Find slow queries
SELECT pid, now() - query_start as duration, query
FROM pg_stat_activity
WHERE state = 'active' AND now() - query_start > interval '5 seconds'
ORDER BY duration DESC;

-- Kill long-running query
SELECT pg_terminate_backend(pid);
```

**2. API Container Crashes**
```bash
# Check logs
docker compose logs api --tail=100

# Check resource limits
docker stats stet-api

# Increase memory limit if needed
# Edit docker-compose.yml: memory: 4G
```

**3. Database Connection Exhaustion**
```sql
-- Check active connections
SELECT count(*) FROM pg_stat_activity;

-- Check connection limits
SHOW max_connections;

-- Kill idle connections
SELECT pg_terminate_backend(pid)
FROM pg_stat_activity
WHERE state = 'idle' AND now() - state_change > interval '10 minutes';
```

**4. Escalation False Positives**
```bash
# Check heartbeat configuration
docker compose exec api env | grep STET_HEARTBEAT

# Verify downstream system is reporting
curl -X GET "https://api.yourdomain.com/v1/enforcement/status?system_id=<system-id>" \
  -H "X-Tenant-Id: <tenant-id>"

# Check system clock drift
docker compose exec api date
docker compose exec postgres date
```

### Emergency Procedures

**Database Corruption:**
```bash
# 1. Stop API immediately
docker compose stop api

# 2. Check database integrity
docker compose exec postgres pg_checksums -D /var/lib/postgresql/data

# 3. Restore from last known good backup
/opt/stet/scripts/restore-database.sh /var/backups/stet/latest.dump.gz

# 4. Verify data integrity
/opt/stet/scripts/verify-integrity.sh

# 5. Restart API
docker compose start api
```

**Complete System Failure:**
```bash
# 1. Provision new infrastructure
# 2. Deploy from backup
# 3. Update DNS to new servers
# 4. Verify all tenants operational
```

---

## Checklist for Go-Live

### Pre-Launch

- [ ] Infrastructure provisioned and configured
- [ ] TLS certificates obtained and installed
- [ ] Database initialized with all migrations
- [ ] Secrets securely stored
- [ ] Firewall rules configured
- [ ] Monitoring and alerting configured
- [ ] Backup automation tested
- [ ] Load testing completed (1000+ req/s)
- [ ] Security audit performed
- [ ] Disaster recovery plan documented

### Launch Day

- [ ] Final backup taken
- [ ] DNS updated
- [ ] Health checks passing
- [ ] All endpoints returning 200/201
- [ ] Test tenant verified
- [ ] Monitoring dashboard active
- [ ] On-call rotation confirmed

### Post-Launch (Week 1)

- [ ] Monitor logs daily
- [ ] Verify backups running
- [ ] Check escalation alerts
- [ ] Review performance metrics
- [ ] Gather user feedback
- [ ] Document any issues

---

## Support & Maintenance

**Recommended Maintenance Schedule:**

| Task | Frequency |
|------|-----------|
| Security updates | Weekly |
| Database VACUUM | Daily |
| Backup verification | Weekly |
| Log review | Daily |
| Performance review | Weekly |
| Disaster recovery drill | Quarterly |
| Dependency updates | Monthly |

**Monitoring Dashboard KPIs:**

- API response time (p50, p95, p99)
- Request rate (req/s)
- Error rate (%)
- Database connections (active/idle)
- Disk usage (%)
- Escalation levels (NONE/WARN/CRITICAL count)
- Heartbeat reporting rate

---

## Additional Resources

- [STET Architecture Diagram](ARCHITECTURE.md)
- [PostgreSQL Production Checklist](https://www.postgresql.org/docs/current/runtime-config.html)
- [Docker Security Best Practices](https://docs.docker.com/engine/security/)
- [Let's Encrypt Documentation](https://letsencrypt.org/docs/)
- [FastAPI Deployment](https://fastapi.tiangolo.com/deployment/)

---

**Document Version:** 1.0  
**Last Updated:** December 2025  
**Maintainer:** Keith Rawlings-Brown
