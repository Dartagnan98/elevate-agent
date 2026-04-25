export function logError(error: unknown): void {
  if (!process.env.ELEVATE_INK_DEBUG_ERRORS) {
    return
  }

  console.error(error)
}
