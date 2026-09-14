// @vitest-environment happy-dom
// @vitest-environment-options {"settings":{"disableCSSFileLoading":true,"disableJavaScriptFileLoading":true}}
import { describe, expect, it } from "vitest";
import { localAssetPath, mergePreviewArtifacts, prepareHtmlPreview } from "../artifactPreview";

describe("local draft preview", () => {
  it("does not evict recent drafts when a full file inventory loads again", () => {
    const inventory = Array.from({ length: 100 }, (_, i) => ({ key: `server:${i}`, path: `/work/${i}.html`, createdAt: i }));
    const first = mergePreviewArtifacts([], inventory, 32);
    expect(mergePreviewArtifacts(first, inventory, 32)).toEqual(first);
    expect(first.at(-1)?.path).toBe('/work/99.html');
    const duplicate = { ...inventory[99], key: 'different-message-id' };
    expect(mergePreviewArtifacts(first, [duplicate], 32)).toHaveLength(32);
  });
  it("resolves relative, absolute and percent-encoded file assets", () => {
    expect(localAssetPath("../images/a%20b.png", "/work/site/index.html")).toBe("/work/images/a b.png");
    expect(localAssetPath("file:///work/a%20b.jpg", "/work/index.html")).toBe("/work/a b.jpg");
    expect(localAssetPath("https://example.com/a.png", "/work/index.html")).toBeNull();
    expect(localAssetPath("file://remote/a.png", "/work/index.html")).toBeNull();
  });
  it("embeds authenticated images and stylesheet assets without granting scripts", async () => {
    const calls: string[] = [];
    const result = await prepareHtmlPreview('<html><head><link rel="stylesheet" href="styles/main.css"><script>alert(1)</script></head><body onload="alert(1)"><img src="file:///work/a%20b.png"><img src="a%20b.png"></body></html>', "/work/index.html", async path => {
      calls.push(path);
      return path.endsWith(".css") ? new Blob(['body {background: url("../bg.png")}'], { type: "text/css" }) : new Blob(["image"], { type: "image/png" });
    });
    expect(calls).toEqual(["/work/a b.png", "/work/styles/main.css", "/work/bg.png"]);
    expect(result.html).toContain("data:image/png;base64,");
    expect(result.html).toContain('charset="utf-8"');
    expect(result.html).not.toContain("file://");
    expect(result.html).not.toContain("<script");
    expect(result.html).not.toContain("onload");
    expect(result.missingAssets).toBe(0);
  });
  it("shows the rest of a draft when an image is missing", async () => {
    const result = await prepareHtmlPreview('<h1>Draft copy</h1><img src="missing.png">', "/work/index.html", async () => { throw new Error("404"); });
    expect(result.html).toContain("Draft copy");
    expect(result.missingAssets).toBe(1);
  });
  it("stops preparing a preview when the user switches files", async () => {
    await expect(prepareHtmlPreview('<img src="a.png">', "/work/index.html", async () => { throw new DOMException("Aborted", "AbortError"); })).rejects.toThrow("Aborted");
  });
});
