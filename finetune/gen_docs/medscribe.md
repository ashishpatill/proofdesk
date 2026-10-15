# MedScribe — Security and Operations

## Encryption and Data Protection
- All data in transit between hospital clients and MedScribe is encrypted using TLS 1.3.
- Data at rest is encrypted with AES-256 in all production storage systems.
- Database backups are encrypted with AES-256 and stored in the us-east-1 region.
- Encryption keys are rotated every 90 days through a managed key management service.

## Certifications and Compliance
- MedScribe maintains SOC 2 Type II certification, audited annually by an independent third party.
- The platform is operated in accordance with HIPAA requirements for protected health information.
- GDPR data subject requests are processed within 30 days of receipt.
- A SOC 2 Type II report is available to hospital clients under NDA within 5 business days of request.

## Data Retention and Backups
- Clinical documentation is retained for 7 years after patient discharge, in line with hospital contractual requirements.
- Full database backups are performed daily at 02:00 UTC.
- Incremental backups run every 4 hours.
- Backup restoration tests are conducted quarterly, with results documented within 10 business days.
- Audit logs are retained for 12 months and stored in immutable storage.

## Incident Response and Notification
- Confirmed security incidents affecting client data are reported to affected hospitals within 24 hours of confirmation.
- Post-incident reports are delivered within 10 business days of incident closure.
- The incident response team conducts a tabletop exercise twice per year.
- Critical severity incidents trigger an on-call escalation within 15 minutes.

## Access Control and Monitoring
- Production access requires multi-factor authentication using FIDO2 hardware keys.
- Access to production systems follows least-privilege role assignments, reviewed every 90 days.
- All administrative access to production is logged and reviewed weekly.
- Penetration tests are performed annually by an external security firm.
- Vulnerability scans run weekly across all internet-facing services.

## Availability and Support
- MedScribe maintains a 99.9% monthly uptime SLA for the clinical documentation platform.
- Customer support is available 24 hours a day, 7 days a week, with a 1-hour response target for critical issues.
- Scheduled maintenance windows occur no more than twice per month and are announced 72 hours in advance.

## Personnel and Subprocessors
- All employees complete security awareness training within 30 days of hire and annually thereafter.
- Subprocessor security reviews are conducted annually, and the subprocessor list is updated within 5 business days of any change.
