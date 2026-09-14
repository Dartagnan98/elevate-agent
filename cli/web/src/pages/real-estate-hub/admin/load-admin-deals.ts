import type { AdminDeal, AdminDealsResponse } from "@/lib/api-types";

// The endpoint's count is the page length, not the total number of deals.
export async function loadAllAdminDeals(fetchPage: (params: { status: null; limit: number; offset: number }) => Promise<AdminDealsResponse>): Promise<AdminDeal[]> {
  const items = new Map<string, AdminDeal>();
  const limit = 200;
  for (let offset = 0; ; offset += limit) {
    const page = await fetchPage({ status: null, limit, offset });
    const before = items.size;
    for (const deal of page.items) if (!items.has(deal.id)) items.set(deal.id, deal);
    if (page.items.length < limit) return [...items.values()];
    // Fail visibly if an upstream implementation ignores offset.
    if (items.size === before) throw new Error("The deal list could not finish loading. Please retry.");
  }
}
