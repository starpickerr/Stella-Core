import { getLang } from '../../i18n'

export const SKILL_HUB_URL = 'https://www.skill-marketplace.com/'
export const FEEDBACK_URL = 'https://github.com/starpickerr/Stella/issues'

export const websiteUrl = () => 'https://github.com/starpickerr/Stella'

export const docsUrl = () =>
  getLang() === 'zh'
    ? 'https://github.com/starpickerr/Stella/tree/main/docs/zh'
    : 'https://github.com/starpickerr/Stella/tree/main/docs'

export const openExternal = (url: string) => {
  window.open(url, '_blank', 'noopener,noreferrer')
}
