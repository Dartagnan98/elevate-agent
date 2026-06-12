# Elevate 1.2.40 — release notes

Quitting the app now means it quits.

## No more app reopening itself after you quit

If an update had downloaded in the background and you quit Elevate, the
updater installed it on the way out and macOS relaunched the new version
immediately — so closing the app appeared to "open a new app that isn't the
one you closed," sometimes without a Dock icon. With releases shipping daily,
an update was staged almost every time you quit, so this looked constant.

Quit now means quit. Updates install when you click the "Restart to update"
card, and if you quit without clicking it, the next launch offers the
already-downloaded update again within seconds — nothing is lost.

## The app always shows in the Dock

An instance relaunched by the updater could come up without a Dock tile, so a
running Elevate didn't show as a live app. Every launch now registers with
the Dock and takes focus properly.
