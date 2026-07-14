export type ApprovalChoice = 'always' | 'deny' | 'once' | 'session'

export function exactRealtorBetaRelease(channel = process.env.ELEVATE_RELEASE_CHANNEL): boolean {
  return channel === 'beta'
}

export function approvalChoicesForRelease(
  channel = process.env.ELEVATE_RELEASE_CHANNEL
): readonly ApprovalChoice[] {
  return exactRealtorBetaRelease(channel)
    ? (['once', 'deny'] as const)
    : (['once', 'session', 'always', 'deny'] as const)
}

export function approvalBypassAvailable(channel = process.env.ELEVATE_RELEASE_CHANNEL): boolean {
  return !exactRealtorBetaRelease(channel)
}

export function isApprovalBypassCommand(command: string): boolean {
  return command.trim().replace(/^\//, '').split(/\s+/, 1)[0]?.toLowerCase() === 'yolo'
}

export function filterApprovalCompletions<T extends { text: string }>(
  items: readonly T[],
  channel = process.env.ELEVATE_RELEASE_CHANNEL
): T[] {
  if (approvalBypassAvailable(channel)) {
    return [...items]
  }

  return items.filter(item => !isApprovalBypassCommand(item.text))
}
