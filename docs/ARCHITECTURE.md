# STET Architecture Diagram

## System Overview
```mermaid
graph TB
    subgraph "Client Layer"
        A[AI Application]
        B[Admin Dashboard]
        C[Audit Tools]
    end

    subgraph "STET API Layer"
        D[FastAPI Service]
        D --> D1[POST /v1/corrections]
        D --> D2[GET /v1/facts]
        D --> D3[GET /v1/history]
        D --> D4[POST /v1/enforcement/heartbeat]
        D --> D5[GET /v1/enforcement/status]
        D --> D6[GET /v1/enforcement/escalation]
    end

    subgraph "Database Layer"
        E[(PostgreSQL)]
        E --> E1[corrections table]
        E --> E2[idempotency table]
        E --> E3[enforcement_heartbeats table]
    end

    subgraph "Downstream Systems"
        F[Enforcement System A]
        G[Enforcement System B]
        H[Enforcement System N]
    end

    A --> D
    B --> D
    C --> D
    
    D --> E
    
    F -->|Heartbeat| D4
    G -->|Heartbeat| D4
    H -->|Heartbeat| D4

    style D fill:#2374ab
    style E fill:#336791
    style F fill:#52b788
    style G fill:#52b788
    style H fill:#52b788
```

## Correction Lifecycle
```mermaid
sequenceDiagram
    participant App as AI Application
    participant API as STET API
    participant DB as PostgreSQL
    participant Enf as Enforcement System

    App->>API: POST /v1/corrections<br/>{field: "allergy", value: "peanuts"}
    API->>DB: INSERT correction (ACTIVE)
    API->>DB: Check for existing ACTIVE
    DB-->>API: Found existing correction
    API->>DB: UPDATE old correction (SUPERSEDED)
    DB-->>API: ✓
    API-->>App: 201 Created {correction_id, supersedes}
    
    Note over App,Enf: Enforcement Phase
    
    App->>API: GET /v1/facts?subject_id=user_123
    API->>DB: SELECT * WHERE status=ACTIVE<br/>AND permissions allow
    DB-->>API: [corrections]
    API-->>App: {facts: [...]}
    
    App->>Enf: Apply corrections in context
    Enf->>API: POST /v1/enforcement/heartbeat<br/>{system_id, version, origin}
    API->>DB: INSERT enforcement_heartbeat
    DB-->>API: ✓
    API-->>Enf: 201 Created
```

## Trust Verification Flow
```mermaid
graph LR
    subgraph "Enforcement Reporting"
        A[System Reports Heartbeat]
        A --> B[recorded_at timestamp]
        A --> C[system_id]
        A --> D[enforced_correction_version]
        A --> E[origin attestation]
    end

    subgraph "Drift Detection Query-Time"
        F[GET /v1/enforcement/status]
        F --> G{now - reported_at}
        G -->|<= threshold| H[Status: OK]
        G -->|> threshold| I[Status: STALE]
        G -->|no heartbeat| J[Status: MISSING]
    end

    subgraph "Escalation Derivation"
        K[GET /v1/enforcement/escalation]
        K --> L{Evaluate all systems}
        L -->|All OK| M[Escalation: NONE]
        L -->|Any STALE| N[Escalation: WARN]
        L -->|Any MISSING| O[Escalation: CRITICAL]
    end

    B --> F
    C --> F
    D --> F
    
    H --> K
    I --> K
    J --> K

    style H fill:#52b788
    style I fill:#f4a261
    style J fill:#e63946
    style M fill:#52b788
    style N fill:#f4a261
    style O fill:#e63946
```

## Data Model
```mermaid
erDiagram
    corrections ||--o{ corrections : supersedes
    corrections {
        uuid correction_id PK
        uuid tenant_id
        string subject_type
        string subject_id
        string field_key
        jsonb value
        enum class
        enum status
        uuid supersedes FK
        jsonb permissions
        jsonb actor
        string idempotency_key
        jsonb origin
        timestamptz created_at
    }

    idempotency ||--|| corrections : tracks
    idempotency {
        uuid tenant_id PK
        string key PK
        uuid correction_id FK
        string payload_hash
    }

    enforcement_heartbeats {
        uuid heartbeat_id PK
        uuid tenant_id
        string system_id
        timestamptz enforced_correction_version
        jsonb origin
        timestamptz reported_at
    }
```

## Permission-First Architecture
```mermaid
graph TD
    A[GET /v1/facts request] --> B{Check requester_id}
    B --> C[Load permissions from DB]
    C --> D{Filter at query time}
    D -->|readers contains requester| E[Include fact]
    D -->|readers excludes requester| F[Exclude fact]
    E --> G[Return filtered facts]
    F --> G

    style E fill:#52b788
    style F fill:#e63946
    style G fill:#2374ab
```

## Deployment Architecture
```mermaid
graph TB
    subgraph "Production Environment"
        LB[Load Balancer]
        
        subgraph "Application Tier"
            API1[STET API Instance 1]
            API2[STET API Instance 2]
        end
        
        subgraph "Data Tier"
            PG[(PostgreSQL Primary)]
            PGR[(PostgreSQL Replica)]
        end
        
        subgraph "Monitoring"
            M[Metrics/Logs]
        end
    end

    subgraph "External Systems"
        DS1[Downstream System 1]
        DS2[Downstream System 2]
        ALERT[Alert System]
    end

    LB --> API1
    LB --> API2
    
    API1 --> PG
    API2 --> PG
    
    PG -.->|Replication| PGR
    
    API1 --> M
    API2 --> M
    
    DS1 -->|Heartbeats| LB
    DS2 -->|Heartbeats| LB
    
    M -->|Escalation >= WARN| ALERT

    style PG fill:#336791
    style PGR fill:#336791
    style API1 fill:#2374ab
    style API2 fill:#2374ab
    style M fill:#52b788
    style ALERT fill:#f4a261
```

## Key Design Principles

### 1. Immutability
- Corrections are never updated in place
- Superseding creates new records with audit trail
- History is preserved indefinitely

### 2. Permission-First Filtering
- Permissions checked at query time, not post-retrieval
- Prevents RAG bugs from post-filtering
- Database-enforced via WHERE clauses

### 3. Deterministic Derivation
- Drift and escalation computed on-demand
- No background workers or cron jobs
- Results are reproducible at any time

### 4. Origin Attestation
- Every write records service identity
- Forensic-grade attribution
- Tamper-evident audit trail

### 5. Zero Background Jobs
- All state derived from database
- No eventual consistency
- No distributed state management

## Trust Model
```
┌─────────────────────────────────────────────────────────┐
│ STET Trust Guarantee                                    │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  "If enforcement stops, STET knows within 2 minutes"   │
│                                                         │
│  - Heartbeat interval: 60s                             │
│  - Grace multiplier: 2x                                │
│  - Detection threshold: 120s                           │
│  - Query latency: <100ms                               │
│  - Total detection time: ~120s                         │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Scalability Characteristics

| Component | Scaling Strategy |
|-----------|-----------------|
| API Layer | Horizontal (stateless) |
| Database | Vertical + Read Replicas |
| Heartbeats | Time-series partitioning |
| Corrections | Tenant-level sharding |

## Performance Targets

| Operation | Target | Actual |
|-----------|--------|--------|
| POST /v1/corrections | <100ms | ~50ms |
| GET /v1/facts | <50ms | ~20ms |
| GET /v1/enforcement/status | <100ms | ~30ms |
| Full test suite | <1s | 0.42s |
```
