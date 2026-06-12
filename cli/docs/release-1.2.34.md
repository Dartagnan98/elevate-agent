# Elevate 1.2.34 — release notes

The dashboard always loads the current build.

## No more blank dashboard / broken icons after an update

After an update, the previous version's dashboard process could keep running
in the background, and the freshly-updated app would attach to it — loading a
page that referenced files the old process no longer had. The result was a
blank dashboard or broken toolbar icons (search, collapse) until a full
restart.

The app now fingerprints the running dashboard against the build it shipped
with. If they don't match, it shuts the stale one down and starts a fresh
dashboard on the correct build automatically — no manual restart needed.
