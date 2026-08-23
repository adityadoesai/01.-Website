# DNS records for adityadave.in

Captured 23 August 2026, before moving nameservers from Hostinger to Cloudflare.
Kept so these can be rebuilt by hand if an import ever loses them.

Nameservers at time of capture: `ns1.dns-parking.com`, `ns2.dns-parking.com` (Hostinger).

## Email — must survive the move

Losing any of these silently breaks mail to and from `@adityadave.in`.

| Type | Name | Value | Priority | Proxy |
|---|---|---|---|---|
| MX | `@` | `mx1.hostinger.in` | 5 | DNS only |
| MX | `@` | `mx2.hostinger.in` | 10 | DNS only |
| TXT | `@` | `v=spf1 include:_spf.mail.hostinger.com ~all` | — | DNS only |
| CNAME | `autodiscover` | `autodiscover.mail.hostinger.com` | — | **DNS only (grey cloud)** |
| CNAME | `autoconfig` | `autoconfig.mail.hostinger.com` | — | **DNS only (grey cloud)** |

Cloudflare tends to set imported CNAMEs to Proxied. The two mail CNAMEs must be
DNS only, or mail-client auto-setup stops working.

No DMARC record exists, and no DKIM was found under the usual Hostinger
selectors. Nothing to preserve there — but also nothing protecting the domain
from spoofing, which is worth revisiting once the move has settled.

## Website — expected to change

| Type | Name | Value | Note |
|---|---|---|---|
| A | `@` | `82.25.106.145` | old Hostinger WordPress server |
| CNAME | `www` | `adityadave.in` | www to root |

Both are replaced by Cloudflare Pages when the custom domain is attached. That
replacement is the point of the migration, not a mistake.

## Verifying after the switch

```bash
dig +short MX adityadave.in          # expect mx1/mx2.hostinger.in
dig +short TXT adityadave.in         # expect the SPF line above
dig +short NS adityadave.in          # expect two cloudflare.com nameservers
dig +short A adityadave.in           # expect Cloudflare IPs, not 82.25.106.145
```

Send yourself a test message at `@adityadave.in` once the nameservers have
propagated. Email failures are silent, so an explicit test is the only
reliable check.
