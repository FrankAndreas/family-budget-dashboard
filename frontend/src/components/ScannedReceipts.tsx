import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { errorMessage } from '../api';
import type { Account, Category } from '../accounts';
import type { FamilyUser } from '../family';
import { money } from '../finance';
import { type InboxPhoto, type Release, deletePhoto, openPhoto } from '../inbox';
import ReceiptForm from './ReceiptForm';

interface Props {
    photos: InboxPhoto[];
    reload: () => void;
    // Accounts the parent may book on
    accounts: Account[];
    categories: Category[];
    people: FamilyUser[];
    aiEnabled: boolean;
    onBooked: () => void;
    // A photo is being checked: the inbox hides its other entries meanwhile
    onChecking: (checking: boolean) => void;
}

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';
// The server's times are UTC without an offset
const utc = (value: string) => new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);

// Receipts photographed on the phone (receipt scan), checked one after another in the order they were taken
export default function ScannedReceipts({ photos, reload, accounts, categories, people, aiEnabled, onBooked, onChecking }: Props) {
    const { t, i18n } = useTranslation();
    const [chosen, setChosen] = useState<Record<string, string>>({});
    // A pile is often from one card: the next photo gets the account of the one booked before
    const [lastAccount, setLastAccount] = useState<string | null>(null);
    const [current, setCurrent] = useState<{ photo: InboxPhoto; account: Account; result: Release } | null>(null);
    const [busy, setBusy] = useState(false);
    const [error, setError] = useState('');

    if (photos.length === 0 && !current) return null;

    const accountFor = (photo: InboxPhoto, previous = lastAccount) =>
        chosen[photo.id] ?? previous ?? photo.suggested_account_id ?? '';

    const check = async (photo: InboxPhoto | undefined, previous = lastAccount) => {
        const account = photo && accounts.find(a => a.id === accountFor(photo, previous));
        if (!photo || !account) {
            setCurrent(null);
            onChecking(false);
            return;
        }
        setError('');
        setBusy(true);
        try {
            setCurrent({ photo, account, result: await openPhoto(photo) });
            onChecking(true);
        } catch (err) {
            setError(errorMessage(err, t('scan.openFailed')));
            setCurrent(null);
            onChecking(false);
        } finally {
            setBusy(false);
        }
    };

    // The photos after the one being checked, in the list's order (the one just booked is still in it until reloaded)
    const after = (photo: InboxPhoto) => photos.slice(photos.findIndex(p => p.id === photo.id) + 1);

    const booked = () => {
        if (!current) return;
        const used = current.account.id;
        setLastAccount(used);
        reload();
        onBooked();
        check(after(current.photo)[0], used);
    };

    const remove = async (photo: InboxPhoto) => {
        if (!window.confirm(t('scan.confirmDelete'))) return;
        try {
            await deletePhoto(photo);
            reload();
        } catch (err) {
            setError(errorMessage(err, t('scan.openFailed')));
        }
    };

    const describe = (photo: InboxPhoto) =>
        photo.read_state === 'read'
            ? [photo.shop || t('scan.noShop'), photo.total !== null ? money(photo.total) : null].filter(Boolean).join(' · ')
            : t(`scan.state.${photo.read_state}`);

    if (current) {
        const index = photos.findIndex(p => p.id === current.photo.id);
        return (
            <div className="space-y-3">
                <p className="text-sm text-slate-400">{t('scan.checking', { n: index + 1, count: photos.length })}</p>
                <label className="block text-sm">
                    {t('scan.accountForCheck')}
                    <select className={`${field} block mt-1`} value={current.account.id} aria-label={t('scan.accountForCheck')}
                        onChange={e => {
                            const account = accounts.find(a => a.id === e.target.value);
                            if (account) setCurrent({ ...current, account });
                        }}>
                        {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                    </select>
                </label>
                <ReceiptForm
                    key={current.photo.id}
                    account={current.account}
                    categories={categories}
                    people={people}
                    aiEnabled={aiEnabled}
                    draft={current.result.draft}
                    attachment={current.result.attachment}
                    submitLabel={t('scan.bookNext')}
                    onSkip={() => check(after(current.photo)[0])}
                    onSaved={booked}
                    onCancel={() => { setCurrent(null); onChecking(false); }}
                />
            </div>
        );
    }

    const first = photos.find(photo => accountFor(photo));
    return (
        <div className="mb-4 space-y-3">
            {error && <p className="text-red-400 text-sm">{error}</p>}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-sm text-slate-400">{t('scan.waitingIntro', { count: photos.length })}</p>
                <button type="button" className="btn-primary text-sm" disabled={!first || busy} onClick={() => check(first)}>
                    {t('scan.checkNext')}
                </button>
            </div>
            <ul className="space-y-2">
                {photos.map((photo, index) => (
                    <li key={photo.id} className="p-3 rounded-lg bg-slate-800/30 flex flex-wrap justify-between gap-2">
                        <div>
                            <p className="font-semibold">{describe(photo)}</p>
                            <p className="text-sm text-slate-400">
                                {photo.person_name ? t('scan.takenBy', { name: photo.person_name }) : t('scan.takerGone')}
                                {' · '}{utc(photo.taken_at).toLocaleString(i18n.language)}
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            <select aria-label={t('scan.account', { n: index + 1 })} className={field} value={accountFor(photo)}
                                onChange={e => setChosen({ ...chosen, [photo.id]: e.target.value })}>
                                <option value="">{t('inbox.chooseAccount')}</option>
                                {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                            </select>
                            <button type="button" className="btn-primary text-sm" disabled={!accountFor(photo) || busy}
                                onClick={() => check(photo)}>{t('scan.check')}</button>
                            <button type="button" className="text-slate-400 hover:text-red-400 text-sm"
                                onClick={() => remove(photo)}>{t('inbox.delete')}</button>
                        </div>
                    </li>
                ))}
            </ul>
        </div>
    );
}
