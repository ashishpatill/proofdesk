# Northwind Analytics — Security Overview

Northwind Analytics is a cloud data-warehouse consultancy. This
overview describes the security posture of our managed platform.

- All customer data is encrypted in transit with TLS 1.3 and at rest
  with AES-256-GCM.
- Northwind holds SOC 2 Type II certification, audited in January
  2026 by an independent CPA firm.
- Access to production systems requires phishing-resistant hardware
  keys (FIDO2). Password-only access is disabled.
- Vulnerability scans run weekly; critical findings are remediated
  within 7 days.
- Customer data is hosted exclusively in the EU (Frankfurt region).
- Backups are taken every 6 hours and retained for 35 days.
- Northwind does not train machine-learning models on customer data.
- Subprocessors are reviewed annually; the current list includes
  three infrastructure providers.
- Security incidents are acknowledged within 4 business hours.
- Employees complete security awareness training twice a year.
- Penetration tests are performed twice a year by an external firm.
- Data deletion requests are completed within 30 days.
