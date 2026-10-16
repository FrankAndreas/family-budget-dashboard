import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import i18n, { type Language } from '../i18n';

// Settings → Logins: the person's language, and ending every login of theirs on every device (e.g. a lost phone)
export default function Logins() {
    const { t } = useTranslation();
    const { user, logout } = useAuth();
    const [error, setError] = useState('');

    const logoutEverywhere = async () => {
        if (!confirm(t('logins.confirmLogoutEverywhere'))) return;
        try {
            await api.post('/api/v1/me/logout-everywhere');
            logout();
        } catch (err) {
            setError(errorMessage(err, t('logins.logoutFailed')));
        }
    };

    const changeLanguage = async (language: Language) => {
        try {
            await api.patch('/api/v1/me/language', { language });
            // Everything already loaded (e.g. the 🔒 category names) comes again in the new language
            window.location.reload();
        } catch (err) {
            setError(errorMessage(err, t('logins.languageFailed')));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-xl font-bold mb-2">{t('logins.title')}</h2>
            <label className="flex items-center gap-2 text-sm mb-4">
                {t('logins.language')}
                <select aria-label={t('logins.language')} value={user?.language ?? i18n.language}
                    onChange={e => changeLanguage(e.target.value as Language)}
                    className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white">
                    <option value="de">{t('logins.german')}</option>
                    <option value="en">{t('logins.english')}</option>
                </select>
            </label>
            <p className="text-sm text-slate-400 mb-4">{t('logins.intro')}</p>
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}
            <button onClick={logoutEverywhere} className="btn-primary text-sm">{t('logins.logoutEverywhere')}</button>
        </div>
    );
}
