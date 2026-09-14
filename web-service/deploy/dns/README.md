# arcturuschess.com DNS preparation

Prepared from Mike's GoDaddy screenshot and public DNS on September 14, 2026
UTC (September 13 locally). The destination is the existing Lightsail IPv4
address, verified against the working Arcturus hostname. Later public
DNS checks on September 14 UTC confirmed that the apex now has only
`54.190.167.232`; the two Website Builder addresses have been removed. Server
hostname activation completed at 05:27 UTC on September 14; email delivery
remains a separate follow-up.

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

## SES domain and DKIM verified

On September 14, 2026 UTC, a new `arcturuschess.com` identity was created in
Amazon SES **US West (Oregon), us-west-2**. At **05:26 UTC**, a fresh AWS console
check confirmed identity **Verified** and DKIM **Successful**. Easy DKIM uses
RSA 2048 for both current and next signing keys, with
signatures enabled. Custom MAIL FROM is not configured. Email feedback
forwarding is enabled; no SNS notification topics are configured.

Mike imported the three DKIM records in his regular browser. At the September
14 **05:04 UTC** checkpoint, all three exact CNAME name/value pairs matched
this identity's records on `ns03.domaincontrol.com`, `ns04.domaincontrol.com`
and public resolver `1.1.1.1`. At that checkpoint, the refreshed SES console still showed identity
**Verification pending** and DKIM **Pending**. The 05:26 UTC console check above
subsequently confirmed both. No repeated import is needed.

At 05:10 UTC, the SES verification-error popover still described its earlier
04:41 UTC lookup (September 13 at 23:41 UTC-05), with SOA serial `2026091304`
and "The DNS server could not find the specified domain name." Both GoDaddy
nameservers, Cloudflare (`1.1.1.1`) and Google (`8.8.8.8`) now returned SOA
serial `2026091305`, the correct apex address, and all three exact DKIM CNAMEs.
The displayed failure predated the published DNS zone. Its timestamp explains
the temporary mismatch between correct public DNS and the then-pending AWS
status; the 05:26 UTC successful verification supersedes it.

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
or activate Arcturus email. The DNS preparation sent no mail. A subsequent
operator-only staged check of code `011c4b8` ran at **05:38:53–05:40 UTC**:
SES accepted Arcturus verification, reset and synthetic new-game notification
messages from addresses on the new domain, and the disposable HTTP lifecycle
and monitor checkpoint/no-news checks passed. Fifty focused Linux regressions
preceded that test. Mike confirmed receipt of all three and supplied a Gmail
screenshot showing them in the inbox; received-message authentication headers
were not inspected. See the
[sanitized mail validation record](../../experiments/arcturus-mail-2026-09-14.json).

The existing SMTP credentials were used only in root-private disposable test
storage; no actual player database or live service configuration changed.
At **05:41 UTC**, both live applications still reported recovery mail
unavailable, with all three service PIDs unchanged. The mail-branding code
`011c4b8` remains staged; the live checkout is `e73d81d`. Arcturus
has no separate monitor configuration or notification unit/timer installed.
SES's **05:31 UTC** sandbox check still showed 200 messages/day and one/second.
Live SMTP configuration, production access for general recipients,
feedback/delivery validation and separate notification activation remain
follow-up work. See [password recovery](../../docs/PASSWORD-RECOVERY.md) and
[notifications](../../docs/GAME-NOTIFICATIONS.md) for the activation boundaries.

## Server activation and account continuity

`https://arcturuschess.com` is active and is Arcturus's canonical origin.
Application code `17789dc` was deployed at **05:26:45 UTC** after an idle check
and coherent private backup. Installed-service namespace validation and 70
focused Linux tests passed; all four saved player bindings, private data and
budget records remained unchanged. The application accepts the previous
Arcturus origin only through an explicit additional-origin setting, while
requiring each write's Origin to match its request Host and retaining CSRF
validation.

The Caddy update succeeded at **05:27 UTC**, retaining all three running
service PIDs, the original route definitions and the configuration inode.
At **05:28 UTC**, a laptop check through normal public DNS resolved
`54.190.167.232` and verified TLS and HTTP 200 health. The `www` hostname
returned HTTP 308 to the canonical origin while preserving the path and query.
Mike also confirmed the new address working in his browser.

The old hostname remains functional without an automatic redirect. Login
cookies remain host-only: password users sign in again at the new address;
passwordless users should add a password under **Your account** on the old
hostname before moving. The old-host notice explains this and offers a manual
link to the canonical site. Existing account/session records are not migrated
or rewritten.

The new DNS points directly to the host's IP and includes no reference to the
original Astra domain. This reduces promotion of that address; it does not
make the expensive service access-controlled. Shared infrastructure and
historical public records can still associate the sites. Keep Arcturus's
public entry points focused on its own domain.
