import { useState } from 'react';
import type { FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import axios from 'axios';
import api from '../api';
import { money } from '../finance';
import { formatMonth } from '../format';
import { useReceiptReading } from '../receipts';

// POST /reports/ask (design 2026-11-27): the AI only turns the question into a query; the server computes the sums.
// Analytics keys it by the person shown, so an answer about someone else never stays on screen.
interface Period { from: string; to: string }
type Answer =
    | (Period & {
        status: 'ok';
        kind: 'expense' | 'income';
        category: string | null;
        tag: string | null;
        amount: number;
        compare: (Period & { amount: number }) | null;
    })
    | { status: 'unclear'; message: string };

const MAX_QUESTION = 300;

export default function AskBox({ ownerId }: { ownerId?: string }) {
    const { t } = useTranslation();
    const enabled = useReceiptReading();
    const [question, setQuestion] = useState('');
    const [answer, setAnswer] = useState<Answer | null>(null);
    const [error, setError] = useState<string | null>(null);
    const [asking, setAsking] = useState(false);

    if (!enabled) return null;

    const period = (p: Period) => p.from === p.to ? formatMonth(p.from) : `${formatMonth(p.from)} – ${formatMonth(p.to)}`;

    const submit = async (event: FormEvent) => {
        event.preventDefault();
        if (!question.trim() || asking) return;
        setAsking(true);
        setError(null);
        try {
            const response = await api.post('/api/v1/reports/ask', { question, user_id: ownerId });
            setAnswer(response.data);
        } catch (e) {
            setAnswer(null);
            const detail = axios.isAxiosError(e) ? e.response?.data?.detail : null;
            setError(typeof detail === 'string' ? detail : t('ask.failed'));
        } finally {
            setAsking(false);
        }
    };

    let text: string | null = error;
    let before: string | null = null;
    if (!error && answer?.status === 'unclear') text = answer.message;
    if (!error && answer?.status === 'ok') {
        const what = answer.category ?? (answer.tag ? `#${answer.tag}` : t(answer.kind === 'income' ? 'ask.allIncome' : 'ask.allExpenses'));
        text = t('ask.answer', { what, period: period(answer), amount: money(answer.amount) });
        if (answer.compare) before = t('ask.before', { period: period(answer.compare), amount: money(answer.compare.amount) });
    }

    return (
        <form onSubmit={submit} className="glass-card p-4 space-y-3">
            <div className="flex flex-wrap gap-2">
                <input
                    type="text"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    maxLength={MAX_QUESTION}
                    aria-label={t('ask.label')}
                    placeholder={t('ask.placeholder')}
                    className="flex-1 min-w-0 p-2 rounded bg-slate-800/50 border border-slate-500 text-white placeholder-slate-400"
                />
                <button
                    type="submit"
                    disabled={asking || !question.trim()}
                    className="px-4 py-2 rounded bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white font-semibold"
                >
                    {asking ? t('ask.thinking') : t('ask.ask')}
                </button>
            </div>
            <div role="status" className="text-slate-200">
                {text && <p className={error ? 'text-red-400' : undefined}>{text}</p>}
                {before && <p className="text-sm text-slate-400">{before}</p>}
            </div>
        </form>
    );
}
