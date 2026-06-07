import { useEffect } from "react";

function looksIconOnly(element: Element): boolean {
  const text = (element.textContent || "").trim();
  if (!text) return true;
  if (text.length <= 2 && !/[A-Za-z0-9]/.test(text)) return true;
  return false;
}

function applyIconButtonTitles(root: ParentNode = document): void {
  const candidates = root.querySelectorAll<HTMLElement>(
    'button[aria-label]:not([title]), [role="button"][aria-label]:not([title])',
  );
  for (const element of candidates) {
    if (!looksIconOnly(element)) continue;
    const label = element.getAttribute("aria-label");
    if (label) element.setAttribute("title", label);
  }
}

export function useIconButtonTitles(): void {
  useEffect(() => {
    applyIconButtonTitles();
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "attributes") {
          const target = mutation.target;
          if (target instanceof HTMLElement) {
            const label = target.getAttribute("aria-label");
            if (label && !target.getAttribute("title") && looksIconOnly(target)) {
              target.setAttribute("title", label);
            }
          }
          continue;
        }
        for (const node of mutation.addedNodes) {
          if (node instanceof HTMLElement) applyIconButtonTitles(node);
        }
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["aria-label", "title"],
    });
    return () => observer.disconnect();
  }, []);
}
