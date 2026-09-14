# arcturuschess.com DNS preparation

Prepared from Mike's GoDaddy screenshot and public DNS on September 14, 2026
UTC (September 13 locally). The destination is the existing Lightsail IPv4
address, verified against the currently working Arcturus hostname. Preparing
these files has not changed DNS or the running service.

## Apply the single required change

| Type | Name | Value | TTL | Action |
| --- | --- | --- | --- | --- |
| A | `@` | `54.190.167.232` | 1 hour / 3600 seconds | Replace Website Builder Site |
| CNAME | `www` | `arcturuschess.com.` | 1 hour / 3600 seconds | Keep existing record |

The quickest method is to edit the existing `A` / `@` record in GoDaddy,
replace its Website Builder destination with `54.190.167.232`, and save.
This is the only DNS change required for the apex and `www` website names.
See [GoDaddy's A-record editing instructions](https://www.godaddy.com/help/edit-an-a-record-19239).

To use the supplied BIND-format import instead:

1. Export the current GoDaddy zone as a backup.
2. Delete only the existing `A` / `@` Website Builder Site record. Public DNS
   currently expands it to `13.248.243.5` and `76.223.105.230`; neither old
   address should remain in the final apex A-record set.
3. In this domain's **DNS** page, choose **Actions → Import Zone File** and
   import [arcturuschess.com.changes.zone](arcturuschess.com.changes.zone), then
   apply it. Do not also perform the manual edit above: these are alternatives.
4. Confirm the apex has exactly one A destination, `54.190.167.232`, and keep
   the existing `www` CNAME pointing to `arcturuschess.com`.

GoDaddy's import adds to the current zone and may reject conflicting records;
it is not a replacement operation. The change file therefore contains only the
new A record. [Official import instructions](https://www.godaddy.com/help/import-my-domains-zone-file-records-4167).

## Records to retain

Leave both `ns03.domaincontrol.com` / `ns04.domaincontrol.com` nameservers and
GoDaddy's managed SOA untouched. Retain the `pay` and `_domainconnect` aliases
and the exact `_dmarc` TXT value from the screenshot. None needs changing to
host the chess website. No new MX, SPF, DKIM, CAA, AAAA or wildcard records are
needed for this website change. Public lookups found no apex MX, TXT, CAA or
AAAA records at this checkpoint; this is not an email-service configuration.

[arcturuschess.com.reference.zone](arcturuschess.com.reference.zone) shows the
complete desired inventory from the supplied screenshot, including the full
SOA data verified through DNS. It is a reference, not the additive import file.
GoDaddy should continue managing the SOA serial and timing fields.

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
