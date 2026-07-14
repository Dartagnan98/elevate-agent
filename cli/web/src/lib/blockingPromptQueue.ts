export interface BlockingPromptIdentity {
  requestId: string;
  type: string;
}

export interface BlockingPromptQueueState<T extends BlockingPromptIdentity> {
  active: T | null;
  queued: T[];
}

export function emptyBlockingPromptQueue<
  T extends BlockingPromptIdentity,
>(): BlockingPromptQueueState<T> {
  return { active: null, queued: [] };
}

export function blockingPromptIdentity(prompt: BlockingPromptIdentity): string {
  return `${prompt.type}:${prompt.requestId}`;
}

export function enqueueBlockingPrompt<T extends BlockingPromptIdentity>(
  state: BlockingPromptQueueState<T>,
  prompt: T,
): BlockingPromptQueueState<T> {
  const identity = blockingPromptIdentity(prompt);
  if (
    (state.active && blockingPromptIdentity(state.active) === identity) ||
    state.queued.some((item) => blockingPromptIdentity(item) === identity)
  ) {
    return state;
  }
  if (!state.active) {
    return { active: prompt, queued: state.queued };
  }
  return { ...state, queued: [...state.queued, prompt] };
}

export function advanceBlockingPrompt<T extends BlockingPromptIdentity>(
  state: BlockingPromptQueueState<T>,
  identity: string,
): BlockingPromptQueueState<T> {
  if (!state.active || blockingPromptIdentity(state.active) !== identity) {
    return state;
  }
  const [active = null, ...queued] = state.queued;
  return { active, queued };
}
