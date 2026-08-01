# Repo Hygiene Playbook — Dependabot, Security Scanning & CI Guardrails

A copy-paste playbook for standing up dependency automation and security
hygiene on a project. Written from a rollout across three sibling
Flask + Vue + Docker repos published as Home Assistant add-ons, but the shape
applies to any repo with a backend, a frontend, containers, and GitHub Actions.

Work top-down: **§1 survey → §2 Dependabot → §3 security scanning → §4 policy →
§5 CI guardrails → §6 settings-only toggles → §7 verify**. Each section states
*why*, not just *what*, so you can adapt rather than cargo-cult.

---

## 1. Survey first (never guess the paths)

Dependabot silently does nothing if `directory:` doesn't point at a real
manifest. Enumerate what actually exists before writing config:

```bash
# manifests, containers, and existing CI in one pass
find . -maxdepth 3 \( -name "requirements*.txt" -o -name "pyproject.toml" \
  -o -name "package.json" -o -iname "Dockerfile*" \) \
  -not -path "*/node_modules/*" -not -path "*/.venv/*"
ls .github .github/workflows 2>/dev/null
```

Record: every dependency manifest **and its directory**, every Dockerfile
(including side-car/secondary images), and what security scanning already
exists. Expect asymmetry between sibling repos — in our rollout one repo had
CodeQL, another had Trivy + gitleaks, and a third had **no scanning at all**.

---

## 2. Dependabot (`.github/dependabot.yml`)

### The config

```yaml
version: 2
updates:
  # One block PER manifest directory. Add extra blocks for e2e/tools dirs.
  - package-ecosystem: "pip"
    directory: "/backend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      backend-python:
        update-types: ["minor", "patch"]   # majors get their own PR for review

  - package-ecosystem: "npm"
    directory: "/frontend"
    schedule:
      interval: "weekly"
    open-pull-requests-limit: 5
    groups:
      frontend-npm:
        update-types: ["minor", "patch"]

  # One block per Dockerfile directory — secondary images are easy to miss.
  - package-ecosystem: "docker"
    directory: "/"
    schedule:
      interval: "weekly"

  # Keeps checkout/setup-* off deprecated runtimes (e.g. the Node 20 EOL warning).
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      actions:
        patterns: ["*"]
```

### The decisions that matter

- **Group minor/patch, split majors.** `update-types: ["minor","patch"]` in a
  group gives one low-risk PR to merge, while each major arrives alone. This
  paid off immediately in our rollout: the first batch included `node 20→25`,
  `python 3.11→3.14`, `vite 5→8`, `pinia 2→4`. Bundled, that is one
  unreviewable, un-bisectable PR; split, each is a deliberate decision.
- **Grouping `github-actions` with `patterns: ["*"]`** is safe — action bumps are
  usually mechanical, and one PR beats nine.
- **`open-pull-requests-limit`** (5 is sane) stops a first run from flooding you.
- **Weekly, not daily.** Daily creates noise you'll learn to ignore, which is
  worse than no automation.
- **Expect a burst on day one** — the backlog lands at once, then it's quiet.

### Rollout tip
Dependabot's *version* updates (above) are separate from Dependabot **security**
updates (CVE-driven, enabled in repo settings — see §6). You want both.

---

## 3. Security scanning workflow (`.github/workflows/security-scan.yml`)

**Principle: advisory, never blocking.** Keep scanning in its own workflow, and
let jobs report without failing the release pipeline. An upstream CVE
disclosed at 3am (or a scanner outage) must not block shipping a fix. Results
still surface in the Security tab (SARIF) and as PR job status.

```yaml
name: Security scan
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
  schedule:
    - cron: "27 6 * * 1"   # weekly — catches newly-disclosed CVEs in old code

permissions:
  contents: read
  security-events: write   # required to upload SARIF
  actions: read

jobs:
  codeql:            # static analysis; matrix one entry per language
  python-deps:       # pip-audit -r <reqs> --desc     (continue-on-error: true)
  npm-deps:          # npm audit --audit-level=high   (continue-on-error: true)
  dependency-review: # PRs only; fail-on-severity: high (blocks NEW bad deps)
  trivy-fs:          # vuln+misconfig+secret → SARIF upload
  gitleaks:          # secret scan; needs fetch-depth: 0 for full history
  sbom:              # anchore/sbom-action, spdx-json artifact
```

Notes:
- **`continue-on-error: true`** on the audit jobs is the "advisory" lever.
  `dependency-review` is the deliberate exception — it gates *newly introduced*
  vulnerable deps on a PR, which is cheap to act on.
- **Use an odd cron minute** (`27 6 * * 1`) — top-of-hour schedules queue behind
  everyone else's.
- **gitleaks needs `fetch-depth: 0`** or it only scans the tip commit.
- **Pick one repo as the reference implementation** and copy it to the others;
  divergent security configs across siblings is exactly how a repo ends up with
  zero scanning and nobody noticing.

---

## 4. Disclosure policy (`.github/SECURITY.md`)

Short, and it must tell people **not** to open a public issue:

- **Supported versions** — usually "latest only; update before reporting".
- **How to report privately** — the repo's Security tab → *Report a
  vulnerability* (requires private vulnerability reporting enabled, §6), with a
  fallback ("open a minimal issue asking for a private contact, no specifics").
- **What to include** — version, description, reproduction/PoC.
- **Scope notes** — where secrets legitimately live (config/DB the operator
  already controls) versus what is genuinely in scope (auth-gate bypasses,
  privilege/scope escalation). This saves round-trips on "the config file
  contains a password" reports.

---

## 5. CI guardrails

### Concurrency — cancel PR runs, never pushes

```yaml
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}
```

Naive `cancel-in-progress: true` will happily kill a push run on the default
branch mid-flight. If your pipeline bumps a version, builds and publishes
images, or creates a release, cancelling halfway can leave a **bumped version
with no published artifact**. Gate cancellation to `pull_request`.

### Know your release automation before you touch versions

If CI auto-bumps versions on push, learn its **skip marker** before making a
manual version change, and check whether other files must move in lockstep:

- Skip markers differ per repo — e.g. `[skip bump]` in the commit body vs.
  `if: !startsWith(github.event.head_commit.message, 'chore: bump version')`.
  Grep the workflow; don't assume.
- **Version consistency is often validated.** We hit a red CI because an add-on
  `config.yaml` version and the integration `manifest.json` version must match —
  the auto-bump updates both, a hand edit updated one. Grep for the assertion:
  ```bash
  grep -rn "version" .github/workflows/*.yml | grep -i "match\|assert\|mismatch"
  ```
- Racing the bot: if CI pushes its own commit, your local branch goes
  `[ahead 1, behind 1]`. Rebase and resolve — keep your intended version, and
  fold the bot's changelog entry underneath your new section.

---

## 6. Settings-only items (cannot be committed — do these in the UI)

Repo → **Settings → Code security**:

- [ ] **Secret scanning** + **push protection** (blocks committing a live key).
- [ ] **Dependabot security updates** (CVE-driven PRs; distinct from §2).
- [ ] **Private vulnerability reporting** (makes the SECURITY.md path real).
- [ ] **Branch protection** on the default branch: require CI green, no force
      push. ⚠️ If a bot pushes version bumps directly to the default branch,
      either allow that actor or move the bump into a PR first — otherwise you
      break your own release pipeline.
- [ ] Optional: **CODEOWNERS**, a PR template, and pinning actions to commit
      SHAs (highest supply-chain hardening; noisier with Dependabot).

---

## 7. Verify — don't declare done on assumption

```bash
# 1. YAML actually parses (a typo here = silent no-op)
python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" \
  .github/dependabot.yml .github/workflows/*.yml

# 2. Dependabot picked up the config (PRs appear within minutes)
gh pr list --author "app/dependabot" --limit 10

# 3. CI is green — check the workflow BY NAME, not just the latest run
gh run list --workflow "CI/CD" --limit 1 --json status,conclusion
```

**The `--limit 1` trap:** if a repo has several workflows, `gh run list --limit 1`
shows whichever ran most recently — which may be a passing *lint* run while the
*test* workflow is red. We reported "CI green" twice on that basis and were
wrong both times. Always filter `--workflow "<name>"`, and remember the name may
differ per repo (`CI` vs `CI/CD`).

---

## Quick checklist

- [ ] Surveyed every manifest dir + Dockerfile (incl. secondary images)
- [ ] `dependabot.yml`: pip / npm / docker / github-actions, weekly, PR limit
- [ ] Minor+patch grouped; **majors separate**
- [ ] Security workflow: CodeQL, dep audits, dependency-review, Trivy, gitleaks, SBOM
- [ ] Audits advisory (`continue-on-error`); `dependency-review` gates new deps
- [ ] `SECURITY.md` with a private reporting path
- [ ] `concurrency` cancels PR runs only
- [ ] Settings: secret scanning + push protection, Dependabot security updates,
      private vuln reporting, branch protection (mind the release bot)
- [ ] Verified: YAML parses, Dependabot PRs exist, CI green **by workflow name**
