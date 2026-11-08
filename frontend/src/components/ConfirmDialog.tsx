import { useEffect, useRef, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { register, type ConfirmRequest } from '../confirm';

// Shows the question ask() (confirm.ts) puts; mounted once (App)
export default function ConfirmHost() {
    const { t } = useTranslation();
    const [request, setRequest] = useState<ConfirmRequest | null>(null);
    const yes = useRef<HTMLButtonElement>(null);
    const dialog = useRef<HTMLDivElement>(null);

    useEffect(() => {
        return register(setRequest);
    }, []);
    // While open: Escape cancels, and Tab stays among the dialog's buttons (it would reach the page behind it). Closed:
    // the focus goes back to what asked, e.g. the "Delete" in a list (accessibility review 2026-11-08)
    useEffect(() => {
        if (!request) return;
        const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
        yes.current?.focus();
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') {
                request.resolve(false);
                setRequest(null);
            } else if (event.key === 'Tab' && dialog.current) {
                const buttons = [...dialog.current.querySelectorAll<HTMLButtonElement>('button')];
                const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
                const next = (at + (event.shiftKey ? buttons.length - 1 : 1)) % buttons.length;
                event.preventDefault();
                buttons[at < 0 ? 0 : next]?.focus();
            }
        };
        window.addEventListener('keydown', onKey);
        return () => {
            window.removeEventListener('keydown', onKey);
            if (opener?.isConnected) opener.focus();
        };
    }, [request]);

    if (!request) return null;
    const danger = request.danger ?? true;
    function answer(value: boolean) {
        request?.resolve(value);
        setRequest(null);
    }

    return (
        <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4">
            <button type="button" aria-label={t('common.cancel')} tabIndex={-1} onClick={() => answer(false)}
                className="absolute inset-0 bg-black/60 cursor-default" />
            <div ref={dialog} role="alertdialog" aria-modal="true" aria-labelledby="confirm-message"
                className="relative w-full max-w-md rounded-2xl border border-slate-600 bg-slate-900 p-5 shadow-2xl">
                <p id="confirm-message" className="text-slate-100 mb-5 whitespace-pre-line">{request.message}</p>
                <div className="flex justify-end gap-2">
                    <button type="button" onClick={() => answer(false)} className="btn-secondary" data-testid="confirm-no">
                        {t('common.cancel')}
                    </button>
                    <button ref={yes} type="button" onClick={() => answer(true)} data-testid="confirm-yes"
                        className={danger
                            ? 'px-4 py-2 rounded-lg font-semibold bg-red-700 hover:bg-red-800 text-white'
                            : 'btn-primary'}>
                        {request.confirmLabel ?? t('common.delete')}
                    </button>
                </div>
            </div>
        </div>
    );
}
