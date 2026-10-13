# KiteMetric security policy (sample)

## Encryption

- Data at rest is encrypted with AES-256 (AWS KMS managed keys).
- Data in transit uses TLS 1.2 or higher; TLS 1.0 and 1.1 are
  disabled.
- Customer passwords are hashed with Argon2id.

## Access control

- Multi-factor authentication (TOTP) is enforced for all employee
  accounts, including email and cloud consoles.
- SSO via SAML 2.0 is available on Growth and Enterprise plans.
- Production access is least-privilege, granted per role, and
  reviewed every quarter.
- Production access requires a ticket reference and expires after
  8 hours.

## Assurance

- SOC 2 Type I report available under NDA. The Type I audit was
  completed in March 2026, covering the Security trust services
  criteria.
- An external firm performs a penetration test once a year. The most
  recent test was in November 2025; an executive summary is
  available under NDA.
