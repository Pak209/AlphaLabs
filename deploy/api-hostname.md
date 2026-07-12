# api.pak-labs.com — prepared, NOT routed

The public hostname for the Intelligence API (:8790). Everything below is
staged; nothing resolves publicly until the [HUMAN] DNS step runs.

## Security model (differs from alpha.pak-labs.com on purpose)

- **No Cloudflare Access** — auth is API keys / x402 payments, not operator
  identity. A public API cannot sit behind an identity wall.
- Cloudflare WAF + rate rules at the edge (set at flip time), the gateway's
  own per-key rate limits behind that, and the loopback bind means the ONLY
  path in is the tunnel.
- The intel app has no personal surface to protect (architecturally absent),
  and commercial mode + catalog pricing enforce the licensing posture.

## Ingress snippet (add to ~/.cloudflared/alphalabs.yml ABOVE the 404 rule)

```yaml
  - hostname: api.pak-labs.com
    service: http://127.0.0.1:8790
```

## Activation (at flip time — both steps [HUMAN]-approved)

```bash
# 1. add the snippet above to ~/.cloudflared/alphalabs.yml, then restart the
#    connector (brief blip on alpha.pak-labs.com while it reconnects):
launchctl kickstart -k gui/$(id -u)/com.alphalab.tunnel-alpha

# 2. route DNS — ALWAYS pass the tunnel UUID (route-dns without it silently
#    binds the CNAME to the default config.yml tunnel — learned 2026-07-08):
cloudflared tunnel route dns bd34f2c8-d5f8-42e6-973f-b37e9c134dba api.pak-labs.com

# 3. verify from off-box:
curl -s https://api.pak-labs.com/health
```

## Rollback

Delete the DNS record in the Cloudflare dashboard (or `--overwrite-dns` to a
dead target), remove the ingress block, kickstart the connector again.
