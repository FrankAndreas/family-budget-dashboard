import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import de from './locales/de';
import en from './locales/en';

export type Language = 'de' | 'en';

// Before login (and after logout) the browser decides; after login the person's own setting (issue #50)
export const browserLanguage = (): Language => (navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en');

i18n.use(initReactI18next).init({
    resources: { de: { translation: de }, en: { translation: en } },
    lng: browserLanguage(),
    fallbackLng: 'de',
    interpolation: { escapeValue: false },
});
document.documentElement.lang = i18n.language;

export function applyLanguage(lang: Language) {
    if (i18n.language !== lang) i18n.changeLanguage(lang);
    document.documentElement.lang = lang;
}

export default i18n;
