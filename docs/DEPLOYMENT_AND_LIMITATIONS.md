# ExamExpert AI — Production Deployment, Known Limitations & Policy Roadmap
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document outlines deployment configurations, technical boundaries, and policy values awaiting formal Controller of Examinations (COE) committee confirmation.

---

## 1. Production Deployment Architecture

For an institutional on-premise or cloud production environment, ExamExpert AI should be deployed behind an Nginx reverse proxy using Gunicorn with Uvicorn worker processes:

```
                  ┌─────────────────────────────────────────┐
                  │          HTTPS Client (Browser)         │
                  └────────────────────┬────────────────────┘
                                       │ Port 443 (SSL/TLS)
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │       Nginx Reverse Proxy & Static      │
                  └────────────────────┬────────────────────┘
                                       │ Unix Socket / Port 8000
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │       Gunicorn (ASGI Process Manager)   │
                  │   ├── Uvicorn Worker 1                  │
                  │   ├── Uvicorn Worker 2                  │
                  │   └── Uvicorn Worker 3                  │
                  └────────────────────┬────────────────────┘
                                       │
                                       ▼
                  ┌─────────────────────────────────────────┐
                  │           SQLite / PostgreSQL           │
                  └─────────────────────────────────────────┘
```

### Sample Systemd Service File (`/etc/systemd/system/examexpert.service`)
```ini
[Unit]
Description=ExamExpert AI — SJBIT Examination Service
After=network.target

[Service]
User=coe_service
WorkingDirectory=/opt/ExamExpert-AI
Environment="PATH=/opt/ExamExpert-AI/.venv/bin"
ExecStart=/opt/ExamExpert-AI/.venv/bin/gunicorn -w 4 -k uvicorn.workers.UvicornWorker backend.app.main:app --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## 2. Known Limitations & Architectural Boundaries

1. **Database Concurrency (SQLite Lock Contention):**
   - SQLite provides outstanding read throughput and zero configuration. However, concurrent write transactions operate under table-level or database-level write locks (`busy_timeout`).
   - For institutional deployments with more than 50 simultaneous departmental HODs submitting approvals in the same second, migrating connection strings to PostgreSQL (`postgresql://...`) via SQLAlchemy requires zero code changes.
2. **Asynchronous SMTP Delivery:**
   - When SMTP is enabled, slow external SMTP relay servers can introduce minor latency to the approval submission request. Deploying a background Celery / Redis task queue is recommended for campus-scale mail distribution exceeding 1,000 daily notices.
3. **Multi-Institution Single Roster:**
   - External faculty entries currently share a single unified external roster. Cross-institutional federated Single Sign-On (SAML 2.0 / Shibboleth) can be integrated in future phases.

---

## 3. Statutory Policy Values Awaiting COE Committee Confirmation

The following policy defaults are implemented dynamically in `eligibility_rules` and can be adjusted through the **⚙️ Settings** tab upon formal COE directive:

| Policy Parameter | Current Implementation Default | Pending COE Decision / Alternative Options |
| :--- | :---: | :--- |
| **Minimum Teaching Experience** | `3.0 Years` | Some Autonomous boards permit 2.0 years for core subjects if faculty holds industrial expertise. |
| **PhD Fast-Track Exemption** | `1.0 Year` | Evaluate whether newly appointed PhD holders should complete 1 full semester of orientation before setter nomination. |
| **Maximum Workload Ceiling** | `2 Papers / Cycle` | Option to raise to 3 papers for specialized elective courses with acute faculty shortages. |
| **External Setter Parity Ratio** | `50:50 (1 Internal : 1 External)` | Autonomous Board may authorize 100% external setting for select final-semester capstone courses. |
| **Subject Rotation Cooldown** | `1 Semester` | Mandates that a setter who handled a course cannot set the same paper again for at least 1 subsequent examination cycle. |
