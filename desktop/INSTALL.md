# Installing Elevate on Mac

Quick guide for first-time install. Takes about 2 minutes.

## 1. Download

Grab the `.dmg` that matches your Mac:

- **Apple Silicon** (M1, M2, M3, M4): `Elevate-0.14.0-mac-arm64.dmg`
- **Intel Mac**: `Elevate-0.14.0-mac-x64.dmg`

Not sure which one you have? Click the Apple menu (top-left) → About This Mac. If it says "Apple M1/M2/M3/M4" pick arm64. If it says "Intel" pick x64.

## 2. Install

1. Double-click the `.dmg` file you downloaded.
2. A window opens showing the Elevate icon and an Applications folder shortcut.
3. Drag **Elevate** onto the **Applications** folder.
4. Wait for the copy to finish (a few seconds).
5. Eject the disk image (right-click the Elevate disk on your desktop → Eject).

## 3. First Launch (Important)

Because this app is not yet signed by Apple, the first launch needs one extra step. After that, it opens normally forever.

1. Open Finder → Applications.
2. Find **Elevate**.
3. **Right-click** (or Control-click) on Elevate → choose **Open**.
4. A dialog warns "Apple could not verify Elevate is free of malware." Click **Open Anyway** (or **Open**).
5. Elevate launches.

If the dialog only gives you a Cancel button:
- Open System Settings → Privacy & Security.
- Scroll down. You will see "Elevate was blocked..." with an **Open Anyway** button.
- Click it, then launch Elevate normally.

You only do this once. Future launches just need a double-click.

## 4. Updating Later

Auto-updates are off in this build. When a new version ships, you will get a download link. Repeat steps 1 to 3 to install over the old one. Your data stays put.

## Troubleshooting

**"Elevate is damaged and cannot be opened"** — macOS quarantine flag got stuck. Open Terminal and run:

```
xattr -dr com.apple.quarantine /Applications/Elevate.app
```

Then launch Elevate normally.

**App will not open at all** — send your Elevate support contact a screenshot of what you see.
