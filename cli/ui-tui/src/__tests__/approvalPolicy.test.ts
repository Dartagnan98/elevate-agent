import { describe, expect, it } from 'vitest'

import {
  approvalBypassAvailable,
  approvalChoicesForRelease,
  exactRealtorBetaRelease,
  filterApprovalCompletions,
  isApprovalBypassCommand
} from '../domain/approval.js'

describe('approval UI policy', () => {
  it('restricts only the exact lowercase Realtor Beta channel', () => {
    expect(exactRealtorBetaRelease('beta')).toBe(true)
    expect(exactRealtorBetaRelease('Beta')).toBe(false)
    expect(exactRealtorBetaRelease('stable')).toBe(false)
  })

  it('offers only one-request allow and deny in Realtor Beta', () => {
    expect(approvalChoicesForRelease('beta')).toEqual(['once', 'deny'])
    expect(approvalBypassAvailable('beta')).toBe(false)
  })

  it('leaves Stable and case-mismatched Beta approval choices unchanged', () => {
    const expected = ['once', 'session', 'always', 'deny']

    expect(approvalChoicesForRelease('stable')).toEqual(expected)
    expect(approvalChoicesForRelease('Beta')).toEqual(expected)
    expect(approvalBypassAvailable('stable')).toBe(true)
    expect(approvalBypassAvailable('Beta')).toBe(true)
  })

  it('removes yolo from exact-Beta completion results only', () => {
    const items = [
      { display: '/help', text: 'help' },
      { display: '/yolo', text: 'yolo' },
      { display: '/model', text: 'model' }
    ]

    expect(isApprovalBypassCommand('/YOLO on')).toBe(true)
    expect(filterApprovalCompletions(items, 'beta').map(item => item.text)).toEqual(['help', 'model'])
    expect(filterApprovalCompletions(items, 'stable')).toEqual(items)
    expect(filterApprovalCompletions(items, 'Beta')).toEqual(items)
  })
})
