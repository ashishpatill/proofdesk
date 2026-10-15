# FleetPilot — Security and Operations

## Encryption and Data Protection
- All data in transit between FleetPilot clients and the platform is encrypted using TLS 1.3.
- Data at rest in FleetPilot production databases is encrypted with AES-256.
- Telematics event payloads stored in the cold archive are encrypted with AES-256 and re-keyed every 12 months.
- API keys issued to fleet operators expire after 90 days and must be rotated through the FleetPilot admin console.

## Certifications and Compliance
- FleetPilot maintains SOC 2 Type II certification, audited annually by an independent third-party assessor.
- The SOC 2 Type II report covers the Security and Availability trust services criteria.
- Personal data of EU-based drivers is processed in accordance with GDPR, with standard contractual clauses in place for transfers to US regions.
- FleetPilot does not process protected health information and is not HIPAA-certified.

## Data Retention
- Vehicle location pings are retained for 90 days in hot storage and then moved to cold storage.
- Cold-storage telematics data is retained for 24 months before permanent deletion.
- Driver authentication logs are retained for 12 months.
- Deleted customer accounts are purged from all production systems within 30 days of a verified deletion request.

## Backup and Recovery
- Full database backups are taken daily at 02:00 UTC.
- Incremental backups run every 4 hours.
- Backup restoration drills are performed quarterly, with a target recovery time objective of 4 hours and a recovery point objective of 1 hour.
- Backup copies are stored in three AWS regions: us-east-1, eu-west-1, and ap-southeast-1.

## Incident Response and Notification
- Confirmed security incidents affecting customer data are reported to affected customers within 72 hours of confirmation.
- Critical production outages trigger an internal incident bridge within 15 minutes of detection.
- Post-incident reports are published to affected customers within 10 business days of incident closure.
- The security team conducts a tabletop incident-response exercise twice per year.

## Access Control
- Employee access to production systems requires hardware-backed FIDO2 security keys and is enforced through mandatory multi-factor authentication.
- Production access follows least-privilege role assignments reviewed every 90 days.
- Administrative access to production databases requires just-in-time approval valid for a maximum of 8 hours.
- Terminated employees have all system access revoked within 4 hours of offboarding.

## Vendor and Subprocessor Management
- The FleetPilot subprocessor list is reviewed every 6 months by the security and legal teams.
- New subprocessors are announced to customers at least 30 days before they begin processing customer data.
- All subprocessors handling customer data must maintain SOC 2 Type II or an equivalent certification.

## Security Testing and Training
- External penetration tests are conducted annually by a third-party firm, with the most recent test completed in the prior calendar year.
- Critical and high findings from penetration tests are remediated within 30 days.
- All employees complete security awareness training within 14 days of hire and annually thereafter.
- Phishing simulation campaigns are run monthly, and employees who fail twice in a quarter are enrolled in additional training.

## Availability and Support
- FleetPilot targets a monthly uptime SLA of 99.95% for the core telematics ingestion API.
- Production status is published on a public status page updated within 30 minutes of a confirmed degradation.
- Standard customer support is available 24 hours a day, 7 days a week, with a 1-hour first-response target for P1 tickets.
- Scheduled maintenance windows are announced at least 5 business days in advance and are limited to a maximum of 4 hours.
