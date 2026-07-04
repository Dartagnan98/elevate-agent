---
name: youtube-listing-thumbnail
description: Create a YouTube thumbnail for a real-estate listing from one or more property photos. Use when the user asks for a YouTube thumbnail, video cover, listing thumbnail, or 16:9 visual for a property tour, especially from Drive-hosted listing photos.
triggers:
  - YouTube thumbnail for a listing
  - thumbnail with listing photos
  - property tour cover image
  - 16:9 listing visual
---

# YouTube Listing Thumbnail

Use this when the user asks for a YouTube thumbnail for a real-estate listing using property photos.

## Workflow

1. **Accept the request as approval to create the asset**
   - If the user provides photo links and the listing/property is clear, do not ask for confirmation.
   - Only ask if required inputs are missing, such as no usable photos or no property/listing identity.

2. **Download source images**
   - For Google Drive file links, extract the file id from `/d/<id>/` and download from:
     - `https://drive.google.com/uc?export=download&id=<id>`
   - If the file is large, preserve cookies and repeat with the `download_warning` confirmation token.
   - Do not assume `requests` is installed. A stdlib `urllib.request` + `http.cookiejar.CookieJar` downloader is reliable.
   - Save to a temp folder such as `/tmp/<property>_thumb/`.

3. **Inspect/verify images**
   - Use `vision_analyze` on the source photos when composition is unclear.
   - Identify which photo should be the hero background and which should be inset/supporting.
   - Typical listing thumbnail pattern:
     - Best exterior/twilight/front photo as the full-background image.
     - Aerial, yard, pool, shop, or standout feature as the second inset photo.

4. **Compose at YouTube size**
   - Output: `1280x720` PNG or high-quality JPG.
   - Use Pillow/PIL if available.
   - If `from PIL import Image` fails after `pip install --user pillow`, install into a temp target and run with `PYTHONPATH`:
     ```bash
     python3 -m pip install pillow -t /tmp/pillow_pkg
     PYTHONPATH=/tmp/pillow_pkg python3 your_script.py
     ```
   - Use cover-crop logic, not distortion, so photos fill their frames cleanly.

5. **Design pattern that reads well for listing thumbnails**
   - Favor a clean, restrained style over a heavy/overdesigned brand-block version — a prior heavier design was disliked in review.
   - Dark left-side gradient over the hero photo for text readability.
   - Clean large address/property text, e.g. the house number and street name stacked.
   - Small top pill for a location/tour label, e.g. `CITY HOME TOUR`.
   - Feature ribbon at bottom listing 2-3 standout features, e.g. `POOL • SHOP • 0.37 ACRE`.
   - Second photo as a bordered, slightly rotated inset card with drop shadow.
   - For brand colours, read the tenant's brand guide (e.g. `knowledge/brand-guide.md` if the tenant has one) for exact tokens rather than guessing hex values. Apply brand colours as restrained accents, pills, ribbons, outlines, or thin bars, not as large heavy blocks over the whole design.
   - If adding a cutout photo of the realtor, place it as a clean sticker-style portrait on the right with a white outline/drop shadow. Avoid making the cutout huge or letting it dominate the property photos.

6. **If a realtor cutout/photo is requested**
   - Prefer the user-provided portrait photo over older local assets.
   - For Google Drive portrait links, direct `uc?export=download` may return a Google sign-in HTML page even when the browser can preview the image. In that case:
     - Open the link with `Browser Use CLI`.
     - Use `Browser Use CLI` to find the Drive viewer preview image, or `Browser Use CLI` to save a screenshot of the preview.
     - If the preview URL cannot be fetched from terminal because of auth/cookies, crop the browser screenshot to isolate the portrait.
   - Use OpenCV GrabCut when available for a better cutout:
     ```bash
     python3 -m pip install -t /tmp/img_pkg numpy opencv-python-headless
     PYTHONPATH=/tmp/pillow_pkg:/tmp/img_pkg python3 make_thumbnail.py
     ```
   - When cutting the realtor out from a screenshot/preview, preserve extra headroom and QA that the head is not cropped. A prior bad attempt cropped too tightly and looked unacceptable.
   - If GrabCut is rough, use it only for an upper-body sticker crop, then add a white outline and shadow so minor edge artifacts are hidden at thumbnail size.

7. **Verify before returning**
   - Use `vision_analyze` on the finished thumbnail.
   - Check:
     - It clearly uses the requested photo(s).
     - Text is legible at a glance.
     - It is 16:9 and 1280x720.
     - No important house/feature content is hidden behind text.
   - Then return the local file as `MEDIA:/path/to/file.png`.

## Pitfalls

- Google Drive photos may be PNG/JPEG regardless of the local extension. PIL can read them, but name files consistently.
- `python3 -m pip install --user pillow` may report success while the runtime `sys.path` does not include the user site-packages. Use `-t /tmp/pillow_pkg` + `PYTHONPATH` if needed.
- Do not over-explain process to the user. Return the completed media and a short note with what was used.

## Example output note

```text
Done, I made a 16:9 YouTube thumbnail with both photos.

MEDIA:/tmp/450-main-street_thumb/450-main-street-youtube-thumbnail.png

I used the front exterior as the main image and the aerial/pool shot as the inset.
```
