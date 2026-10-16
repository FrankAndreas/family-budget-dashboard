import 'i18next';
import type de from './locales/de';

// t('a.key') is checked against the German texts: a missing key is a type error
declare module 'i18next' {
    interface CustomTypeOptions {
        resources: { translation: typeof de };
    }
}
