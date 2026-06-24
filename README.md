# autobot

`autobot` is a configurable webhook automation daemon for AI-assisted code maintenance.

The first supported provider is a private GitHub App. The daemon receives webhook events, stores them durably, queues work in Redis or Valkey, waits for a configurable PR quiet window, gathers context when work is ready, and creates/updates human-reviewable child PRs.

## Core behavior

1. Receive and verify a provider webhook.
2. Persist the raw payload and delivery metadata.
3. Normalize the payload into a provider-agnostic event envelope.
4. Route by `autobot.toml` event scope and handler rules.
5. Queue work by resource.
6. Wait until the resource is quiet for `quiet_window_seconds`.
7. Gather full PR/check/comment/repo context when ready.
8. Run the configured handler and quality gates.
9. Create or update one `autobot` child PR per parent PR.

## Local config

Default config path:

```text
~/.config/autobot/autobot.toml
```

Secrets must not be written directly into TOML. Use environment variables, a git-ignored `.env`, files, or systemd credentials.

Example `.env`:

```dotenv
AUTOBOT_GITHUB_APP_ID=4137601
AUTOBOT_GITHUB_WEBHOOK_SECRET=replace-me
AUTOBOT_QUEUE_URL=redis://127.0.0.1:6379/0
```

## Service endpoints

Recommended local daemon config:

```toml
[server]
host = "127.0.0.1"
port = 9090
webhook_path = "/hooks/github"
health_path = "/healthz"
readiness_path = "/readyz"
```

Apache should proxy:

```text
https://public.webhooks.endpoint/hooks/github -> http://127.0.0.1:9090/hooks/github
```

## Running as a systemd service

Installing the Python package should not silently register or start a systemd service. Running `autobot` as a daemon is an explicit admin step.

For manual installs, adapt the example unit in `examples/systemd/autobot.service`:

```bash
sudo install -D -m 0644 examples/systemd/autobot.service /etc/systemd/system/autobot.service
sudo systemctl daemon-reload
sudo systemctl enable --now autobot.service
sudo systemctl status autobot.service --no-pager
```

Package-manager builds may ship a systemd unit, but enabling the daemon should still be an explicit user/admin action.

A future `autobot service install` command may automate this with confirmation and root privileges, but direct package installation should remain side-effect free.

This VM's rollout uses an installed and enabled `/etc/systemd/system/autobot.service` that runs `autobot serve` behind Apache.

## GitHub App installation

`autobot` receives GitHub events through a GitHub App webhook. For organization repositories, prefer creating or installing a GitHub App that the organization can actually authorize.

### Choose where the app lives

You have two good options:

| App owner | Use when | Notes |
| --- | --- | --- |
| Personal account | You only need personal repositories, or the app is allowed to be installed by any account. | If the organization does not appear during installation, check the app's installability and your org permissions. |
| Organization | You need reliable org-wide setup. | Usually the best option for company repos because org owners/admins can manage installation and repository access directly. |

If an organization is not available when installing a personal-account app, one of these is usually true:

- The app is configured so it can only be installed on the owner account.
- The organization restricts third-party or user-owned GitHub Apps.
- Your GitHub user does not have permission to install apps for that organization.

In that case, either update the app settings to allow installation by any account, ask an org owner to approve/install it, or create a new GitHub App owned by the organization.

### Create the app

Create a GitHub App from the account or organization that should own it.

Use these settings:

| Setting | Value |
| --- | --- |
| Webhook URL | `https://public.webhooks.endpoint/hooks/github` |
| Webhook active | Enabled |
| SSL verification | Enabled |
| Webhook secret | A high-entropy secret stored outside git |

Store secrets locally through environment variables, a git-ignored `.env`, files, or systemd credentials. Do not put raw secrets in `autobot.toml`.

Example local `.env`:

```dotenv
AUTOBOT_GITHUB_APP_ID=4137601
AUTOBOT_GITHUB_WEBHOOK_SECRET=replace-me
AUTOBOT_QUEUE_URL=redis://127.0.0.1:6379/0
```

Generate a private key for the app and store it outside git, for example:

```text
~/.config/autobot/github-app.private-key.pem
```

Recommended permissions for the initial GitHub provider:

| Permission | Access | Why |
| --- | --- | --- |
| Metadata | Read-only | Required by GitHub Apps. |
| Contents | Read and write | Create/update generated child branches. |
| Pull requests | Read and write | Read PR context and open/update child PRs. |
| Issues | Read and write | Read/comment on issue and PR discussions. |
| Checks | Read-only | Inspect failing checks. |
| Actions | Read-only | Inspect workflow failures/log context. |

Subscribe to these events:

```text
ping
pull_request
pull_request_review
pull_request_review_comment
issue_comment
check_run
check_suite
workflow_run
```

### Install the app on repositories

Install the app on selected repositories first. Then add each installed repo to `~/.config/autobot/autobot.toml`:

```toml
[[repos]]
key = "ORG_OR_USER/REPO"
enabled = true
provider = "github"
local_path = "/path/to/local/clone"

[repos.ai]
provider = "copilot"

[repos.quality]
run_tests_before_commit = false
run_ai_review_before_commit = false
run_coderabbit_before_commit = false

[repos.branching]
child_branch_template = "{{app_name:-autobot}}/{{pr_number:-pr-unknown}}-fix"
```

Restart the service after changing config:

```bash
systemctl restart autobot.service
```

### Firewall allowlist

GitHub recommends allowing webhook source IPs from the live `GET /meta` endpoint. Use the `hooks` ranges from:

```text
https://api.github.com/meta
```

At the time this README was written, the `hooks` ranges were:

```text
192.30.252.0/22
185.199.108.0/22
140.82.112.0/20
143.55.64.0/20
2a0a:a440::/29
2606:50c0::/32
```

Allow those ranges to inbound TCP `443` on the VM. Keep TCP `80` reachable if this host uses HTTP-01 certificate renewal.

GitHub can change these ranges, so refresh your firewall allowlist periodically from `/meta`.

`autobot` can track these ranges for you. Enable the monitor in `autobot.toml`:

```toml
[providers.github.ip_allowlist_monitor]
enabled = true
meta_url = "https://api.github.com/meta"
check_interval_seconds = 86400
warn_on_change = true
```

The monitor stores the latest `hooks` ranges in SQLite. On startup and then periodically, `autobot serve` compares GitHub's live ranges to the stored snapshot. If the ranges change, it logs a warning to systemd/journal and records the added/removed CIDRs in SQLite. It does not update firewall rules automatically.

Manual commands:

```bash
autobot github-ip-ranges check --config ~/.config/autobot/autobot.toml
autobot github-ip-ranges status --config ~/.config/autobot/autobot.toml
```

### Verify installation

Check the local service:

```bash
autobot doctor --config ~/.config/autobot/autobot.toml
curl -fsS https://public.webhooks.endpoint/healthz
curl -fsS https://public.webhooks.endpoint/readyz
```

Then use the GitHub App settings page to redeliver a `ping` webhook. A successful delivery should return `202`.

If GitHub reports `failed to connect to host` and Apache logs show no request, check cloud firewall rules first. In the initial rollout, that error was caused by the DigitalOcean firewall blocking GitHub Hookshot IPs.

## Template literals

`autobot` supports safe template literals in config strings, prompts, shell commands, branch names, and PR titles.

Syntax:

| Syntax | Meaning |
| --- | --- |
| `{{name}}` | Required variable. Rendering fails if missing. |
| `{{name:-default}}` | Optional variable with default fallback. |
| `{{nested.value}}` | Nested dictionary lookup. |

No code execution, filters, loops, or function calls are supported.

Branch names are sanitized after rendering: unsupported characters become `-`, repeated slashes collapse, leading/trailing slash/dot characters are removed, and names are capped to a safe length.

Common variables:

| Variable | Available in | Description |
| --- | --- | --- |
| `app_name` | all workflows | App name, usually `autobot`. |
| `handler_id` | handler workflows | Matched handler id. |
| `handler_name` | handler workflows | Human-readable handler name when configured. |
| `provider` | all provider events | Provider key, e.g. `github`. |
| `event_name` | all provider events | Raw provider event, e.g. `pull_request_review_comment`. |
| `event_action` | events with actions | Raw provider action, e.g. `created`. |
| `repo_key` | repo events | Repository key, e.g. `owner/repo`. |
| `actor` | provider events | User who triggered the event. |
| `delivery_id` | provider events | Provider delivery id. |
| `resource_key` | queued jobs | Stable queue/coalescing resource key. |
| `pr_number` | PR-scoped jobs | Parent PR number. |
| `parent_pr_number` | PR-scoped jobs | Parent PR number. |
| `parent_branch` | PR-scoped jobs | Parent PR head/source branch. |
| `parent_pr_head_branch` | PR-scoped jobs | Parent PR head/source branch. |
| `parent_pr_base_branch` | PR-scoped jobs | Parent PR base/target branch. |
| `child_branch` | child PR workflows | Generated child branch. |
| `child_pr_number` | child PR workflows | Generated child PR number when known. |
| `commit_sha` | commit/check workflows | Relevant commit SHA. |
| `check_url` | check workflows | Provider check/log URL when available. |
| `comment_body` | comment workflows | Review/comment body. |

Example:

```toml
[defaults.branching]
child_branch_template = "{{app_name:-autobot}}/{{pr_number:-pr-unknown}}-fix"
```

## CLI

```bash
autobot doctor
autobot serve
autobot render 'hello {{name:-world}}'
```

`autobot serve` runs the always-on HTTP daemon. `doctor` validates config and dependencies.
