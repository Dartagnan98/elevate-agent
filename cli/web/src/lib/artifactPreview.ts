/** Resolve local HTML resources through the authenticated file API, never file://. */
export function mergePreviewArtifacts<T extends { key: string; path?: string; createdAt: number }>(previous: T[], incoming: T[], limit: number): T[] {
  const byIdentity = new Map<string, T>();
  for (const item of [...previous, ...incoming]) byIdentity.set(item.path ? `file:${item.path}` : item.key, item);
  return [...byIdentity.values()].sort((a, b) => a.createdAt - b.createdAt || (a.path || a.key).localeCompare(b.path || b.key)).slice(-limit);
}

export function localAssetPath(reference: string, documentPath: string): string | null {
  const value = reference.trim();
  if (!value || value.startsWith("#") || /^(?:data|blob|https?|mailto|tel|javascript):/i.test(value) || value.startsWith("//")) return null;
  try {
    const base = documentPath.startsWith("file:") ? documentPath : `file://${documentPath.startsWith("/") ? "" : "/"}${documentPath}`;
    const url = new URL(value, base);
    return url.protocol === "file:" && (!url.hostname || url.hostname === "localhost") ? decodeURIComponent(url.pathname) : null;
  } catch { return null; }
}

function dataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(new Error("Could not read preview image"));
    reader.readAsDataURL(blob);
  });
}

export async function prepareHtmlPreview(
  html: string,
  documentPath: string,
  fetchAsset: (path: string) => Promise<Blob>,
): Promise<{ html: string; missingAssets: number }> {
  const doc = new DOMParser().parseFromString(html, "text/html");
  // Blob navigation has no HTTP charset header; always declare the UTF-8
  // encoding used by Blob so punctuation and accented names stay readable.
  doc.querySelectorAll("meta[charset]").forEach(el => el.remove());
  const charset = doc.createElement("meta");
  charset.setAttribute("charset", "utf-8");
  doc.head.prepend(charset);
  const assets = new Map<string, string>();
  let totalBytes = 0;
  let missingAssets = 0;
  // A draft is a visual preview. Keep scripts, refreshes and base URL overrides
  // from redirecting it or turning an external-open action into application code.
  doc.querySelectorAll("script, base, meta[http-equiv], iframe, object, embed").forEach(el => el.remove());
  doc.querySelectorAll("*").forEach(el => {
    for (const attr of [...el.attributes]) {
      if (/^on/i.test(attr.name) || /^(?:javascript|vbscript):/i.test(attr.value.trim())) el.removeAttribute(attr.name);
    }
  });
  const embed = async (reference: string, base: string): Promise<string> => {
    const path = localAssetPath(reference, base);
    if (!path) return reference;
    if (assets.has(path)) return assets.get(path)!;
    try {
      if (assets.size >= 80 || totalBytes >= 24 * 1024 * 1024) throw new Error("Preview asset budget reached");
      const blob = await fetchAsset(path);
      if (!/^(?:image\/|font\/|application\/(?:font|x-font|vnd.ms-fontobject))/.test(blob.type)) throw new Error("Unsupported preview asset");
      if (totalBytes + blob.size > 24 * 1024 * 1024) throw new Error("Preview asset budget reached");
      totalBytes += blob.size;
      const value = await dataUrl(blob);
      assets.set(path, value);
      return value;
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      missingAssets += 1;
      assets.set(path, "");
      return "";
    }
  };
  const css = async (text: string, base: string): Promise<string> => {
    const matches = [...text.matchAll(/url\(\s*(['"]?)(.*?)\1\s*\)/gi)];
    for (const match of matches) text = text.replace(match[0], `url("${await embed(match[2], base)}")`);
    return text;
  };
  for (const el of doc.querySelectorAll("img[src], source[src], video[poster], input[type=image][src]")) {
    const attr = el.hasAttribute("poster") ? "poster" : "src";
    el.setAttribute(attr, await embed(el.getAttribute(attr)!, documentPath));
  }
  for (const el of doc.querySelectorAll("[srcset]")) {
    const set = el.getAttribute("srcset")!;
    if (set.trim().startsWith("data:")) continue;
    const entries = [];
    for (const part of set.split(",")) {
      const [url, ...descriptor] = part.trim().split(/\s+/);
      const resolved = await embed(url, documentPath);
      if (resolved) entries.push([resolved, ...descriptor].join(" "));
    }
    el.setAttribute("srcset", entries.join(", "));
  }
  for (const link of doc.querySelectorAll('link[rel="stylesheet"][href]')) {
    const path = localAssetPath(link.getAttribute("href")!, documentPath);
    if (!path) continue;
    try {
      const blob = await fetchAsset(path);
      if (!blob.type.startsWith("text/css") || blob.size > 1024 * 1024) throw new Error("Unsupported stylesheet");
      const style = doc.createElement("style");
      style.textContent = await css(await blob.text(), path);
      link.replaceWith(style);
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") throw error;
      missingAssets += 1;
      link.remove();
    }
  }
  for (const style of doc.querySelectorAll("style")) style.textContent = await css(style.textContent ?? "", documentPath);
  for (const el of doc.querySelectorAll("[style]")) el.setAttribute("style", await css(el.getAttribute("style")!, documentPath));
  return { html: `<!doctype html>\n${doc.documentElement.outerHTML}`, missingAssets };
}
