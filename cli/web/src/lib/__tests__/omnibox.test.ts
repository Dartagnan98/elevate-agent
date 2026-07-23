import { describe, expect, it } from "vitest";

import {
  browserTarget,
  buildSuggestions,
  historyScore,
  isHostShaped,
  isUrlShaped,
  middleTruncate,
  normalizeUrlKey,
  parseHistory,
  recordVisit,
  retitleVisit,
  searchUrl,
  suggestionTitle,
  type OmniboxHistoryEntry,
} from "../omnibox";

const NOW = 1_800_000_000_000;

function entry(overrides: Partial<OmniboxHistoryEntry> = {}): OmniboxHistoryEntry {
  return {
    url: "https://example.com/",
    title: "Example",
    count: 1,
    lastVisited: NOW,
    ...overrides,
  };
}

describe("host-shaped detection", () => {
  it("treats a single bare word as host-shaped", () => {
    expect(isHostShaped("youtube")).toBe(true);
    expect(isHostShaped("  youtube  ")).toBe(true);
    expect(isHostShaped("web-app")).toBe(true);
  });

  it("rejects phrases, dotted hosts, numbers, and malformed labels", () => {
    expect(isHostShaped("you tube")).toBe(false);
    expect(isHostShaped("youtube.com")).toBe(false); // already URL-shaped
    expect(isHostShaped("42")).toBe(false); // bare number reads as a search
    expect(isHostShaped("-bad")).toBe(false);
    expect(isHostShaped("bad-")).toBe(false);
    expect(isHostShaped("")).toBe(false);
  });
});

describe("URL-shaped detection", () => {
  it("accepts explicit URLs, dotted hosts, localhost, and IPv4", () => {
    expect(isUrlShaped("https://youtube.com")).toBe(true);
    expect(isUrlShaped("youtube.com")).toBe(true);
    expect(isUrlShaped("youtube.com/watch?v=abc")).toBe(true);
    expect(isUrlShaped("localhost:3000")).toBe(true);
    expect(isUrlShaped("127.0.0.1:8080")).toBe(true);
  });

  it("rejects bare words, phrases, and non-web schemes", () => {
    expect(isUrlShaped("youtube")).toBe(false);
    expect(isUrlShaped("pizza near me")).toBe(false);
    expect(isUrlShaped("mailto:x@y.com")).toBe(false);
  });
});

describe("browserTarget", () => {
  it("navigates host-shaped input directly instead of searching Google", () => {
    // The captcha fix: "youtube" must never build a google.com/search URL.
    expect(browserTarget("youtube")).toBe("https://youtube.com");
    expect(browserTarget("Youtube")).toBe("https://youtube.com");
  });

  it("passes URLs and dotted hosts through", () => {
    expect(browserTarget("https://youtube.com/feed")).toBe("https://youtube.com/feed");
    expect(browserTarget("youtube.com")).toBe("https://youtube.com");
    expect(browserTarget("localhost:5173/app")).toBe("https://localhost:5173/app");
  });

  it("falls back to a plain Google search URL only for non-host input", () => {
    expect(browserTarget("pizza near me")).toBe(
      "https://www.google.com/search?q=pizza%20near%20me",
    );
    expect(browserTarget("404")).toBe("https://www.google.com/search?q=404");
  });

  it("keeps the search URL free of extra params", () => {
    const url = new URL(searchUrl("youtube"));
    expect(url.origin + url.pathname).toBe("https://www.google.com/search");
    expect([...url.searchParams.keys()]).toEqual(["q"]);
  });

  it("maps empty and about:blank input to about:blank", () => {
    expect(browserTarget("")).toBe("about:blank");
    expect(browserTarget("about:blank")).toBe("about:blank");
  });
});

describe("normalizeUrlKey", () => {
  it("collapses scheme, www, trailing slash, and hash variants", () => {
    const variants = [
      "https://www.youtube.com/",
      "http://youtube.com",
      "https://youtube.com/#top",
      "https://YOUTUBE.com/",
    ];
    const keys = new Set(variants.map(normalizeUrlKey));
    expect(keys.size).toBe(1);
    expect([...keys][0]).toBe("youtube.com");
  });

  it("keeps distinct queries distinct", () => {
    expect(normalizeUrlKey("https://g.com/search?q=a")).not.toBe(
      normalizeUrlKey("https://g.com/search?q=b"),
    );
  });
});

describe("title fallback and truncation", () => {
  it("uses the recorded page title when present", () => {
    expect(suggestionTitle(entry({ title: "YouTube" }))).toBe("YouTube");
  });

  it("falls back to hostname+path when the title is missing", () => {
    expect(
      suggestionTitle(entry({ title: "", url: "https://www.youtube.com/feed/history" })),
    ).toBe("youtube.com/feed/history");
    expect(suggestionTitle(entry({ title: "", url: "https://youtube.com/" }))).toBe(
      "youtube.com",
    );
  });

  it("middle-truncates long fallbacks so host and tail survive", () => {
    const long = `https://example.com/${"a".repeat(200)}/report-final.pdf`;
    const title = suggestionTitle(entry({ title: "", url: long }), 40);
    expect(title.length).toBeLessThanOrEqual(40);
    expect(title).toContain("…");
    expect(title.startsWith("example.com/")).toBe(true);
    expect(title.endsWith("final.pdf")).toBe(true);
  });

  it("middleTruncate leaves short strings alone", () => {
    expect(middleTruncate("youtube.com", 64)).toBe("youtube.com");
  });
});

describe("buildSuggestions", () => {
  it("injects the direct .com navigation first for host-shaped input, search second", () => {
    const rows = buildSuggestions("youtube", [], { now: NOW });
    expect(rows[0]).toMatchObject({ kind: "navigate", url: "https://youtube.com" });
    expect(rows[0].title).toBe("youtube.com");
    expect(rows[1]).toMatchObject({ kind: "search" });
    expect(rows[1].title).toBe('Search Google for "youtube"');
    expect(rows[1].url).toBe(searchUrl("youtube"));
  });

  it("puts the search row first when input is not URL- or host-shaped", () => {
    const rows = buildSuggestions("open houses this weekend", [], { now: NOW });
    expect(rows[0].kind).toBe("search");
    expect(rows[0].title).toBe('Search Google for "open houses this weekend"');
  });

  it("puts direct navigation first for URL-shaped input without appending .com", () => {
    const rows = buildSuggestions("youtube.com", [], { now: NOW });
    expect(rows[0]).toMatchObject({ kind: "navigate", url: "https://youtube.com" });
    expect(rows.some((row) => row.url.includes("youtube.com.com"))).toBe(false);
  });

  it("dedupes history rows by normalized URL", () => {
    const historyEntries = [
      entry({ url: "https://www.youtube.com/", title: "YouTube", count: 3 }),
      entry({ url: "http://youtube.com", title: "", count: 1 }),
      entry({ url: "https://youtube.com/#top", title: "YouTube", count: 2 }),
    ];
    const rows = buildSuggestions("youtu", historyEntries, { now: NOW });
    const historyRows = rows.filter((row) => row.kind === "history");
    expect(historyRows).toHaveLength(1);
    expect(historyRows[0].title).toBe("YouTube");
  });

  it("dedupes a history row against the primary navigation row", () => {
    const rows = buildSuggestions(
      "youtube",
      [entry({ url: "https://www.youtube.com/", title: "YouTube" })],
      { now: NOW },
    );
    const targets = rows.map((row) => normalizeUrlKey(row.url));
    expect(new Set(targets).size).toBe(targets.length);
  });

  it("ranks history matches by frequency and recency", () => {
    const historyEntries = [
      entry({ url: "https://a.example.com/", title: "Stale", count: 1, lastVisited: NOW - 30 * 86_400_000 }),
      entry({ url: "https://b.example.com/", title: "Frequent", count: 20, lastVisited: NOW - 86_400_000 }),
      entry({ url: "https://c.example.com/", title: "Fresh", count: 2, lastVisited: NOW }),
    ];
    const rows = buildSuggestions("example", historyEntries, { now: NOW });
    const titles = rows.filter((row) => row.kind === "history").map((row) => row.title);
    expect(titles[0]).toBe("Frequent");
    expect(titles[titles.length - 1]).toBe("Stale");
  });

  it("only surfaces recorded history — nothing fabricated", () => {
    const historyEntries = [entry({ url: "https://real.example.com/", title: "Real" })];
    const rows = buildSuggestions("real", historyEntries, { now: NOW });
    for (const row of rows.filter((r) => r.kind === "history")) {
      expect(historyEntries.some((h) => h.url === row.url)).toBe(true);
    }
  });

  it("shows top-ranked recents for empty input and respects the limit", () => {
    const historyEntries = Array.from({ length: 10 }, (_, i) =>
      entry({ url: `https://site${i}.example.com/`, title: `Site ${i}`, count: i + 1 }),
    );
    const rows = buildSuggestions("", historyEntries, { now: NOW, limit: 4 });
    expect(rows).toHaveLength(4);
    expect(rows.every((row) => row.kind === "history")).toBe(true);
    expect(rows[0].title).toBe("Site 9");
  });

  it("gives every history row a title and a secondary URL detail", () => {
    const rows = buildSuggestions(
      "no-title",
      [entry({ url: "https://no-title.example.com/path", title: "" })],
      { now: NOW },
    );
    const row = rows.find((r) => r.kind === "history");
    expect(row?.title).toBe("no-title.example.com/path");
    expect(row?.detail).toBe("no-title.example.com/path");
  });
});

describe("history recording", () => {
  it("increments count for repeat visits to the same normalized URL", () => {
    let historyEntries = recordVisit([], { url: "https://www.youtube.com/", title: "", now: NOW - 1000 });
    historyEntries = recordVisit(historyEntries, { url: "https://youtube.com", title: "YouTube", now: NOW });
    expect(historyEntries).toHaveLength(1);
    expect(historyEntries[0]).toMatchObject({ count: 2, title: "YouTube", lastVisited: NOW });
  });

  it("ignores non-http(s) URLs", () => {
    expect(recordVisit([], { url: "about:blank", now: NOW })).toEqual([]);
    expect(recordVisit([], { url: "file:///tmp/x", now: NOW })).toEqual([]);
  });

  it("retitles without bumping the count and keeps identity when unchanged", () => {
    const base = [entry({ url: "https://youtube.com/", title: "", count: 5 })];
    const retitled = retitleVisit(base, "https://www.youtube.com/", "YouTube");
    expect(retitled[0]).toMatchObject({ title: "YouTube", count: 5 });
    expect(retitleVisit(retitled, "https://youtube.com/", "YouTube")).toBe(retitled);
    expect(retitleVisit(base, "https://youtube.com/", "")).toBe(base);
  });

  it("caps stored history by keeping the best-scoring entries", () => {
    let historyEntries: OmniboxHistoryEntry[] = [];
    for (let i = 0; i < 5; i += 1) {
      historyEntries = recordVisit(
        historyEntries,
        { url: `https://site${i}.example.com/`, title: `S${i}`, now: NOW - i * 1000 },
        3,
      );
    }
    expect(historyEntries).toHaveLength(3);
  });

  it("historyScore prefers recent and frequent entries", () => {
    const fresh = entry({ count: 2, lastVisited: NOW });
    const stale = entry({ count: 2, lastVisited: NOW - 10 * 86_400_000 });
    expect(historyScore(fresh, NOW)).toBeGreaterThan(historyScore(stale, NOW));
  });
});

describe("parseHistory", () => {
  it("keeps only well-formed http(s) entries", () => {
    const parsed = parseHistory([
      { url: "https://a.example.com/", title: "A", count: 2, lastVisited: NOW },
      { url: "javascript:alert(1)", title: "x", count: 1, lastVisited: NOW },
      { url: "https://b.example.com/", title: 42, count: "nope", lastVisited: "later" },
      "garbage",
      null,
    ]);
    expect(parsed).toHaveLength(2);
    expect(parsed[0]).toMatchObject({ url: "https://a.example.com/", count: 2 });
    expect(parsed[1]).toMatchObject({ url: "https://b.example.com/", title: "", count: 1, lastVisited: 0 });
  });

  it("returns empty for non-arrays", () => {
    expect(parseHistory("{}")).toEqual([]);
    expect(parseHistory(null)).toEqual([]);
  });
});
