import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { Markdown } from "../Markdown";

function render(content: string): string {
  return renderToStaticMarkup(
    createElement(Markdown, { content, onOpenPath: () => undefined }),
  );
}

describe("Markdown path links", () => {
  it("does not make slash-delimited prose fragments interactive", () => {
    const html = render(
      "mid/end ready/live release/push sessions/visits SMS/email/Meta/Google",
    );

    expect(html).not.toContain("data-md-path");
  });

  it("keeps intentional local paths interactive", () => {
    const html = render(
      "Open /Users/me/contracts, ~/Documents/offer.pdf, ./src/App.tsx, and cli/web/src/Markdown.tsx.",
    );

    expect(html.match(/data-md-path=/g)).toHaveLength(4);
  });
});
