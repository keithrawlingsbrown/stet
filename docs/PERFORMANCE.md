# STET Performance Load Testing Suite

## Table of Contents
- [Overview](#overview)
- [Testing Tools](#testing-tools)
- [Performance Targets](#performance-targets)
- [Test Scenarios](#test-scenarios)
- [Locust Load Tests](#locust-load-tests)
- [k6 Performance Tests](#k6-performance-tests)
- [Apache Bench Quick Tests](#apache-bench-quick-tests)
- [Database Performance](#database-performance)
- [Bottleneck Analysis](#bottleneck-analysis)
- [CI/CD Integration](#cicd-integration)
- [Performance Monitoring](#performance-monitoring)
- [Optimization Guide](#optimization-guide)

---

## Overview

Performance testing ensures STET meets production SLAs under realistic load conditions. This guide provides tools, scripts, and procedures for comprehensive load testing.

### Why Performance Test?

- **Capacity Planning:** Determine infrastructure requirements
- **SLA Validation:** Verify response time guarantees
- **Bottleneck Detection:** Identify performance issues before production
- **Regression Prevention:** Catch performance degradation in CI/CD
- **Cost Optimization:** Right-size infrastructure based on actual needs

### Test Environment
```
Load Generator → STET API → PostgreSQL
     (Locust/k6)    (Docker)    (Docker)
```

---

## Testing Tools

### 1. Locust (Recommended - Python-based)

**Pros:**
- Python scripting (easy to extend)
- Web UI for real-time monitoring
- Distributed load generation
- Detailed reports

**Installation:**
```bash
pip install locust
```

### 2. k6 (Alternative - JavaScript-based)

**Pros:**
- CLI-focused, CI/CD friendly
- JavaScript scripting
- Built-in thresholds
- Cloud integration

**Installation:**
```bash
# Ubuntu/Debian
sudo gpg -k
sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt-get update
sudo apt-get install k6
```

### 3. Apache Bench (Quick Tests)

**Pros:**
- Preinstalled on most systems
- Simple CLI
- Quick validation

**Installation:**
```bash
sudo apt install apache2-utils
```

---

## Performance Targets

### Production SLAs

| Endpoint | p50 | p95 | p99 | Throughput |
|----------|-----|-----|-----|------------|
| POST /v1/corrections | <30ms | <100ms | <200ms | 500 req/s |
| GET /v1/facts | <20ms | <50ms | <100ms | 1000 req/s |
| GET /v1/history | <30ms | <80ms | <150ms | 500 req/s |
| POST /v1/enforcement/heartbeat | <20ms | <60ms | <120ms | 200 req/s |
| GET /v1/enforcement/status | <25ms | <75ms | <150ms | 200 req/s |
| GET /v1/enforcement/escalation | <30ms | <100ms | <200ms | 100 req/s |

### Resource Limits

**API Server (2 vCPU, 4GB RAM):**
- Max concurrent connections: 200
- Max requests per second: 1000
- CPU utilization target: <70%
- Memory utilization target: <80%

**Database (2 vCPU, 8GB RAM):**
- Max connections: 100
- Active queries: <50 concurrent
- Query time p99: <50ms
- Connection pool usage: <80%

---

## Test Scenarios

### Scenario 1: Normal Load (Baseline)

**Profile:**
- 100 concurrent users
- 10 req/s per user
- Duration: 10 minutes
- Mix: 50% reads, 40% writes, 10% enforcement

**Purpose:** Establish baseline performance metrics

### Scenario 2: Peak Load

**Profile:**
- 500 concurrent users
- 20 req/s per user
- Duration: 5 minutes
- Spike pattern: gradual ramp-up

**Purpose:** Test capacity under peak conditions

### Scenario 3: Stress Test

**Profile:**
- 1000+ concurrent users
- Increasing load until failure
- Duration: Until system breaks
- Pattern: Linear increase

**Purpose:** Find breaking point and failure modes

### Scenario 4: Soak Test (Endurance)

**Profile:**
- 200 concurrent users
- 5 req/s per user
- Duration: 2 hours
- Pattern: Steady state

**Purpose:** Detect memory leaks and resource exhaustion

### Scenario 5: Spike Test

**Profile:**
- Sudden jump from 100 → 1000 users
- Hold for 2 minutes
- Drop back to 100
- Duration: 15 minutes

**Purpose:** Test elasticity and recovery

---

## Locust Load Tests

### Base Locust Configuration

**tests/performance/locustfile.py:**
```python
from locust import HttpUser, task, between, events
import json
import uuid
from datetime import datetime, timezone

# Test data
TENANT_ID = "00000000-0000-0000-0000-000000000001"
TEST_SUBJECTS = [f"user_{i}" for i in range(1000)]
TEST_SYSTEMS = [f"system_{i}" for i in range(50)]

class STETUser(HttpUser):
    wait_time = between(0.1, 0.5)  # 100-500ms between requests
    
    def on_start(self):
        """Called when a simulated user starts"""
        self.tenant_id = TENANT_ID
        self.headers = {
            "X-Tenant-Id": self.tenant_id,
            "Content-Type": "application/json"
        }
    
    @task(5)  # Weight: 50%
    def get_facts(self):
        """Read facts for a random subject"""
        subject_id = self.select_random_subject()
        with self.client.get(
            f"/v1/facts?subject_type=user&subject_id={subject_id}&requester_id=bot:test",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")
    
    @task(4)  # Weight: 40%
    def create_correction(self):
        """Create a new correction"""
        subject_id = self.select_random_subject()
        payload = {
            "subject": {"type": "user", "id": subject_id},
            "field_key": f"test.field_{uuid.uuid4().hex[:8]}",
            "value": {"test": "value", "timestamp": datetime.now(timezone.utc).isoformat()},
            "class": "FACT",
            "permissions": {"readers": ["bot:test"]},
            "actor": {"type": "system", "id": "load-test"},
            "idempotency_key": str(uuid.uuid4())
        }
        
        with self.client.post(
            "/v1/corrections",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")
    
    @task(1)  # Weight: 10%
    def enforcement_heartbeat(self):
        """Send enforcement heartbeat"""
        system_id = self.select_random_system()
        payload = {
            "system_id": system_id,
            "enforced_correction_version": datetime.now(timezone.utc).isoformat()
        }
        
        with self.client.post(
            "/v1/enforcement/heartbeat",
            json=payload,
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 201:
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")
    
    @task(1)  # Weight: 10%
    def get_enforcement_status(self):
        """Check enforcement status"""
        with self.client.get(
            "/v1/enforcement/status",
            headers=self.headers,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Got status {response.status_code}")
    
    def select_random_subject(self):
        """Select random test subject"""
        import random
        return random.choice(TEST_SUBJECTS)
    
    def select_random_system(self):
        """Select random test system"""
        import random
        return random.choice(TEST_SYSTEMS)

# Custom metrics collection
@events.request.add_listener
def on_request(request_type, name, response_time, response_length, exception, context, **kwargs):
    """Custom request handler for additional metrics"""
    if exception:
        print(f"Request failed: {name} - {exception}")

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Initialize test"""
    print(f"Load test starting against {environment.host}")
    print(f"Target: {TENANT_ID}")

@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Cleanup after test"""
    print("Load test complete")
    print(f"Total requests: {environment.stats.total.num_requests}")
    print(f"Failures: {environment.stats.total.num_failures}")
```

### Run Locust Tests

**1. Basic Test (Web UI):**
```bash
# Start Locust with web UI
locust -f tests/performance/locustfile.py --host=http://127.0.0.1:8000

# Open browser: http://localhost:8089
# Configure: 100 users, 10 spawn rate
```

**2. Headless Test (CI/CD):**
```bash
# Run without web UI
locust -f tests/performance/locustfile.py \
    --host=http://127.0.0.1:8000 \
    --users=500 \
    --spawn-rate=10 \
    --run-time=5m \
    --headless \
    --html=reports/locust-report.html \
    --csv=reports/locust-stats
```

**3. Distributed Load Test:**
```bash
# Master node
locust -f tests/performance/locustfile.py \
    --master \
    --expect-workers=3

# Worker nodes (on separate machines)
locust -f tests/performance/locustfile.py \
    --worker \
    --master-host=<master-ip>
```

### Advanced Locust: Custom Shape

**tests/performance/spike_test.py:**
```python
from locust import LoadTestShape

class SpikeLoadShape(LoadTestShape):
    """
    Spike load pattern:
    - Start: 100 users
    - Spike to 1000 users at 2 min
    - Hold for 2 minutes
    - Drop to 100 users
    - Total: 10 minutes
    """
    
    stages = [
        {"duration": 120, "users": 100, "spawn_rate": 10},   # Baseline
        {"duration": 240, "users": 1000, "spawn_rate": 100}, # Spike
        {"duration": 360, "users": 100, "spawn_rate": 50},   # Recovery
        {"duration": 600, "users": 100, "spawn_rate": 10},   # Steady
    ]
    
    def tick(self):
        run_time = self.get_run_time()
        
        for stage in self.stages:
            if run_time < stage["duration"]:
                return (stage["users"], stage["spawn_rate"])
        
        return None  # Test complete
```

---

## k6 Performance Tests

### Basic k6 Script

**tests/performance/k6-test.js:**
```javascript
import http from 'k6/http';
import { check, sleep } from 'k6';
import { Rate, Trend } from 'k6/metrics';

// Custom metrics
const errorRate = new Rate('errors');
const correctionLatency = new Trend('correction_latency');
const factsLatency = new Trend('facts_latency');

// Configuration
export const options = {
  stages: [
    { duration: '2m', target: 100 },  // Ramp-up
    { duration: '5m', target: 100 },  // Steady state
    { duration: '2m', target: 200 },  // Peak
    { duration: '2m', target: 0 },    // Ramp-down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<100', 'p(99)<200'],
    'errors': ['rate<0.01'],  // <1% errors
    'http_req_failed': ['rate<0.01'],
  },
};

const BASE_URL = __ENV.API_URL || 'http://localhost:8000';
const TENANT_ID = '00000000-0000-0000-0000-000000000001';

export default function () {
  const headers = {
    'X-Tenant-Id': TENANT_ID,
    'Content-Type': 'application/json',
  };

  // 50% GET /v1/facts
  if (Math.random() < 0.5) {
    const subjectId = `user_${Math.floor(Math.random() * 1000)}`;
    const response = http.get(
      `${BASE_URL}/v1/facts?subject_type=user&subject_id=${subjectId}&requester_id=bot:test`,
      { headers }
    );
    
    const success = check(response, {
      'facts status is 200': (r) => r.status === 200,
      'facts response time < 50ms': (r) => r.timings.duration < 50,
    });
    
    factsLatency.add(response.timings.duration);
    errorRate.add(!success);
  } 
  // 40% POST /v1/corrections
  else if (Math.random() < 0.8) {
    const payload = JSON.stringify({
      subject: { type: 'user', id: `user_${Math.floor(Math.random() * 1000)}` },
      field_key: `test.field_${Date.now()}`,
      value: { test: 'value' },
      class: 'FACT',
      permissions: { readers: ['bot:test'] },
      actor: { type: 'system', id: 'k6-load-test' },
      idempotency_key: `${Date.now()}-${Math.random()}`,
    });
    
    const response = http.post(
      `${BASE_URL}/v1/corrections`,
      payload,
      { headers }
    );
    
    const success = check(response, {
      'correction status is 201': (r) => r.status === 201,
      'correction response time < 100ms': (r) => r.timings.duration < 100,
    });
    
    correctionLatency.add(response.timings.duration);
    errorRate.add(!success);
  }
  // 10% POST /v1/enforcement/heartbeat
  else {
    const payload = JSON.stringify({
      system_id: `system_${Math.floor(Math.random() * 50)}`,
      enforced_correction_version: new Date().toISOString(),
    });
    
    const response = http.post(
      `${BASE_URL}/v1/enforcement/heartbeat`,
      payload,
      { headers }
    );
    
    check(response, {
      'heartbeat status is 201': (r) => r.status === 201,
    });
  }

  sleep(0.1);  // 100ms think time
}

// Setup function - runs once
export function setup() {
  console.log('Starting k6 load test');
  console.log(`Target: ${BASE_URL}`);
  return { startTime: Date.now() };
}

// Teardown function - runs once at end
export function teardown(data) {
  const duration = (Date.now() - data.startTime) / 1000;
  console.log(`Test completed in ${duration}s`);
}
```

### Run k6 Tests
```bash
# Basic run
k6 run tests/performance/k6-test.js

# With environment variable
k6 run --env API_URL=https://api.yourdomain.com tests/performance/k6-test.js

# Output results to JSON
k6 run --out json=reports/k6-results.json tests/performance/k6-test.js

# Cloud output (k6 Cloud account required)
k6 run --out cloud tests/performance/k6-test.js
```

### k6 Thresholds

**tests/performance/k6-thresholds.js:**
```javascript
export const options = {
  thresholds: {
    // HTTP errors should be less than 1%
    'http_req_failed': ['rate<0.01'],
    
    // 95% of requests should be below 100ms
    'http_req_duration': ['p(95)<100'],
    
    // 99% of requests should be below 200ms
    'http_req_duration{name:corrections}': ['p(99)<200'],
    
    // Specific endpoint thresholds
    'http_req_duration{endpoint:/v1/facts}': ['p(95)<50'],
    'http_req_duration{endpoint:/v1/corrections}': ['p(95)<100'],
    
    // Minimum throughput
    'http_reqs': ['rate>100'], // At least 100 req/s
  },
  
  // Abort test if thresholds breached
  abortOnFail: true,
};
```

---

## Apache Bench Quick Tests

### Basic Benchmarks
```bash
# Test GET /v1/facts (1000 requests, 10 concurrent)
ab -n 1000 -c 10 \
   -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
   "http://127.0.0.1:8000/v1/facts?subject_type=user&subject_id=test&requester_id=bot:test"

# Test POST /v1/corrections (100 requests, 5 concurrent)
ab -n 100 -c 5 \
   -p tests/performance/correction-payload.json \
   -T "application/json" \
   -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
   "http://127.0.0.1:8000/v1/corrections"
```

### Payload File

**tests/performance/correction-payload.json:**
```json
{
  "subject": {"type": "user", "id": "bench_test"},
  "field_key": "test.benchmark",
  "value": {"test": "ab"},
  "class": "FACT",
  "permissions": {"readers": ["bot:test"]},
  "actor": {"type": "system", "id": "ab"},
  "idempotency_key": "ab-test-key"
}
```

### Interpret Results
```
Requests per second:    234.56 [#/sec] (mean)
Time per request:       42.631 [ms] (mean)
Time per request:       4.263 [ms] (mean, across all concurrent requests)

Percentage of requests served within a certain time (ms)
  50%     38
  66%     40
  75%     42
  80%     44
  90%     50
  95%     58
  98%     70
  99%     85
 100%    120 (longest request)
```

**Good:** p95 < 100ms, p99 < 200ms  
**Needs investigation:** p95 > 200ms

---

## Database Performance

### PostgreSQL Slow Query Log

**Enable slow query logging:**
```sql
-- Log queries slower than 100ms
ALTER SYSTEM SET log_min_duration_statement = 100;
SELECT pg_reload_conf();
```

### Monitor Active Queries
```bash
#!/bin/bash
# tests/performance/monitor-queries.sh

watch -n 1 'docker compose exec postgres psql -U stet -d stet -c "
SELECT 
    pid,
    now() - query_start as duration,
    state,
    substring(query, 1, 50) as query
FROM pg_stat_activity
WHERE state = '\''active'\''
  AND query NOT LIKE '\''%pg_stat_activity%'\''
ORDER BY duration DESC
LIMIT 10;
"'
```

### Database Metrics During Load Test
```bash
#!/bin/bash
# tests/performance/db-metrics.sh

while true; do
    echo "=== $(date) ==="
    
    # Active connections
    echo "Active connections:"
    docker compose exec postgres psql -U stet -d stet -t -c \
        "SELECT count(*) FROM pg_stat_activity WHERE state = 'active';"
    
    # Cache hit ratio
    echo "Cache hit ratio:"
    docker compose exec postgres psql -U stet -d stet -t -c \
        "SELECT 
            sum(heap_blks_hit) / (sum(heap_blks_hit) + sum(heap_blks_read)) * 100 
         FROM pg_statio_user_tables;"
    
    # Transaction rate
    echo "Transactions/sec:"
    docker compose exec postgres psql -U stet -d stet -t -c \
        "SELECT xact_commit + xact_rollback FROM pg_stat_database WHERE datname='stet';"
    
    sleep 5
done
```

---

## Bottleneck Analysis

### API Performance Profiling

**Add profiling middleware (development only):**
```python
import time
from fastapi import Request

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)
    
    # Log slow requests
    if process_time > 0.1:  # >100ms
        print(f"SLOW: {request.method} {request.url.path} took {process_time:.3f}s")
    
    return response
```

### System Resource Monitoring
```bash
#!/bin/bash
# tests/performance/monitor-resources.sh

# Monitor CPU, memory, disk I/O during load test
dstat --time --cpu --mem --disk --net --output reports/dstat-$(date +%Y%m%d-%H%M%S).csv 1
```

### Docker Stats
```bash
# Real-time container stats
docker stats stet-api stet-postgres

# Export to file
docker stats --no-stream stet-api stet-postgres > reports/docker-stats.txt
```

---

## CI/CD Integration

### GitHub Actions Workflow

**.github/workflows/performance-test.yml:**
```yaml
name: Performance Tests

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM

jobs:
  performance-test:
    runs-on: ubuntu-latest
    
    services:
      postgres:
        image: postgres:15-alpine
        env:
          POSTGRES_DB: stet
          POSTGRES_USER: stet
          POSTGRES_PASSWORD: stet_test
        ports:
          - 5432:5432
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
    
    steps:
    - uses: actions/checkout@v3
    
    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.11'
    
    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install locust
    
    - name: Start API
      run: |
        export DATABASE_URL="postgresql://stet:stet_test@localhost:5432/stet"
        uvicorn app.main:app --host 0.0.0.0 --port 8000 &
        sleep 5
    
    - name: Run load test
      run: |
        locust -f tests/performance/locustfile.py \
          --host=http://localhost:8000 \
          --users=100 \
          --spawn-rate=10 \
          --run-time=2m \
          --headless \
          --html=reports/locust-report.html \
          --csv=reports/locust-stats
    
    - name: Check performance thresholds
      run: |
        python tests/performance/check-thresholds.py reports/locust-stats_stats.csv
    
    - name: Upload results
      uses: actions/upload-artifact@v3
      if: always()
      with:
        name: performance-reports
        path: reports/
```

### Threshold Checker

**tests/performance/check-thresholds.py:**
```python
import csv
import sys

THRESHOLDS = {
    'Median': 50,   # ms
    '95%ile': 100,  # ms
    '99%ile': 200,  # ms
}

def check_thresholds(stats_file):
    with open(stats_file, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Name'] == 'Aggregated':
                median = float(row['Median Response Time'])
                p95 = float(row['95%ile'])
                p99 = float(row['99%ile'])
                
                print(f"Performance Metrics:")
                print(f"  Median: {median}ms (threshold: {THRESHOLDS['Median']}ms)")
                print(f"  95%ile: {p95}ms (threshold: {THRESHOLDS['95%ile']}ms)")
                print(f"  99%ile: {p99}ms (threshold: {THRESHOLDS['99%ile']}ms)")
                
                if median > THRESHOLDS['Median']:
                    print(f"❌ FAILED: Median {median}ms exceeds {THRESHOLDS['Median']}ms")
                    sys.exit(1)
                
                if p95 > THRESHOLDS['95%ile']:
                    print(f"❌ FAILED: 95%ile {p95}ms exceeds {THRESHOLDS['95%ile']}ms")
                    sys.exit(1)
                
                if p99 > THRESHOLDS['99%ile']:
                    print(f"❌ FAILED: 99%ile {p99}ms exceeds {THRESHOLDS['99%ile']}ms")
                    sys.exit(1)
                
                print("✓ All thresholds passed")
                return 0

if __name__ == '__main__':
    sys.exit(check_thresholds(sys.argv[1]))
```

---

## Performance Monitoring

### Grafana Dashboard (Optional)

**docker-compose.monitoring.yml:**
```yaml
services:
  prometheus:
    image: prom/prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    environment:
      GF_SECURITY_ADMIN_PASSWORD: admin
    volumes:
      - grafana_data:/var/lib/grafana

volumes:
  prometheus_data:
  grafana_data:
```

---

## Optimization Guide

### If p95 > 100ms:

1. **Check database indexes:**
```sql
   EXPLAIN ANALYZE SELECT * FROM corrections WHERE tenant_id = '...' AND status = 'ACTIVE';
```

2. **Enable connection pooling (PgBouncer)**
3. **Increase API workers:**
```bash
   uvicorn app.main:app --workers 4
```

### If p99 > 200ms:

1. **Check for slow queries in PostgreSQL logs**
2. **Analyze query plans**
3. **Consider read replicas for read-heavy loads**
4. **Implement caching (Redis) for frequently accessed data**

### If throughput < 500 req/s:

1. **Scale API horizontally (more instances)**
2. **Optimize database connection pool size**
3. **Profile Python code with cProfile**
4. **Consider async optimizations**

---

## Example: Complete Performance Test

**tests/performance/run-full-test.sh:**
```bash
#!/bin/bash
set -e

echo "=== STET Performance Test Suite ==="
echo "Starting at $(date)"

# Ensure services are running
docker compose up -d
sleep 10

# Create reports directory
mkdir -p reports

# 1. Baseline test (Apache Bench)
echo "Running baseline test..."
ab -n 1000 -c 10 \
   -H "X-Tenant-Id: 00000000-0000-0000-0000-000000000001" \
   "http://127.0.0.1:8000/health" \
   > reports/ab-baseline.txt

# 2. Load test (Locust)
echo "Running load test (5 minutes)..."
locust -f tests/performance/locustfile.py \
    --host=http://127.0.0.1:8000 \
    --users=200 \
    --spawn-rate=20 \
    --run-time=5m \
    --headless \
    --html=reports/locust-report.html \
    --csv=reports/locust-stats

# 3. Check thresholds
echo "Checking performance thresholds..."
python tests/performance/check-thresholds.py reports/locust-stats_stats.csv

# 4. Database stats
echo "Collecting database statistics..."
docker compose exec postgres psql -U stet -d stet -c "\
    SELECT schemaname, tablename, 
           pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
           n_tup_ins, n_tup_upd, n_tup_del
    FROM pg_stat_user_tables
    ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;" \
    > reports/db-stats.txt

echo "=== Test Complete ==="
echo "Reports available in ./reports/"
echo "  - locust-report.html (detailed metrics)"
echo "  - locust-stats_stats.csv (raw data)"
echo "  - ab-baseline.txt (baseline performance)"
echo "  - db-stats.txt (database statistics)"
```

**Run:**
```bash
chmod +x tests/performance/run-full-test.sh
./tests/performance/run-full-test.sh
```

---

## Performance Test Checklist

### Before Testing

- [ ] Test environment matches production specs
- [ ] Database has realistic data volume
- [ ] Monitoring tools are running
- [ ] Baseline metrics captured
- [ ] Test duration planned (avoid short tests)

### During Testing

- [ ] Monitor CPU, memory, disk I/O
- [ ] Watch for errors in logs
- [ ] Track database connection pool usage
- [ ] Observe response time distribution
- [ ] Check for resource exhaustion

### After Testing

- [ ] Analyze reports and identify bottlenecks
- [ ] Compare against SLA targets
- [ ] Document findings
- [ ] Create optimization tickets
- [ ] Archive test results

---

## Additional Resources

- [Locust Documentation](https://docs.locust.io/)
- [k6 Documentation](https://k6.io/docs/)
- [PostgreSQL Performance Tuning](https://wiki.postgresql.org/wiki/Performance_Optimization)
- [FastAPI Performance](https://fastapi.tiangolo.com/deployment/concepts/)

---

**Document Version:** 1.0  
**Last Updated:** December 2025  
**Maintainer:** Keith Rawlings-Brown
