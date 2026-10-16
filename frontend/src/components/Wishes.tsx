import { useEffect, useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { money, useSplits } from '../finance';
import { ownerFields, ownerValue } from '../ownership';
import OwnerSelect from './OwnerSelect';

interface Wish {
    id: string;
    name: string;
    estimate: number | null;
    notes: string | null;
    owner_id: string | null;
    split_id: string | null;
    best_price: number | null;
    best_shop: string | null;
    best_url: string | null;
    best_checked: string | null;
    position: number;
    family_position: number | null;
    bought_on: string | null;
    // best_price, else estimate
    price: number | null;
    can_edit: boolean;
    in_family_plan: boolean;
}

type PlanRow = Wish & { running_total: number };

// Opened in a new tab with the wish's name; the app itself sends nothing anywhere
const SEARCHES = [
    { label: 'toppreise.ch', url: (q: string) => `https://www.toppreise.ch/produktsuche?q=${encodeURIComponent(q)}` },
    { label: 'Galaxus', url: (q: string) => `https://www.galaxus.ch/de/search?q=${encodeURIComponent(q)}` },
    { label: 'Google Shopping', url: (q: string) => `https://www.google.com/search?udm=28&q=${encodeURIComponent(q)}` },
];

const emptyForm = (userId: string) => ({
    id: null as string | null,
    name: '',
    estimate: '',
    owner: `owner:${userId}`,
    notes: '',
    best_price: '',
    best_shop: '',
    best_url: '',
    best_checked: ''
});

type Form = ReturnType<typeof emptyForm>;

const numberOrNull = (value: string) => (value.trim() === '' ? null : Number(value));
const textOrNull = (value: string) => (value.trim() === '' ? null : value.trim());
const priceText = (value: number | null) => (value === null ? '–' : money(value));
const groupKey = (wish: Wish) => (wish.split_id ? `split:${wish.split_id}` : `owner:${wish.owner_id}`);

// Things to buy: each owner's list in its own order, and the parents' family plan (one ranking, running total)
export default function Wishes() {
    const { user } = useAuth();
    const { users } = useFamily();
    const { splits } = useSplits();
    const [view, setView] = useState<'lists' | 'plan'>('lists');
    const [wishes, setWishes] = useState<Wish[]>([]);
    const [plan, setPlan] = useState<PlanRow[]>([]);
    const [form, setForm] = useState<Form | null>(null);
    const [searching, setSearching] = useState<string | null>(null);
    const [showBought, setShowBought] = useState<Record<string, boolean>>({});
    const [error, setError] = useState('');
    const [version, setVersion] = useState(0);
    const isParent = user?.role === 'PARENT';

    useEffect(() => {
        Promise.all([
            api.get('/api/v1/wishes'),
            isParent ? api.get('/api/v1/wishes/family-plan') : Promise.resolve({ data: [] })
        ])
            .then(([w, p]) => {
                setWishes(w.data);
                setPlan(p.data);
            })
            .catch(err => setError(errorMessage(err, 'Failed to load wishes')));
    }, [version, isParent]);

    if (!user) return null;

    const change = async (request: Promise<unknown>, failure: string) => {
        try {
            await request;
            setError('');
            setVersion(v => v + 1);
        } catch (err) {
            setError(errorMessage(err, failure));
        }
    };

    const ownerLabel = (wish: Wish) => {
        if (wish.split_id) return `Common: ${splits.find(s => s.id === wish.split_id)?.name ?? ''}`;
        if (wish.owner_id === user.id) return 'Mine';
        return users.find(u => u.id === wish.owner_id)?.username ?? '';
    };
    const cardTitle = (key: string, sample?: Wish) => {
        if (key === `owner:${user.id}`) return 'My wishes';
        if (!sample) return '';
        return sample.split_id ? ownerLabel(sample) : `${ownerLabel(sample)}'s wishes`;
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        const body = {
            name: form.name,
            estimate: numberOrNull(form.estimate),
            notes: textOrNull(form.notes),
            best_price: numberOrNull(form.best_price),
            best_shop: textOrNull(form.best_shop),
            best_url: textOrNull(form.best_url),
            best_checked: textOrNull(form.best_checked),
            ...ownerFields(form.owner)
        };
        await change(
            form.id ? api.put(`/api/v1/wishes/${form.id}`, body) : api.post('/api/v1/wishes', body),
            'Failed to save the wish'
        );
        setForm(null);
    };

    const edit = (wish: Wish) => setForm({
        id: wish.id,
        name: wish.name,
        estimate: wish.estimate?.toString() ?? '',
        owner: ownerValue(wish),
        notes: wish.notes ?? '',
        best_price: wish.best_price?.toString() ?? '',
        best_shop: wish.best_shop ?? '',
        best_url: wish.best_url ?? '',
        best_checked: wish.best_checked ?? ''
    });

    const move = (wish: Wish, direction: 'up' | 'down', list: 'own' | 'family') =>
        change(api.post(`/api/v1/wishes/${wish.id}/move`, { list, direction }), 'Failed to move the wish');
    const remove = (wish: Wish) => {
        if (!confirm(`Delete "${wish.name}"?`)) return;
        change(api.delete(`/api/v1/wishes/${wish.id}`), 'Failed to delete the wish');
    };

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';
    const small = 'text-sm text-slate-500 hover:text-white transition-colors';

    // Own list first (even when empty), then the other people, then the common lists
    const open = wishes.filter(w => !w.bought_on);
    const keys = [`owner:${user.id}`, ...new Set(wishes.map(groupKey))]
        .filter((key, i, all) => all.indexOf(key) === i)
        .sort((a, b) => Number(a !== `owner:${user.id}`) - Number(b !== `owner:${user.id}`)
            || Number(a.startsWith('split:')) - Number(b.startsWith('split:')));

    return (
        <div className="space-y-6">
            <div className="glass-card p-6">
                <div className="flex flex-wrap justify-between items-center gap-3">
                    <div>
                        <h2 className="text-xl font-bold">Wishes</h2>
                        <p className="text-sm text-slate-400">
                            Things to buy, in order of priority. The price is the best offer found, otherwise the estimate.
                        </p>
                    </div>
                    <div className="flex gap-2">
                        {isParent && (['lists', 'plan'] as const).map(v => (
                            <button
                                key={v}
                                onClick={() => setView(v)}
                                className={`px-3 py-2 rounded-lg text-sm font-semibold ${view === v ? 'bg-blue-500/30 text-blue-300' : 'text-slate-400 hover:text-white'}`}
                            >
                                {v === 'lists' ? 'My lists' : 'Family plan'}
                            </button>
                        ))}
                        {view === 'lists' && (
                            <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">+ Add wish</button>
                        )}
                    </div>
                </div>
                {error && <p className="text-red-400 text-sm mt-3">{error}</p>}

                {form && (
                    <form onSubmit={save} className="mt-4 p-4 bg-slate-800/30 rounded-lg grid grid-cols-1 md:grid-cols-2 gap-2">
                        <input aria-label="Wish name" placeholder="What?" value={form.name} required maxLength={120}
                            onChange={e => setForm({ ...form, name: e.target.value })} className={input} />
                        <input aria-label="Estimate" placeholder="Rough price" type="number" min="0" step="0.01" value={form.estimate}
                            onChange={e => setForm({ ...form, estimate: e.target.value })} className={input} />
                        <OwnerSelect value={form.owner} onChange={owner => setForm({ ...form, owner })} />
                        <input aria-label="Notes" placeholder="Notes" value={form.notes} maxLength={1000}
                            onChange={e => setForm({ ...form, notes: e.target.value })} className={input} />
                        {form.id && (<>
                            <input aria-label="Best price" placeholder="Best price found" type="number" min="0" step="0.01"
                                value={form.best_price} onChange={e => setForm({ ...form, best_price: e.target.value })} className={input} />
                            <input aria-label="Shop" placeholder="Shop" value={form.best_shop} maxLength={120}
                                onChange={e => setForm({ ...form, best_shop: e.target.value })} className={input} />
                            <input aria-label="Link" placeholder="https://…" type="url" pattern="https?://.*" value={form.best_url}
                                onChange={e => setForm({ ...form, best_url: e.target.value })} className={input} />
                            <input aria-label="Checked on" type="date" value={form.best_checked}
                                onChange={e => setForm({ ...form, best_checked: e.target.value })} className={input} />
                        </>)}
                        <div className="flex gap-2 md:col-span-2">
                            <button type="submit" className="btn-primary text-sm">Save wish</button>
                            <button type="button" onClick={() => setForm(null)} className="px-3 text-sm text-slate-400 hover:text-white">Cancel</button>
                        </div>
                    </form>
                )}
            </div>

            {view === 'lists' && keys.map(key => {
                const rows = open.filter(w => groupKey(w) === key).sort((a, b) => a.position - b.position);
                const bought = wishes.filter(w => w.bought_on && groupKey(w) === key)
                    .sort((a, b) => (b.bought_on ?? '').localeCompare(a.bought_on ?? ''));
                const sample = wishes.find(w => groupKey(w) === key);
                const total = rows.reduce((sum, w) => sum + (w.price ?? 0), 0);
                return (
                    <div key={key} className="glass-card p-6">
                        <h3 className="text-lg font-semibold mb-3">{cardTitle(key, sample)}</h3>
                        {rows.length === 0 && <p className="text-sm text-slate-400">No open wishes.</p>}
                        <ul className="space-y-2">
                            {rows.map((wish, i) => (
                                <li key={wish.id} className="p-3 rounded bg-slate-800/30">
                                    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
                                        {wish.can_edit && (
                                            <span className="flex flex-col leading-none">
                                                <button aria-label={`Move ${wish.name} up`} disabled={i === 0}
                                                    onClick={() => move(wish, 'up', 'own')} className={`${small} disabled:opacity-30`}>▲</button>
                                                <button aria-label={`Move ${wish.name} down`} disabled={i === rows.length - 1}
                                                    onClick={() => move(wish, 'down', 'own')} className={`${small} disabled:opacity-30`}>▼</button>
                                            </span>
                                        )}
                                        <span data-wish-name className="font-medium flex-1 min-w-32">{wish.name}</span>
                                        {wish.in_family_plan && <span className="text-xs text-amber-300" title="In the family plan">📌</span>}
                                        <span className="text-slate-400 text-sm">estimate {priceText(wish.estimate)}</span>
                                        {wish.best_price !== null && (
                                            <span className="text-sm">
                                                best {money(wish.best_price)}
                                                {wish.best_shop && (wish.best_url
                                                    ? <> at <a href={wish.best_url} target="_blank" rel="noreferrer" className="text-sky-400 hover:underline">{wish.best_shop}</a></>
                                                    : ` at ${wish.best_shop}`)}
                                                {wish.best_checked && <span className="text-slate-500"> (checked {wish.best_checked})</span>}
                                            </span>
                                        )}
                                        <span className="flex flex-wrap gap-3">
                                            <button aria-label={`Search ${wish.name}`} title="Search shops"
                                                onClick={() => setSearching(searching === wish.id ? null : wish.id)} className={small}>🔎</button>
                                            {isParent && wish.can_edit && !wish.split_id && (wish.in_family_plan
                                                ? <button aria-label={`Remove ${wish.name} from the family plan`}
                                                    onClick={() => change(api.delete(`/api/v1/wishes/${wish.id}/family-plan`), 'Failed to change the family plan')}
                                                    className={small}>Unpin</button>
                                                : <button aria-label={`Add ${wish.name} to the family plan`}
                                                    onClick={() => change(api.post(`/api/v1/wishes/${wish.id}/family-plan`), 'Failed to change the family plan')}
                                                    className={small}>📌 Plan</button>)}
                                            {wish.can_edit && (<>
                                                <button aria-label={`Mark ${wish.name} as bought`}
                                                    onClick={() => change(api.post(`/api/v1/wishes/${wish.id}/bought`, {}), 'Failed to mark as bought')}
                                                    className={small}>✓ Bought</button>
                                                <button aria-label={`Edit ${wish.name}`} onClick={() => edit(wish)} className={small}>Edit</button>
                                                <button aria-label={`Delete ${wish.name}`} onClick={() => remove(wish)}
                                                    className="text-sm text-slate-500 hover:text-red-400 transition-colors">Delete</button>
                                            </>)}
                                        </span>
                                    </div>
                                    {wish.notes && <p className="text-xs text-slate-400 mt-1">{wish.notes}</p>}
                                    {searching === wish.id && (
                                        <p className="text-sm mt-2 flex flex-wrap gap-3">
                                            {SEARCHES.map(s => (
                                                <a key={s.label} data-search href={s.url(wish.name)} target="_blank" rel="noreferrer"
                                                    className="text-sky-400 hover:underline">🔎 {s.label}</a>
                                            ))}
                                        </p>
                                    )}
                                </li>
                            ))}
                        </ul>
                        {rows.length > 0 && <p className="text-right font-semibold mt-3">Total {money(total)}</p>}
                        {bought.length > 0 && (
                            <div className="mt-3">
                                <button onClick={() => setShowBought({ ...showBought, [key]: !showBought[key] })} className={small}>
                                    {showBought[key] ? '▾' : '▸'} Bought ({bought.length})
                                </button>
                                {showBought[key] && (
                                    <ul className="mt-2 space-y-1">
                                        {bought.map(wish => (
                                            <li key={wish.id} className="flex flex-wrap gap-x-4 text-sm text-slate-400">
                                                <span className="flex-1">{wish.name}</span>
                                                <span>{priceText(wish.price)}</span>
                                                <span>bought {wish.bought_on}</span>
                                                {wish.can_edit && (
                                                    <button onClick={() => change(api.delete(`/api/v1/wishes/${wish.id}/bought`), 'Failed to reopen the wish')}
                                                        className={small}>Back to open</button>
                                                )}
                                            </li>
                                        ))}
                                    </ul>
                                )}
                            </div>
                        )}
                    </div>
                );
            })}

            {view === 'plan' && (
                <div className="glass-card p-6">
                    <h3 className="text-lg font-semibold mb-1">Family plan</h3>
                    <p className="text-sm text-slate-400 mb-3">
                        What we plan to buy together, most important first. Every parent can change the order.
                    </p>
                    {plan.length === 0 ? (
                        <p className="text-sm text-slate-400">Nothing in the family plan yet. Use 📌 in My lists to add a wish.</p>
                    ) : (
                        <ol className="space-y-2">
                            {plan.map((wish, i) => (
                                <li key={wish.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3 rounded bg-slate-800/30">
                                    <span className="w-6 text-slate-500">{i + 1}.</span>
                                    <span className="flex flex-col leading-none">
                                        <button aria-label={`Move ${wish.name} up in the family plan`} disabled={i === 0}
                                            onClick={() => move(wish, 'up', 'family')} className={`${small} disabled:opacity-30`}>▲</button>
                                        <button aria-label={`Move ${wish.name} down in the family plan`} disabled={i === plan.length - 1}
                                            onClick={() => move(wish, 'down', 'family')} className={`${small} disabled:opacity-30`}>▼</button>
                                    </span>
                                    <span data-plan-name className="font-medium flex-1 min-w-32">{wish.name}</span>
                                    <span className="text-sm text-slate-400">{ownerLabel(wish)}</span>
                                    <span className="w-24 text-right">{priceText(wish.price)}</span>
                                    <span data-plan-total className="w-28 text-right font-semibold" title="Total up to here">
                                        {money(wish.running_total)}
                                    </span>
                                </li>
                            ))}
                        </ol>
                    )}
                </div>
            )}
        </div>
    );
}
