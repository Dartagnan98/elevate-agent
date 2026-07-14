import { beforeEach, describe, expect, it } from 'vitest'

import {
  advanceApprovalQueue,
  isStaleApprovalResponseError,
  patchOverlayState,
  resetFlowOverlays,
  resetOverlayState
} from '../app/overlayStore.js'

describe('approval overlay identity', () => {
  beforeEach(() => resetOverlayState())

  it('advances a terminal approval without dropping later work', () => {
    patchOverlayState({
      approval: { command: 'first', description: 'first', requestId: 'first' },
      approvalQueue: [
        { command: 'second', description: 'second', requestId: 'second' },
        { command: 'third', description: 'third', requestId: 'third' }
      ]
    })

    resetFlowOverlays('first')

    expect(advanceApprovalQueue('stale')).toEqual({ advanced: false, hasNext: true })
    expect(advanceApprovalQueue('second')).toEqual({ advanced: true, hasNext: true })
    expect(advanceApprovalQueue('third')).toEqual({ advanced: true, hasNext: false })
  })

  it('recognizes only stale approval protocol errors', () => {
    expect(isStaleApprovalResponseError(new Error('no pending approval request'))).toBe(true)
    expect(isStaleApprovalResponseError(new Error('approval request id is required'))).toBe(true)
    expect(isStaleApprovalResponseError(new Error('gateway disconnected'))).toBe(false)
  })
})
