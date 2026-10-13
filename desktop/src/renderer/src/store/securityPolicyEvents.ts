export const SECURITY_POLICY_CHANGED = 'stella:security-policy-changed'

export function notifySecurityPolicyChanged() {
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(SECURITY_POLICY_CHANGED))
}
