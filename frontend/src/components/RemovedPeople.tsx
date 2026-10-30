import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import RemoveMember from './RemoveMember';

interface Removed { id: string; username: string; role: 'PARENT' | 'CHILD' }

// Parents: people the family hub no longer lists for this app. Their data is kept, hidden, until deleted here.
export default function RemovedPeople({ onChanged }: { onChanged: (message: string) => void }) {
    const { t } = useTranslation();
    const [removed, setRemoved] = useState<Removed[]>([]);
    const [deleting, setDeleting] = useState<string | null>(null);
    const [error, setError] = useState('');

    const load = useCallback(() => {
        api.get<Removed[]>('/api/v1/users/removed')
            .then(res => setRemoved(res.data))
            .catch(err => setError(errorMessage(err, t('removedPeople.failed'))));
    }, [t]);
    useEffect(load, [load]);

    if (removed.length === 0 && !error) return null;
    return (
        <section aria-labelledby="removed-people" className="space-y-3">
            <h3 id="removed-people" className="text-lg font-semibold">{t('removedPeople.title')}</h3>
            <p className="text-sm text-slate-400">{t('removedPeople.intro')}</p>
            {error && <p role="alert" className="text-red-300">{error}</p>}
            {removed.map(person => (
                <div key={person.id} className="p-4 bg-slate-800/30 rounded-lg">
                    <div className="flex flex-wrap justify-between items-center gap-3">
                        <span className="font-semibold">{person.username}</span>
                        {deleting !== person.id && (
                            <button onClick={() => setDeleting(person.id)} className="text-sm text-slate-400 hover:text-red-400"
                                aria-label={t('removedPeople.deleteOf', { name: person.username })}>
                                {t('removedPeople.delete')}
                            </button>
                        )}
                    </div>
                    {deleting === person.id && (
                        <RemoveMember
                            member={{ ...person, has_allowance: false }}
                            onDone={(message) => { setDeleting(null); load(); onChanged(message); }}
                            onCancel={() => setDeleting(null)}
                        />
                    )}
                </div>
            ))}
        </section>
    );
}
