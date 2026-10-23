import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import type { FamilyUser } from '../family';
import type { PersonEmail } from '../inbox';

interface Props {
    member: FamilyUser;
    // This person's addresses
    addresses: PersonEmail[];
    onChanged: () => void;
}

// Settings → Family: the addresses a person forwards receipt mails from (issue #57); mails from others are refused
export default function EmailAddresses({ member, addresses, onChanged }: Props) {
    const { t } = useTranslation();
    const [address, setAddress] = useState('');
    const [error, setError] = useState('');

    const add = async (e: React.FormEvent) => {
        e.preventDefault();
        setError('');
        try {
            await api.post(`/api/v1/users/${member.id}/emails`, { address });
            setAddress('');
            onChanged();
        } catch (err) {
            setError(errorMessage(err, t('emails.failed')));
        }
    };

    const remove = async (email: PersonEmail) => {
        setError('');
        try {
            await api.delete(`/api/v1/emails/${email.id}`);
            onChanged();
        } catch (err) {
            setError(errorMessage(err, t('emails.failed')));
        }
    };

    return (
        <div className="mt-3 text-sm">
            <p className="text-slate-400">{t('emails.label')}</p>
            {addresses.length === 0
                ? <p className="text-slate-500">{t('emails.none')}</p>
                : (
                    <ul className="flex flex-wrap gap-2 mt-1">
                        {addresses.map(email => (
                            <li key={email.id} className="px-2 py-0.5 rounded-full border border-slate-600">
                                {email.address}
                                <button type="button" onClick={() => remove(email)} className="ml-2 text-slate-500 hover:text-red-400"
                                    aria-label={t('emails.remove', { address: email.address })}>✕</button>
                            </li>
                        ))}
                    </ul>
                )}
            <form onSubmit={add} className="mt-2 flex flex-wrap gap-2">
                <input type="email" required value={address} onChange={e => setAddress(e.target.value)}
                    aria-label={t('emails.newFor', { name: member.username })} placeholder={t('emails.placeholder')}
                    className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white flex-1 min-w-48" />
                <button type="submit" className="text-blue-400 hover:underline">{t('emails.add')}</button>
            </form>
            {error && <p className="text-red-400 mt-1">{error}</p>}
        </div>
    );
}
