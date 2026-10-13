export const PROACTIVE_CHANNELS = new Set(['desktop', 'telegram', 'wecom_bot'])

/** A new notification still on the placeholder channel must be chosen again. Existing web conversation tasks stay valid. */
export function notificationChannelError(input: {
  isCreate: boolean
  hasNotification: boolean
  channel: string
}): 'reselect' | null {
  if (input.hasNotification && input.isCreate && !PROACTIVE_CHANNELS.has(input.channel)) {
    return 'reselect'
  }
  return null
}
