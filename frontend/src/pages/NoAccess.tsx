import { useTranslation } from 'react-i18next';
import { useAuth } from '../AuthContext';

// Logged in at the family hub, but this app isn't theirs (no_access), or the hub can't be reached (hub_down)
export default function NoAccess({ reason }: { reason: 'no_access' | 'hub_down' }) {
    const { t } = useTranslation();
    const { logout, retry } = useAuth();
    return (
        <div className="flex min-h-screen items-center justify-center p-4">
            <div role="alert" className="glass-card max-w-md p-6 text-center space-y-4">
                <h1 className="text-xl font-semibold">{t(`hubLogin.${reason}.title`)}</h1>
                <p className="text-slate-300">{t(`hubLogin.${reason}.text`)}</p>
                <div className="flex justify-center gap-3">
                    {reason === 'hub_down'
                        ? <button className="btn-primary" onClick={retry}>{t('hubLogin.retry')}</button>
                        : <button className="btn-primary" onClick={() => void logout()}>{t('hubLogin.otherPerson')}</button>}
                </div>
            </div>
        </div>
    );
}
