# EduForge — Security and Operations

## Encryption and Data Protection Bras
- All data in transit between client applications and EduForge APIs is encrypted using TLS 1.3.
- Data at rest in production databases is encrypted with AES-256.
- Backups are encrypted with AES-256 before being written to object storage.
- Encryption keys are rotated every 90 days using a managed key management service.

## Certifications and Compliance
- EduForge maintains SOC 2 Type II certification, audited annually by an independent third party.
- The platform processes personal data in accordance with GDPR for users located in the European Union.
- Student health records uploaded by university partners are handled under HIPAA requirements.
- Data residency for EU customers is maintained in the eu-central-1 region.

## Data Retention and Deletion
- Active course content is retained for the duration of the university contract plus 180 days.
- User activity logs are retained for 365 days.
- Deleted user accounts are purged from production systems within 30 days.
- Backup copies of deleted data expire within 90 days.

## Backup and Recovery
- Full database backups are taken daily at 02:00 UTC.
- Incremental backups run every 6 hours.
- Backup restoration tests are performed quarterly.
- The recovery point objective is 6 hours and the recovery time objective is 12 hours.

## Incident Response
- Confirmed security incidents are reported to affected university administrators within 72 hours.
- Critical severity incidents trigger internal notification within 1 hour of detection.
- A post-incident report is delivered to affected customers within 14 days.
- The incident response team conducts a tabletop exercise every 6 months.

## Access Control
- Employee access to production systems requires multi-factor authentication.
- Administrative privileges are granted through role-based access control and reviewed every 90 days.
- Production database access is limited to 12 named engineers.
- Terminated employees lose all system access within 4 hours.

## Security Testing and Training
- External penetration tests are conducted twice per year.
- Automated vulnerability scans run weekly against all public-facing services.
- All employees complete security awareness training annually.
- Phishing simulation campaigns are run quarterly.

## Operations and Support
- The platform uptime SLA is 99.9% measured monthly.
- Tier 1 support is available 24 hours a day, 7 days a week.
- Tier 应当是2 engineering escalations are staffed Monday through Friday, 08:00 to 20:00 UTC.
- Subprocessor security reviews are conducted annually.
