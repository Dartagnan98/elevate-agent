# Elevate NPM Bootstrap

This folder contains the public NPM bootstrap package for Elevate Agent.

The package is intentionally small. It installs an `elevate` command that can:

- run `elevate install` to bootstrap the local Python runtime;
- forward normal commands to the installed local Elevate CLI;
- keep the base installer public while paid real estate packs stay licensed.

## Local Smoke Test

```bash
cd cli/packaging/npm/elevate
npm pack --dry-run
node bin/elevate.js --help
node bin/elevate.js install --dry-run --skip-setup
```

## Publish

The package must be published to NPM before this works:

```bash
npx @elevationrealestate/elevate install
```

Local publish:

```bash
cd cli/packaging/npm/elevate
npm login
npm publish --access public
```

GitHub Actions publish:

1. Create an NPM automation token with publish access.
2. Add it to the GitHub repo as `NPM_TOKEN`.
3. Run the "Publish NPM bootstrap" workflow manually, or push a tag:

   ```bash
   git tag npm-v0.11.0
   git push origin npm-v0.11.0
   ```

After publish, verify:

```bash
npm view @elevationrealestate/elevate version
npx @elevationrealestate/elevate install --help
```

For private beta builds, pass a GitHub token through the environment:

```bash
ELEVATE_GITHUB_TOKEN="$(gh auth token)" npx @elevationrealestate/elevate install
```
