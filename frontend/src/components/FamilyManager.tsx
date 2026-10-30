import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import type { FamilyUser } from '../family';
import EmailAddresses from './EmailAddresses';
import RemovedPeople from './RemovedPeople';
import type { PersonEmail } from '../inbox';
import Section from './Section';

// Parents only: the family as the family hub lists it for this app, with what only this app knows about each person
// (Jugendlohn or dependent, receipt-mail addresses). People, names and PINs are added and changed in the hub.
export default function FamilyManager() {
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users, reload } = useFamily();
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    // Addresses receipt mails are taken from (issue #57)
    const [emails, setEmails] = useState<PersonEmail[]>([]);
    const loadEmails = useCallback(() => {
        api.get('/api/v1/emails')
            .then(response => setEmails(response.data))
            .catch(err => setError(errorMessage(err, t('emails.failed'))));
    }, [t]);
    useEffect(loadEmails, [loadEmails]);

    const describe = (member: FamilyUser) => {
        if (member.role === 'PARENT') return t('family.parent');
        return member.has_allowance ? t('family.ownAllowance') : t('family.noOwnMoney');
    };

    const members = [...users].sort((a, b) =>
        a.role === b.role ? a.username.localeCompare(b.username) : a.role === 'PARENT' ? -1 : 1
    );

    const showResult = (message: string) => {
        setError('');
        setNotice(message);
        reload();
    };

    const setAllowance = async (member: FamilyUser, hasAllowance: boolean) => {
        if (!hasAllowance && !confirm(t('family.confirmRemoveAllowance', { name: member.username }))) return;
        try {
            await api.put(`/api/v1/users/${member.id}`, { has_allowance: hasAllowance });
            showResult(t(hasAllowance ? 'family.allowanceGiven' : 'family.allowanceRemoved', { name: member.username }));
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, t('family.updateFailed')));
        }
    };

    return (
        <Section id="family" title={t('family.title')}>
            <p className="text-slate-400 mb-6 text-sm">{t('family.intro')}</p>

            {(error || notice) && (
                <div className={`mb-4 p-3 rounded-lg flex justify-between items-center border ${error
                    ? 'bg-red-500/20 border-red-500/50 text-red-300'
                    : 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    }`}>
                    <span>{error || notice}</span>
                    <button onClick={() => { setError(''); setNotice(''); }} className="hover:text-white" aria-label={t('family.dismiss')}>✕</button>
                </div>
            )}

            <div className="space-y-3 mb-8">
                {members.map(member => (
                    <div key={member.id} className="p-4 bg-slate-800/30 rounded-lg">
                        <div className="flex flex-wrap justify-between items-center gap-3">
                            <div>
                                <h3 className="font-semibold">
                                    {member.username}
                                    {member.id === user?.id && <span className="ml-2 text-xs font-normal text-slate-400">{t('family.you')}</span>}
                                </h3>
                                <p className="text-sm text-slate-400">{describe(member)}</p>
                            </div>
                            <div className="flex gap-3 text-sm">
                                {member.role === 'CHILD' && member.has_allowance && (
                                    <button onClick={() => void setAllowance(member, false)} className="text-slate-400 hover:text-white">
                                        {t('family.removeAllowance')}
                                    </button>
                                )}
                                {member.role === 'CHILD' && !member.has_allowance && (
                                    <button onClick={() => void setAllowance(member, true)} className="btn-primary text-sm">
                                        {t('family.giveAllowance')}
                                    </button>
                                )}
                            </div>
                        </div>

                        <EmailAddresses member={member} addresses={emails.filter(e => e.user_id === member.id)}
                            onChanged={loadEmails} />
                    </div>
                ))}
            </div>

            <RemovedPeople onChanged={showResult} />
        </Section>
    );
}
