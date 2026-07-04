---
name: buffer-instagram-draft-with-image
description: Create and verify a Buffer Instagram draft with an image via Buffer's GraphQL API. Use when the user asks to create a Buffer Instagram draft, especially a real-estate social post with an image, and needs a post ID/proof or an exact blocker.
---

# Buffer Instagram Draft With Image

Use when the user asks to create a Buffer Instagram draft, especially for a real-estate social post with an image and they need a post ID/proof or an exact blocker.

## Preconditions

- `BUFFER_TOKEN` is available in the working environment.
- Target channel ID is known. Look up the realtor's configured Instagram channel ID from Buffer (`get_account`/`list_channels`) rather than assuming a value.
- Image URL must be publicly fetchable by Buffer. Prefer a direct JPEG/PNG URL. Verify with `HEAD` before creating the post.

## Steps

1. **Verify the image URL is fetchable**

   ```bash
   python3 - <<'PY'
   import urllib.request
   img='https://example.com/image.jpg'
   req=urllib.request.Request(img, method='HEAD', headers={'User-Agent':'Mozilla/5.0'})
   with urllib.request.urlopen(req, timeout=20) as resp:
       print(resp.status, resp.headers.get('Content-Type'), resp.headers.get('Content-Length'))
   PY
   ```

   Acceptance: HTTP 200 and `Content-Type` starts with `image/`.

2. **Verify Buffer auth and channel**

   ```bash
   set -a; source .env; set +a
   python3 - <<'PY'
   import os,json,urllib.request
   q='{ account { id email channels { id name service } } }'
   req=urllib.request.Request('https://api.buffer.com/', data=json.dumps({'query':q}).encode(), headers={
     'Authorization':'Bearer '+os.environ['BUFFER_TOKEN'],
     'Content-Type':'application/json',
     'User-Agent':'Elevate/1.0'
   })
   with urllib.request.urlopen(req, timeout=30) as resp:
       print(json.dumps(json.loads(resp.read()), indent=2))
   PY
   ```

3. **Create the draft with the current Buffer GraphQL asset shape**

   Current working shape is a list of `AssetInput` objects:

   ```json
   "assets": [{ "image": { "url": "https://example.com/image.jpg" } }]
   ```

   Do **not** use the stale wrapper shape:

   ```json
   "assets": { "images": [{ "url": "https://example.com/image.jpg" }] }
   ```

   That stale shape fails with `Field images is not defined by type AssetInput`.

   Minimal create mutation:

   ```graphql
   mutation CreatePost($input: CreatePostInput!) {
     createPost(input: $input) {
       __typename
       ... on PostActionSuccess {
         post { id status dueAt text channel { id service name } }
       }
       ... on MutationError { message }
       ... on RestProxyError { message code link }
     }
   }
   ```

   Input requirements for an Instagram feed draft:

   ```json
   {
     "channelId": "<buffer-instagram-channel-id>",
     "text": "caption",
     "schedulingType": "automatic",
     "mode": "customScheduled",
     "dueAt": "YYYY-MM-DDTHH:mm:ss-07:00",
     "assets": [{ "image": { "url": "https://example.com/image.jpg" } }],
     "source": "marketing-agent",
     "saveToDraft": true,
     "metadata": {
       "instagram": {
         "type": "post",
         "shouldShareToFeed": true
       }
     }
   }
   ```

4. **Verify by querying the post back, including assets**

   ```graphql
   query GetPost($id: PostId!) {
     post(input: {id: $id}) {
       id
       status
       dueAt
       channel { id service name }
       assets {
         __typename
         id
         type
         mimeType
         source
         thumbnail
         ... on ImageAsset { image { width height altText isAnimated } }
       }
     }
   }
   ```

   Acceptance:
   - `status` is `draft`.
   - Channel is the requested Instagram channel.
   - `assets[0].__typename` is `ImageAsset`.
   - `mimeType` is an image MIME type.
   - `source` matches the intended image URL.

5. **Visual preview gate for the realtor's social graphics**

   Before reporting a Buffer/Instagram/Facebook graphic draft as ready, capture or assemble a visual proof:

   - exported image/contact sheet from the local graphic files;
   - platform preview/crop screenshot through local/free Browser Use CLI when available;
   - reference source used, e.g. an approved brand template, user-provided screenshot, or previous approved asset;
   - comparison notes for logo size/placement, type, colours, crop, CTA, stale price/date/MLS/open-house language, approved photo source, and off-brand flyer-style elements.

   Save the screenshot/contact sheet and a compact proof JSON/MD beside the draft artifact. API success and attached-image verification alone are not enough to call the visual package ready.

## Reporting back

Return:

- Buffer post ID.
- Status.
- Channel name and ID.
- Proof that the image attached, including MIME type, dimensions, and source URL if available.
- If blocked, return the exact HTTP/GraphQL error and the step where it occurred.

## Pitfalls

- Buffer's GraphQL schema can drift. If a known-good mutation fails, introspect `CreatePostInput`, `AssetInput`, `ImageAssetInput`, `PostInputMetaData`, and `InstagramPostMetadataInput` before guessing.
- Old Buffer REST endpoints reject OIDC tokens. Use `https://api.buffer.com/` GraphQL with `Authorization: Bearer $BUFFER_TOKEN`.
- `saveToDraft: true` prevents publishing/scheduling, but Buffer still accepts and stores a `dueAt` when using `customScheduled` mode.
- For Instagram, include `metadata.instagram.type = "post"` and `shouldShareToFeed = true`.
