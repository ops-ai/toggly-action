# Toggly CLI GitHub Action

Composite GitHub Action that downloads a **pinned** [`toggly-cli`](https://github.com/ops-ai/Toggly.FeatureManagement/releases) release, verifies `SHA256SUMS`, and runs the arguments you pass.

This action does **not** call the Toggly HTTP API. Authentication is handled by the CLI via process environment variables.

> **Different product:** [Workflow dispatch from Toggly → GitHub](https://docs.toggly.io/docs/integrations/github-actions) (Toggly triggers your workflow when a flag changes) is the opposite direction. This action is for **your pipeline calling Toggly**.

## Inputs

| Input | Required | Description |
| --- | --- | --- |
| `version` | yes | CLI semver without the `cli-v` prefix (for example `0.2.1`). Floating `latest` is not allowed. |
| `args` | yes | Arguments for `toggly-cli`, quote-aware like a shell. **Do not put secrets here.** |

## Auth (environment only)

Set these on the step (or job) with Actions secrets:

| Variable | Required | Purpose |
| --- | --- | --- |
| `TOGGLY_CLIENT_ID` | yes (for write commands) | OAuth2 client ID |
| `TOGGLY_CLIENT_SECRET` | yes (for write commands) | OAuth2 client secret |
| `TOGGLY_BASE_URL` | no | API base URL (default production) |
| `TOGGLY_AUTHORITY` | no | Auth authority (default production) |

Never put `TOGGLY_CLIENT_SECRET` (or any secret) in `args`. Prefer env vars over `--client-id` / `--client-secret` flags.

## Pin rule

Always pin `version` to an exact `MAJOR.MINOR.PATCH` that matches a published `cli-v*` GitHub Release. Do not use `latest`.

## Example: associate a build

Flags verified against `toggly-cli` **0.2.1** (`associate-build --help`).

```yaml
name: Deploy

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      # ... build and deploy your app ...

      - name: Associate build with Toggly release
        uses: ops-ai/toggly-action@v1
        with:
          version: "0.2.1"
          args: >-
            associate-build
            --project-key my-app
            --environment Production
            --ci-provider github
            --run-id ${{ github.run_id }}
            --pipeline-name "${{ github.workflow }}"
            --branch ${{ github.ref_name }}
            --commit-sha ${{ github.sha }}
            --run-url ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
        env:
          TOGGLY_CLIENT_ID: ${{ secrets.TOGGLY_CLIENT_ID }}
          TOGGLY_CLIENT_SECRET: ${{ secrets.TOGGLY_CLIENT_SECRET }}
```

## Example: enable a feature after deploy

```yaml
- uses: ops-ai/toggly-action@v1
  with:
    version: "0.2.1"
    args: >-
      update-feature-environment
      --application-id my-app
      --environment Production
      --feature-key my-feature
      --enable
  env:
    TOGGLY_CLIENT_ID: ${{ secrets.TOGGLY_CLIENT_ID }}
    TOGGLY_CLIENT_SECRET: ${{ secrets.TOGGLY_CLIENT_SECRET }}
```

## Local development

```bash
python3 -m unittest discover -s tests -v
```

## License

MIT
