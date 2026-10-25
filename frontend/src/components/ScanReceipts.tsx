import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { deletePhoto, type InboxPhoto } from '../inbox';
import { shrink, uploadPhoto } from '../scan';

interface Props {
    // Reading with the AI is set up on the server
    aiEnabled: boolean;
    // All photos are in the inbox (or left out on purpose)
    onDone: () => void;
}

interface Shot {
    key: number;
    url: string;
    blob: Blob;
    withAi: boolean;
    state: 'uploading' | 'done' | 'failed';
    // In the inbox once uploaded
    photo?: InboxPhoto;
}

// A pile of receipts photographed one after another (receipt scan): each photo goes to the inbox as soon as it is
// taken, so a closed tab loses at most the one being uploaded; a failed upload keeps its photo here for a retry
export default function ScanReceipts({ aiEnabled, onDone }: Props) {
    const { t } = useTranslation();
    const input = useRef<HTMLInputElement>(null);
    const [shots, setShots] = useState<Shot[]>([]);
    // Off for a pile the AI shouldn't see (a doctor's bill): those photos are typed in when checked
    const [withAi, setWithAi] = useState(true);
    const urls = useRef<string[]>([]);
    useEffect(() => () => urls.current.forEach(url => URL.revokeObjectURL(url)), []);

    const setState = (key: number, state: Shot['state'], photo?: InboxPhoto) =>
        setShots(list => list.map(shot => (shot.key === key ? { ...shot, state, photo } : shot)));

    const send = async (key: number, blob: Blob, ai: boolean) => {
        setState(key, 'uploading');
        try {
            setState(key, 'done', await uploadPhoto(blob, ai));
        } catch {
            setState(key, 'failed');
        }
    };

    const taken = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (!file) return;
        // A photo the browser can't shrink goes up as it is: the server decides, and a failure shows with a retry
        const blob = await shrink(file).catch(() => file);
        const key = Date.now() + Math.random();
        const url = URL.createObjectURL(blob);
        urls.current.push(url);
        const ai = aiEnabled && withAi;
        setShots(list => [...list, { key, url, blob, withAi: ai, state: 'uploading' }]);
        await send(key, blob, ai);
    };

    // Taken by mistake: out of the inbox again; a failed one never got there
    const remove = async (shot: Shot) => {
        if (shot.photo) {
            if (!window.confirm(t('scan.confirmRemove'))) return;
            try {
                await deletePhoto(shot.photo);
            } catch {
                window.alert(t('scan.removeFailed'));
                return;
            }
        }
        setShots(list => list.filter(other => other.key !== shot.key));
    };

    const uploading = shots.some(shot => shot.state === 'uploading');
    const failed = shots.some(shot => shot.state === 'failed');
    const done = shots.filter(shot => shot.state === 'done').length;
    const finish = () => {
        if (failed && !window.confirm(t('scan.confirmFailed'))) return;
        onDone();
    };

    return (
        <div className="space-y-4">
            <div>
                <h3 className="text-lg font-semibold">{t('scan.title')}</h3>
                <p className="text-sm text-slate-400">{t('scan.intro')}</p>
            </div>
            {aiEnabled && (
                <label className="flex items-start gap-2 text-sm">
                    <input type="checkbox" className="mt-1" checked={withAi} onChange={e => setWithAi(e.target.checked)} />
                    <span>
                        {t('scan.withAi')}
                        <span className="block text-slate-400">{withAi ? t('scan.withAiOn') : t('scan.withAiOff')}</span>
                    </span>
                </label>
            )}
            <input ref={input} type="file" accept="image/*" capture="environment" aria-label={t('scan.camera')}
                onChange={taken} className="sr-only" />
            {shots.length > 0 && (
                <ul className="flex flex-wrap gap-2">
                    {shots.map((shot, index) => (
                        <li key={shot.key} className="w-20 text-center text-xs">
                            <img src={shot.url} alt={t('scan.photo', { n: index + 1 })}
                                className={`h-24 w-20 object-cover rounded ${shot.state === 'failed' ? 'ring-2 ring-red-400' : ''}`} />
                            {shot.state === 'uploading' && <p className="text-slate-400">{t('scan.uploading')}</p>}
                            {shot.state === 'done' && <p className="text-emerald-400">✓ {t('scan.uploaded')}</p>}
                            {shot.state === 'failed' && (
                                <>
                                    <p className="text-red-400">{t('scan.failed')}</p>
                                    <button type="button" className="text-blue-400 underline"
                                        onClick={() => send(shot.key, shot.blob, shot.withAi)}>{t('scan.retry')}</button>
                                </>
                            )}
                            <button type="button" className="mt-1 text-slate-400 underline disabled:opacity-50"
                                disabled={shot.state === 'uploading'} aria-label={t('scan.remove', { n: index + 1 })}
                                onClick={() => remove(shot)}>✕ {t('scan.removeShort')}</button>
                        </li>
                    ))}
                </ul>
            )}
            <div className="flex flex-col sm:flex-row gap-2">
                <button type="button" className="btn-primary" onClick={() => input.current?.click()}>
                    {shots.length === 0 ? t('scan.first') : t('scan.next')}
                </button>
                <button type="button" className="px-4 py-2 rounded-lg bg-slate-700 text-white disabled:opacity-50"
                    disabled={uploading} onClick={finish}>
                    {t('scan.done', { count: done })}
                </button>
            </div>
        </div>
    );
}
