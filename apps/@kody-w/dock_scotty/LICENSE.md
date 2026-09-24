# Licenses

## RAPP Dock / Scotty code: MIT

MIT License

Copyright (c) 2026 kody-w

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

This covers the Scotty agent, the Dock controller, adapters, gateway server
and UI in this directory. It does not relicense any upstream application.

## Upstream applications and images

Each upstream app keeps its own license. The upstream license files are carried
under `singleton/scotty_support_<sha>/deploy/stacks/<app>/upstream/`, and
`components.lock.json` records the license notice for every locked image.

| Component | Upstream | License |
|---|---|---|
| Scrapling | D4Vinci/Scrapling | BSD 3-Clause |
| Presenton | presenton/presenton | Apache License 2.0 (with NOTICE) |
| OpenSEO | every-app/open-seo | MIT |
| OpenShorts | mutonby/openshorts | MIT, except its `cloud/` directory, which is under the OpenShorts Commercial License (`cloud/LICENSE`). Remotion, model and dependency terms also apply. |
| Dify | langgenius/dify | Modified Apache License 2.0 with additional conditions (below) |
| Intelligence gateway | github/copilot-cli | The official GitHub Copilot CLI terms; base-image licenses apply |
| Supporting images | PostgreSQL, pgvector, Redis, Squid, NGINX, BusyBox | Each publisher's license (for example Squid and BusyBox are GPL; source obligations apply) |

### Dify's additional conditions

Dify's license adds conditions to Apache 2.0. In short, and see its full text:

- **Multi-tenant service:** unless Dify authorizes it in writing, you may not
  use the Dify source code to operate a multi-tenant environment.
- **Logo and copyright:** when you use Dify's frontend, you may not remove or
  modify the logo or copyright information in the Dify console or applications.

RAPP Dock runs Dify as a single-owner local stack on your own computer.
