/**
 * Tail-windowing for the chat transcript render.
 *
 * The transcript renders only the last `size` rows so opening a long chat
 * mounts a bounded number of DOM nodes instead of the whole history. Older
 * rows are revealed on demand by growing `size`. This isolates the (bug-prone)
 * boundary math so it can be unit-tested without the ChatPage mega-component.
 */
export function tailWindow<T>(
  list: readonly T[],
  size: number,
): { items: readonly T[]; hasEarlier: boolean } {
  const hasEarlier = list.length > size;
  return {
    items: hasEarlier ? list.slice(list.length - size) : list,
    hasEarlier,
  };
}
