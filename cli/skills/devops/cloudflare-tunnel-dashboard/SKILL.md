---
name: cloudflare-tunnel-dashboard
description: Expose a local Elevate dashboard safely through a custom Cloudflare subdomain. Use when the user wants remote access to their dashboard from another device without router port-forwarding, via Cloudflare Tunnel, DNS API, and a local Basic Auth proxy when Cloudflare Access permissions are unavailable.
tags:
  - cloudflare
  - cloudflared
  - tunnel
  - dashboard
  - remote-access
  - launchagent
---

# Cloudflare Tunnel for Elevate Dashboard

Use this when the user wants to access a local Elevate dashboard remotely through a domain/subdomain, especially from another laptop, without router port-forwarding.

## Key lessons

- Prefer **Cloudflare Tunnel** over opening the local network or router ports.
- Keep the Elevate dashboard bound to `127.0.0.1`; tunnel to a local origin instead of exposing Elevate directly on LAN.
- If Cloudflare Access API permissions are missing, add a local Basic Auth reverse proxy in front of the dashboard as a temporary protection layer.
- A laptop-hosted dashboard is only available while the laptop is awake, online, and logged in. For 24/7 access, move Elevate to an always-on Mac mini/server later.
- DNS propagation can be uneven locally. If `curl`/system resolver says host not found but `dig @1.1.1.1` returns Cloudflare IPs, verify with `curl --resolve`.

## Prerequisites

1. Confirm local dashboard origin:
   ```bash
   lsof -nP -iTCP -sTCP:LISTEN | grep -E '9120|elevate|dashboard'
   python3 - <<'PY'
import urllib.request
for url in ['http://127.0.0.1:9120','http://localhost:9120']:
    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            print(url, r.status, r.headers.get('content-type'))
    except Exception as e:
        print(url, type(e).__name__, e)
PY
   ```

2. Check tools and Cloudflare auth:
   ```bash
   command -v cloudflared
   command -v wrangler
   wrangler whoami
   ```

3. If multiple Cloudflare accounts exist, identify the zone/account:
   ```python
   from pathlib import Path
   import urllib.request, json, tomllib
   token = tomllib.loads((Path.home()/'.wrangler/config/default.toml').read_text())['oauth_token']
   req = urllib.request.Request(
       'https://api.cloudflare.com/client/v4/zones?name=DOMAIN&per_page=50',
       headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'},
   )
   with urllib.request.urlopen(req, timeout=20) as r:
       print(json.dumps(json.load(r), indent=2))
   ```

## Build the tunnel

1. Create the tunnel under the correct account:
   ```bash
   CLOUDFLARE_ACCOUNT_ID=<account_id> wrangler tunnel create elevate-dashboard
   CLOUDFLARE_ACCOUNT_ID=<account_id> wrangler tunnel list
   ```

2. Configure ingress through Cloudflare API. Keep the final fallback rule:
   ```python
   from pathlib import Path
   import urllib.request, json, tomllib

   account_id = '<account_id>'
   tunnel_id = '<tunnel_id>'
   hostname = 'dashboard.example.com'
   token = tomllib.loads((Path.home()/'.wrangler/config/default.toml').read_text())['oauth_token']
   url = f'https://api.cloudflare.com/client/v4/accounts/{account_id}/cfd_tunnel/{tunnel_id}/configurations'
   body = {
       'config': {
           'ingress': [
               {'hostname': hostname, 'service': 'http://127.0.0.1:9122'},
               {'service': 'http_status:404'},
           ]
       }
   }
   req = urllib.request.Request(url, data=json.dumps(body).encode(), method='PUT', headers={
       'Authorization': 'Bearer '+token,
       'Content-Type': 'application/json',
   })
   with urllib.request.urlopen(req, timeout=20) as r:
       print(json.dumps(json.load(r), indent=2))
   ```

   Note: `originRequest.connectTimeout: "30s"` can fail with `strconv.ParseInt`; omit optional timeout fields unless needed.

3. Create DNS record using a DNS-capable API token, not necessarily Wrangler OAuth:
   ```python
   from pathlib import Path
   import urllib.request, json

   env = {}
   for line in Path('~/.elevate/dashboard-tunnel/cloudflare.env').expanduser().read_text(errors='ignore').splitlines():
       s = line.strip()
       if s and not s.startswith('#') and '=' in s:
           k, v = s.split('=', 1)
           env[k] = v.strip().strip('"').strip("'")

   token = env['CLOUDFLARE_API_TOKEN']
   zone_id = env['CLOUDFLARE_ZONE_ID']
   hostname = 'dashboard.example.com'
   tunnel_id = '<tunnel_id>'
   content = f'{tunnel_id}.cfargotunnel.com'
   headers = {'Authorization': 'Bearer '+token, 'Content-Type': 'application/json'}

   body = {'type':'CNAME','name':hostname,'content':content,'proxied':True,'ttl':1,'comment':'Elevation dashboard Cloudflare Tunnel'}
   req = urllib.request.Request(
       f'https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records',
       data=json.dumps(body).encode(), method='POST', headers=headers,
   )
   with urllib.request.urlopen(req, timeout=20) as r:
       print(json.dumps(json.load(r), indent=2))
   ```

## Add a local Basic Auth proxy when Cloudflare Access is unavailable

Cloudflare Access API may return `403 Authentication error` if the token lacks Access permissions. In that case, create a local proxy bound to `127.0.0.1:9122` that requires Basic Auth and forwards to `127.0.0.1:9120`. The tunnel ingress should point at `9122`, not directly at `9120`.

Minimum Node proxy requirements:

- Load credentials from `~/.elevate/dashboard-tunnel/proxy.env` with mode `600`.
- Require `Authorization: Basic ...` on both HTTP requests and WebSocket `upgrade` requests.
- Forward HTTP and upgrade traffic to the dashboard origin.
- Bind only to `127.0.0.1`.

Generate credentials with:
```python
import secrets, string, pathlib
base = pathlib.Path.home()/'.elevate/dashboard-tunnel'
base.mkdir(parents=True, exist_ok=True)
password = ''.join(secrets.choice(string.ascii_letters+string.digits+'-_.') for _ in range(24))
(base/'proxy.env').write_text(f'DASHBOARD_PROXY_USER=<owner-username>\nDASHBOARD_PROXY_PASS={password}\nTARGET_HOST=127.0.0.1\nTARGET_PORT=9120\nPROXY_HOST=127.0.0.1\nPROXY_PORT=9122\n')
(base/'proxy.env').chmod(0o600)
print(password)
```

## Run and persist on macOS

1. Start the proxy and tunnel as LaunchAgents so they restart after login:
   - `~/Library/LaunchAgents/com.elevation.dashboard-auth-proxy.plist`
   - `~/Library/LaunchAgents/com.elevation.dashboard-cloudflared.plist`

2. The cloudflared/wrangler LaunchAgent should include:
   ```xml
   <key>ProgramArguments</key>
   <array>
     <string>/usr/local/bin/wrangler</string>
     <string>tunnel</string>
     <string>run</string>
     <string><tunnel_id></string>
   </array>
   <key>EnvironmentVariables</key>
   <dict>
     <key>HOME</key><string>/Users/admin</string>
     <key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
     <key>CLOUDFLARE_ACCOUNT_ID</key><string><account_id></string>
   </dict>
   <key>RunAtLoad</key><true/>
   <key>KeepAlive</key><true/>
   ```

3. Load/restart:
   ```bash
   UIDNUM=$(id -u)
   launchctl bootstrap gui/$UIDNUM ~/Library/LaunchAgents/com.elevation.dashboard-auth-proxy.plist
   launchctl bootstrap gui/$UIDNUM ~/Library/LaunchAgents/com.elevation.dashboard-cloudflared.plist
   launchctl kickstart -k gui/$UIDNUM/com.elevation.dashboard-auth-proxy
   launchctl kickstart -k gui/$UIDNUM/com.elevation.dashboard-cloudflared
   launchctl print gui/$UIDNUM/com.elevation.dashboard-auth-proxy | egrep 'state =|pid =|last exit code'
   launchctl print gui/$UIDNUM/com.elevation.dashboard-cloudflared | egrep 'state =|pid =|last exit code'
   ```

## Verification

1. Local proxy:
   ```bash
   curl -I http://127.0.0.1:9122       # should be 401
   curl -I -u user:pass http://127.0.0.1:9122  # should be 200
   ```

2. Tunnel health:
   ```bash
   CLOUDFLARE_ACCOUNT_ID=<account_id> wrangler tunnel info <tunnel_id>
   # Status should be healthy
   ```

3. DNS and public lock:
   ```bash
   dig +short @1.1.1.1 dashboard.example.com A
   curl -I https://dashboard.example.com     # should be 401
   curl -L -u user:pass https://dashboard.example.com | head
   ```

4. If the local resolver still cannot resolve the hostname, use `curl --resolve` to verify Cloudflare path while DNS cache catches up:
   ```bash
   curl -I --resolve dashboard.example.com:443:<cloudflare_ip> https://dashboard.example.com
   curl -L --resolve dashboard.example.com:443:<cloudflare_ip> -u user:pass https://dashboard.example.com | head
   ```

## Multiple dashboard users vs. new redirect URLs

When the user asks whether another realtor/user needs a new redirect URL, separate the layers clearly:

1. **Cloudflare Tunnel / DNS URL** is only the public front door. One URL can serve multiple users if the application/dashboard supports user or workspace routing after login.
2. **Local Basic Auth proxy credentials** are only the public-URL gate. A username generated by this proxy setup did **not** replace the user's account/dashboard login. Do not describe it as the real dashboard identity.
3. **Dashboard/app login or workspace mapping** decides whose dashboard data appears. Before telling the user another person can safely use the same URL, verify in a private/incognito browser that the other user's login lands in their own workspace and cannot see the original user's deals/leads/messages/assets.

Default answer pattern:

- **No new redirect/subdomain is needed** just to let another user log in, unless the user wants a separate branded entry point or the other user is on a separate deployment/app instance.
- **A separate gate credential is needed** if using the Basic Auth proxy. Do not share the original user's Basic Auth username/password. Add a per-user username/password with a unique password, then test.
- If the other user logs in and sees the original user's dashboard, the issue is **workspace/auth isolation**, not Cloudflare redirect/DNS.

If the current proxy only supports one `DASHBOARD_PROXY_USER` / `DASHBOARD_PROXY_PASS`, either extend it to support a credential allowlist from a `600` file (preferred for multiple users) or rotate the single shared credential only as a temporary measure. Keep the tunnel ingress pointed at the protected proxy, never directly at the dashboard origin.

## Safety notes

- Do not publish the dashboard without Cloudflare Access or a local auth layer.
- Do not print full Cloudflare tokens. Redact Wrangler logs if needed.
- Keep Basic Auth credentials in a `600` file and give the password to the user only through the current secure chat context.
- Tell the user the dashboard goes offline if the laptop sleeps/closes.
- Prefer upgrading to Cloudflare Access locked to the user’s email once Access permissions are available.
