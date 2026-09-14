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

## SES DNS published; AWS verification pending

On September 14, 2026 UTC, a new `arcturuschess.com` identity was created in
Amazon SES **US West (Oregon), us-west-2**. Its status is **Verification
pending**. Easy DKIM uses RSA 2048 for both current and next signing keys, with
signatures enabled. Custom MAIL FROM is not configured. Email feedback
forwarding is enabled; no SNS notification topics are configured.

Mike imported the three DKIM records in his regular browser. At the September
14 **05:04 UTC** checkpoint, all three exact CNAME name/value pairs matched
this identity's records on `ns03.domaincontrol.com`, `ns04.domaincontrol.com`
and public resolver `1.1.1.1`. The refreshed SES console still showed identity
**Verification pending** and DKIM **Pending**. DNS publication is complete;
AWS verification is not yet confirmed. No repeated import is needed.

At 05:10 UTC, the SES verification-error popover still described its earlier
04:41 UTC lookup (September 13 at 23:41 UTC-05), with SOA serial `2026091304`
and "The DNS server could not find the specified domain name." Both GoDaddy
nameservers, Cloudflare (`1.1.1.1`) and Google (`8.8.8.8`) now returned SOA
serial `2026091305`, the correct apex address, and all three exact DKIM CNAMEs.
The displayed failure therefore predates the current DNS zone. Await a newer
SES verification result rather than deleting the identity or reimporting
already correct records.

[arcturuschess.com.ses.txt](arcturuschess.com.ses.txt) is the applied import file
for the exact three CNAME records supplied by this identity, each with TTL
3600 seconds. Retain it as the reproducible record of the additions.
[arcturuschess.com.ses.csv](arcturuschess.com.ses.csv) is a reference copy of
those records, not the GoDaddy import file.

For reference, the import procedure is:

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
