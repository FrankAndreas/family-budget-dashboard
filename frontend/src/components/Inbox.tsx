import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import type { Account, Category } from '../accounts';
import type { FamilyUser } from '../family';
import { type InboxMail, type Release, release, useInbox, usePhotos } from '../inbox';
import ReceiptForm from './ReceiptForm';
import ScanReceipts from './ScanReceipts';
import ScannedReceipts from './ScannedReceipts';

interface Props {
    // Accounts the parent may book on
    accounts: Account[];
    categories: Category[];
    people: FamilyUser[];
    aiEnabled: boolean;
    version: number;
    onBooked: () => void;
    // Photographing a pile of receipts (receipt scan)
    scanning: boolean;
    onScan: () => void;
    onScanDone: () => void;
}

const field = 'p-2 rounded bg-slate-800/50 border border-slate-600 text-white';

// Parents only: receipt mails forwarded by the family (issue #57), unopened until one is released, and receipts
// photographed on the phone (receipt scan)
export default function Inbox({ accounts, categories, people, aiEnabled, version, onBooked, scanning, onScan, onScanDone }: Props) {
    const { t, i18n } = useTranslation();
    const { mails, failed, reload } = useInbox(true, version);
    const photos = usePhotos(true, version);
    const [checking, setChecking] = useState(false);
    const waiting = mails.length + photos.photos.length;
    const [chosen, setChosen] = useState<Record<string, string>>({});
    const [open, setOpen] = useState<{ mail: InboxMail; account: Account; result: Release } | null>(null);
    const [busy, setBusy] = useState<string | null>(null);
    const [error, setError] = useState('');

    const accountFor = (mail: InboxMail) => chosen[mail.id] ?? mail.suggested_account_id ?? '';
    const date = (value: string | null) => (value ? new Date(value).toLocaleDateString(i18n.language) : '');

    const doRelease = async (mail: InboxMail) => {
        const account = accounts.find(a => a.id === accountFor(mail));
        if (!account) return;
        setError('');
        setBusy(mail.id);
        try {
            setOpen({ mail, account, result: await release(mail) });
        } catch (err) {
            setError(errorMessage(err, t('inbox.failed')));
        } finally {
            setBusy(null);
        }
    };

    const remove = async (mail: InboxMail) => {
        if (!window.confirm(t('inbox.confirmDelete'))) return;
        try {
            await api.delete(`/api/v1/inbox/${mail.id}`);
            reload();
        } catch (err) {
            setError(errorMessage(err, t('inbox.failed')));
        }
    };

    return (
        <div className="glass-card p-6">
            <div className="flex flex-wrap justify-between items-center gap-2 mb-1">
                <h2 className="text-xl font-bold">
                    {waiting ? t('inbox.title', { count: waiting }) : t('inbox.titleEmpty')}
                </h2>
                {!scanning && <button type="button" className="btn-primary text-sm" onClick={onScan}>{t('scan.open')}</button>}
            </div>
            {mails.length > 0 && <p className="text-sm text-slate-400 mb-4">{t('inbox.intro')}</p>}
            {failed && <p className="text-red-400 text-sm mb-3">{t('inbox.loadFailed')}</p>}
            {error && <p className="text-red-400 text-sm mb-3">{error}</p>}

            {scanning ? (
                <ScanReceipts onDone={() => { onScanDone(); photos.reload(); }} />
            ) : open ? (
                <ReceiptForm
                    account={open.account}
                    categories={categories}
                    people={people}
                    aiEnabled={aiEnabled}
                    draft={open.result.draft}
                    attachment={open.result.attachment}
                    onSaved={() => { setOpen(null); reload(); onBooked(); }}
                    onCancel={() => setOpen(null)}
                />
            ) : (
                <>
                    <ScannedReceipts
                        photos={photos.photos}
                        reload={photos.reload}
                        accounts={accounts}
                        categories={categories}
                        people={people}
                        aiEnabled={aiEnabled}
                        onBooked={onBooked}
                        onChecking={setChecking}
                    />
                    {!checking && <ul className="space-y-3">
                        {mails.map(mail => (
                            <li key={mail.id} className="p-3 rounded-lg bg-slate-800/30">
                                <div className="flex flex-wrap justify-between gap-2">
                                    <div>
                                        <p className="font-semibold">{mail.subject}</p>
                                        <p className="text-sm text-slate-400">
                                            {mail.person_name ? t('inbox.forwardedBy', { name: mail.person_name }) : t('inbox.forwarderGone')}
                                            {' · '}{date(mail.sent_at ?? mail.received_at)}
                                            {' · '}{t('inbox.from', { address: mail.from_addr })}
                                        </p>
                                        <p className="text-sm text-slate-500">
                                            📎 {mail.attachment_names.length ? mail.attachment_names.join(', ') : t('inbox.noAttachments')}
                                        </p>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        <select aria-label={t('inbox.account', { subject: mail.subject })} className={field}
                                            value={accountFor(mail)} onChange={e => setChosen({ ...chosen, [mail.id]: e.target.value })}>
                                            <option value="">{t('inbox.chooseAccount')}</option>
                                            {accounts.map(a => <option key={a.id} value={a.id}>{a.name}</option>)}
                                        </select>
                                        <button type="button" className="btn-primary text-sm" disabled={!accountFor(mail) || busy !== null}
                                            onClick={() => doRelease(mail)}>{t('inbox.release')}</button>
                                        <button type="button" className="text-slate-400 hover:text-red-400 text-sm"
                                            onClick={() => remove(mail)}>{t('inbox.delete')}</button>
                                    </div>
                                </div>
                            </li>
                        ))}
                    </ul>}
                </>
            )}
        </div>
    );
}
