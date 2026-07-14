import { atom, computed } from 'nanostores'

import type { OverlayState } from './interfaces.js'

const buildOverlayState = (): OverlayState => ({
  agents: false,
  agentsInitialHistoryIndex: 0,
  approval: null,
  approvalQueue: [],
  clarify: null,
  confirm: null,
  modelPicker: false,
  pager: null,
  picker: false,
  secret: null,
  skillsHub: false,
  sudo: null
})

export const $overlayState = atom<OverlayState>(buildOverlayState())

export const $isBlocked = computed(
  $overlayState,
  ({ agents, approval, clarify, confirm, modelPicker, pager, picker, secret, skillsHub, sudo }) =>
    Boolean(agents || approval || clarify || confirm || modelPicker || pager || picker || secret || skillsHub || sudo)
)

export const getOverlayState = () => $overlayState.get()

export const patchOverlayState = (next: Partial<OverlayState> | ((state: OverlayState) => OverlayState)) =>
  $overlayState.set(typeof next === 'function' ? next($overlayState.get()) : { ...$overlayState.get(), ...next })

export const advanceApprovalQueue = (requestId: string) => {
  const state = $overlayState.get()

  if (!state.approval || state.approval.requestId !== requestId) {
    return { advanced: false, hasNext: Boolean(state.approval) }
  }

  const [approval = null, ...approvalQueue] = state.approvalQueue

  $overlayState.set({ ...state, approval, approvalQueue })

  return { advanced: true, hasNext: Boolean(approval) }
}

/** Full reset — used by session/turn teardown and tests. */
export const resetOverlayState = () => $overlayState.set(buildOverlayState())

/**
 * Soft reset: drop FLOW-scoped overlays (approval / clarify / confirm / sudo
 * / secret / pager) but PRESERVE user-toggled ones — agents dashboard, model
 * picker, skills hub, session picker.  Those are opened deliberately and
 * shouldn't vanish when a turn ends.  Called from turnController.idle() on
 * every turn completion / interrupt; the old "reset everything" behaviour
 * silently closed /agents the moment delegation finished.
 */
export const resetFlowOverlays = (terminalApprovalRequestId = '') => {
  const current = $overlayState.get()
  let approval: OverlayState['approval'] = null
  let approvalQueue = [] as OverlayState['approvalQueue']

  // A terminal frame makes the currently visible approval stale, but later
  // concurrent approvals are still real work. Advance only when the terminal
  // identity matches; a mismatched late frame cannot consume anything.
  if (terminalApprovalRequestId) {
    if (current.approval?.requestId === terminalApprovalRequestId) {
      const [nextApproval = null, ...remainingApprovals] = current.approvalQueue
      approval = nextApproval
      approvalQueue = remainingApprovals
    } else {
      approval = current.approval
      approvalQueue = current.approvalQueue
    }
  }

  $overlayState.set({
    ...buildOverlayState(),
    agents: current.agents,
    agentsInitialHistoryIndex: current.agentsInitialHistoryIndex,
    approval,
    approvalQueue,
    modelPicker: current.modelPicker,
    picker: current.picker,
    skillsHub: current.skillsHub
  })
}

export const isStaleApprovalResponseError = (error: unknown) => {
  const message = error instanceof Error ? error.message : String(error ?? '')

  return /(?:no pending approval request|approval request id is required)/i.test(message)
}
