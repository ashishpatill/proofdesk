# Ledgerly — Security and Operations

## Encryption and Data Protection
- All customer data is encrypted at rest using AES-256, with keys rotated every 90 days through AWS KMS in the us-east-1 region.
- Data in transit is protected with TLS 1.3; TLS 1.0 and 1.1 are disabled across all production endpoints.
- Database backups are encrypted with AES-256 and stored in a separate AWS account restricted to three named security engineers.

## Certifications and Compliance
- Ledgerly maintains SOC 2 Type II certification, audited annually by an independent third-party firm.
- The platform is GDPR-compliant, and EU customer data is stored exclusively in the eu-central-1 region.
- A Data Protection Impact Assessment is reviewed and updated every 12 months by the security team.

## Data Retention and Backups
- Production databases are backed up every 6 hours, with a full snapshot retained for 35 days.
- Deleted customer records are purged from primary storage within 30 days and from backups within 90 days.
- Audit logs are retained for 12 months and stored in immutable S3 buckets with object lock enabled.

## Incident Response
- Confirmed security incidents affecting customer data are reported to affected customers within 72 hours.
- The incident response team conducts a tabletop exercise every quarter and a full post-incident review within 5 business days of closure.
- Critical severity incidents trigger a page to the on-call engineer within 15 minutes via PagerDuty.

## Access Control
- Employee access to production systems requires hardware-backed FIDO2 security keys and is reviewed every 90 days.
- Administrative access follows least-privilege principles, and no more than 8 employees hold production write access at any time.
- All access to customer data is logged and retained for 12 months in the central SIEM.

## Vendor and Subprocessor Management
- Subprocessors are reviewed for security posture every 6 months, and the current list is published on the Ledgerly trust page.
- New subprocessors require sign-off from the CTO and Head of Security before onboarding.

## Security Testing
- External penetration tests are performed twice per year by a third-party firm, with remediation of critical findings within 14 days.
- Automated vulnerability scans run daily against production infrastructure, and dependency scanning runs on every pull request.

## Availability and Support
- Ledgerly targets a 99.9% monthly uptime SLA, measured at the API gateway and reported on a public status page.
- Customer support is available Monday through Friday, 8:00–20:00 Eastern Time, with a 4-hour first-response target for urgent tickets.

## Employee Security
- All employees complete security awareness training within 14 days of hire and annually thereafter.
- Background checks are conducted for all employees with access to production systems prior to their start date.
