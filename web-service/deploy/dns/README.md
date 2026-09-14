# arcturuschess.com DNS preparation

Prepared from Mike's GoDaddy screenshot and public DNS on September 14, 2026
UTC (September 13 locally). The destination is the existing Lightsail IPv4
address, verified against the currently working Arcturus hostname. Later public
DNS checks on September 14 UTC confirmed that the apex now has only
`54.190.167.232`; the two Website Builder addresses have been removed. Server
hostname activation and email delivery remain separate from these DNS changes.

## Website DNS checkpoint

| Type | Name | Value | TTL | Action |
| --- | --- | --- | --- | --- |
| A | `@` | `54.190.167.232` | 1 hour / 3600 seconds | Applied; retain this sole address |
| CNAME | `www` | `arcturuschess.com.` | 1 hour / 3600 seconds | Keep existing record |

The website's A-record replacement is complete. The earlier
[arcturuschess.com.changes.zone](arcturuschess.com.changes.zone) records that
single website change; do not reimport it or restore the former
`13.248.243.5` / `76.223.105.230` addresses. The separate SES file below adds
only the email-domain verification records.

## Records to retain

Leave both `ns03.domaincontrol.com` / `ns04.domaincontrol.com` nameservers and
GoDaddy's managed SOA untouched. Retain the `pay` and `_domainconnect` aliases
and the exact `_dmarc` TXT value from the screenshot. None needs changing to
host the chess website. Public lookups found no apex MX, TXT, CAA or AAAA
records at the website checkpoint. The SES setup below adds three DKIM CNAMEs;
it does not require replacing the existing DMARC policy or adding website,
MX, SPF, CAA, AAAA or wildcard records.

[arcturuschess.com.reference.zone](arcturuschess.com.reference.zone) shows the
website-only inventory from the supplied screenshot, including the full SOA
data verified through DNS. It predates the SES additions and is a reference,
not an additive import file. GoDaddy should continue managing the SOA serial
and timing fields.

## SES identity verification: DNS pending

On September 14, 2026 UTC, a new `arcturuschess.com` identity was created in
Amazon SES **US West (Oregon), us-west-2**. Its status is **Verification
pending**. Easy DKIM uses RSA 2048 for both current and next signing keys, with
signatures enabled. Custom MAIL FROM is not configured. Email feedback
forwarding is enabled; no SNS notification topics are configured.

Import [arcturuschess.com.ses.txt](arcturuschess.com.ses.txt) to add the exact
three CNAME records supplied by this identity, each with TTL 3600 seconds.
[arcturuschess.com.ses.csv](arcturuschess.com.ses.csv) is a reference copy of
those records, not the GoDaddy import file.

1. Export the current GoDaddy zone as a backup.
2. In the domain's **DNS** page, choose **Actions → Import Zone File**, select
   `arcturuschess.com.ses.txt`, review its three CNAME additions, and apply.
3. Retain every existing record, particularly the sole apex A address, `www`,
   both nameservers, SOA and the existing `_dmarc` TXT record.
4. Check all three DKIM CNAMEs through the authoritative nameservers, then
   confirm the domain and DKIM status in SES. Do not treat file preparation
   or an import acknowledgment as completed verification.

GoDaddy imports add records rather than replace the zone and can reject
conflicting records. The previous SES setup also found that this importer
rejected a `.zone` extension but accepted the same BIND content as `.txt`;
use the supplied `.txt`, not the CSV or complete website reference.
See [GoDaddy's import instructions](https://www.godaddy.com/help/import-my-domains-zone-file-records-4167)
and the [recorded SES setup](../../docs/GAME-NOTIFICATIONS.md).

The SES dashboard reports the account as healthy but still in the sandbox,
with a 200-message daily quota and one message per second. Account suppression
is enabled for bounces and complaints. The setup page still reports **More
information needed** for production access, but the support case shows
**Customer action completed**: Mike's detailed September 12 follow-up is
already filed, with no newer AWS reply visible at this September 14 UTC check.
AWS's response is pending; no additional reply was sent. Domain/DKIM
verification does not remove sandbox restrictions
or activate Arcturus email. Application SMTP configuration, sender permissions,
branding and canonical URLs, delivery and feedback tests, and a separate
notification timer remain follow-up work. No email was sent while preparing
these files. See [password recovery](../../docs/PASSWORD-RECOVERY.md) for the
separate activation requirements.

## Server activation and account continuity

DNS alone will not activate the new website. The experimental server still
needs the new HTTPS hostname, canonical `www` redirect and matching application
origin before the new address is ready. Existing replay paths should be
preserved. Do not redirect all old-host traffic until account continuity is
handled: login cookies are host-only; password users must sign in again, and
passwordless users need an account-protection or migration route first.

The new DNS points directly to the host's IP and includes no reference to the
original Astra domain. This reduces promotion of that address; it does not
make the expensive service access-controlled. Shared infrastructure and
historical public records can still associate the sites. Future activation
should avoid adding public links from Arcturus to the expensive Astra service.
