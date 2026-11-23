# ExamExpert AI — Environment Configuration & Secrets Management Guide
**SJB Institute of Technology, Bengaluru | Autonomous MCA Major Project**  
**Office of the Controller of Examinations (COE)**  

This document details the configuration parameters, cryptographic keys, and credential boundaries defined in `.env`.

---

## 1. Security & Source Control Notice
> [!CAUTION]
> **Never commit `.env` or `examexpert.db` to Git or public repositories.** Both files are strictly ignored by `.gitignore`. Always maintain local environment files and inject secrets using environment variables or secret vaults in production.

---

## 2. Configuration Parameters Reference

| Variable Name | Default / Example Value | Description |
| :--- | :--- | :--- |
| `DATABASE_URL` | `sqlite:///./examexpert.db` | Connection string for SQLite database. Supports relative or absolute path. |
| `SECRET_KEY` | *(Cryptographically random string)* | Used by JWT and cryptographic token generation to sign session tokens. |
| `ALGORITHM` | `HS256` | Cryptographic signature algorithm for JWT tokens. |
| `SESSION_EXPIRY_HOURS` | `12` | Inactivity/session lifespan before requiring re-authentication. |
| `OTP_POLICY` | `ALL_ROLES` | One-Time Password verification policy: `ALL_ROLES`, `EXTERNAL_ONLY`, or `DISABLED`. |
| `ADMIN_PASSWORD` | `Admin@SJBIT2026!` | Initial password seeded for the root COE Admin account upon fresh initialization. |
| `HOD_MCA_PASSWORD` | `Hod@2026!` | Initial password seeded for the MCA HOD account upon fresh initialization. |
| `FACULTY_PASSWORD` | `Faculty@2026!` | Initial password seeded for internal faculty accounts upon fresh initialization. |
| `SMTP_HOST` | `smtp.office365.com` *(Optional)* | Outgoing SMTP mail server hostname for notification emails. |
| `SMTP_PORT` | `587` | Outgoing SMTP server TLS port (typically 587 or 465). |
| `SMTP_USER` | `coe.examination@sjbit.edu.in` | Official COE outgoing mailbox username. |
| `SMTP_PASSWORD` | *(App Password)* | Mailbox application password or OAuth2 client secret. |
| `SMTP_FROM_EMAIL` | `coe@sjbit.edu.in` | Display address appearing in outgoing email `From:` headers. |
| `SMTP_USE_TLS` | `True` | Enforce STARTTLS encryption for all outgoing mail transactions. |

---

## 3. Fallback & Graceful Degradation Behavior

### 3.1 SMTP Unavailable or Unset
If `SMTP_HOST` is left empty or omitted:
1. The system detects the absent mail credentials on startup.
2. The notification service automatically falls back to **In-App Delivery Only**.
3. All allocation alerts, approval notices, and setter appointment orders are routed directly to user inboxes (`/api/notifications/my`).
4. An informational notice banner is displayed on the UI: `"SMTP Email Notice: SMTP is not configured in .env. Notifications are securely delivered to your personal in-app inbox."`
5. Zero unhandled exceptions or error popups are displayed to the user.

### 3.2 Secret Key Fallback
If `SECRET_KEY` is not present in `.env`, the application generates an ephemeral high-entropy random key (`secrets.token_urlsafe(32)`) for development use, logging an alert recommending explicit environment configuration before production deployment.
