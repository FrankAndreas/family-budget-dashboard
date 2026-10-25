import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import { accessTo, canWrite } from '../family';
import { assetTotals, money, useAssets, useSplits, type Asset } from '../finance';
import { ownerFields, ownerValue } from '../ownership';
import { useTags } from '../receipts';
import OwnerSelect from './OwnerSelect';
import AssetCard from './AssetCard';
import AssetGroup, { ArchivedGroup } from './AssetGroup';
import { useScrollIntoView } from '../useScrollIntoView';

interface Expense { id: string; amount: number; date: string; description: string | null }
type Filter = 'all' | 'mine' | 'common' | 'others';
const FILTERS: Filter[] = ['all', 'mine', 'common', 'others'];
// The tag select's choice for making a new tag
const NEW_TAG = 'new';

const emptyForm = (userId: string) => ({
    id: null as string | null,
    name: '',
    price: '',
    purchase_date: new Date().toISOString().slice(0, 10),
    lifespan_years: '5',
    owner: `owner:${userId}`,
    tag: '',
    newTag: '',
    notes: '',
    kind: 'PURCHASE' as Asset['kind'],
    lease_rate: '',
    lease_months: '',
    lease_final: ''
});

// Big purchases (TV, fridge, car, bike): age, when to replace them, what to set aside, and what they cost so far;
// grouped by tag, with what each group costs together
export default function Investments() {
    const { t } = useTranslation();
    const { user } = useAuth();
    const { users, shares } = useFamily();
    const { splits } = useSplits();
    const { assets, reload } = useAssets();
    const { tags, reload: reloadTags } = useTags();
    const [filter, setFilter] = useState<Filter>('all');
    const [form, setForm] = useState<ReturnType<typeof emptyForm> | null>(null);
    const [openId, setOpenId] = useState<string | null>(null);
    const [expenses, setExpenses] = useState<Expense[]>([]);
    const [error, setError] = useState('');
    const formRef = useScrollIntoView<HTMLFormElement>(form?.id);

    const ownerLabel = (asset: Asset) => {
        if (asset.split_id) {
            return t('investments.commonSplit', { name: splits.find(s => s.id === asset.split_id)?.name ?? t('investments.splitFallback') });
        }
        return asset.owner_id === user?.id
            ? t('investments.mine')
            : t('investments.someones', { name: users.find(u => u.id === asset.owner_id)?.username ?? '' });
    };
    const canChange = (asset: Asset) =>
        !asset.owner_id || (!!user && canWrite(accessTo(user, asset.owner_id, users, shares)));
    const shown = assets.filter(a =>
        filter === 'all' ||
        (filter === 'mine' && a.owner_id === user?.id) ||
        (filter === 'common' && a.split_id) ||
        (filter === 'others' && a.owner_id && a.owner_id !== user?.id)
    );
    const active = shown.filter(a => !a.archived_on);
    const archived = shown.filter(a => a.archived_on);
    // Per tag (an unknown or no tag: "No tag" last among equals), the costliest group first
    const groups = [...tags.map(tag => ({ id: tag.id, title: `${tag.icon ? `${tag.icon} ` : ''}${tag.name}`, assets: active.filter(a => a.tag_id === tag.id) })),
        { id: 'none', title: t('investments.noTag'), assets: active.filter(a => !a.tag_id || !tags.some(tag => tag.id === a.tag_id)) }]
        .filter(g => g.assets.length > 0)
        .sort((a, b) => assetTotals(b.assets).monthly - assetTotals(a.assets).monthly);
    const all = assetTotals(active);

    const call = async (request: () => Promise<unknown>, failed: string) => {
        try {
            await request();
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, failed));
        }
    };

    const toggle = async (asset: Asset) => {
        if (openId === asset.id) {
            setOpenId(null);
            return;
        }
        try {
            const response = await api.get(`/api/v1/assets/${asset.id}`);
            setExpenses(response.data.expenses);
            setOpenId(asset.id);
        } catch (err) {
            setError(errorMessage(err, t('investments.loadFailed')));
        }
    };

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!form) return;
        try {
            let tagId: string | null = form.tag || null;
            if (form.tag === NEW_TAG) {
                tagId = (await api.post('/api/v1/tags', { name: form.newTag })).data.id;
                reloadTags();
            }
            const body = {
                name: form.name,
                price: parseFloat(form.price),
                purchase_date: form.purchase_date,
                lifespan_years: parseInt(form.lifespan_years, 10),
                notes: form.notes || null,
                tag_id: tagId,
                kind: form.kind,
                ...(form.kind === 'LEASE' ? {
                    lease_rate: parseFloat(form.lease_rate),
                    lease_months: parseInt(form.lease_months, 10),
                    lease_final: form.lease_final ? parseFloat(form.lease_final) : 0,
                } : {}),
                ...ownerFields(form.owner)
            };
            if (form.id) await api.put(`/api/v1/assets/${form.id}`, body);
            else await api.post('/api/v1/assets', body);
            setForm(null);
            setError('');
            reload();
        } catch (err) {
            setError(errorMessage(err, t('investments.saveFailed')));
        }
    };

    const remove = (asset: Asset) => {
        if (!confirm(t('investments.confirmDelete', { name: asset.name }))) return;
        call(() => api.delete(`/api/v1/assets/${asset.id}`), t('investments.deleteFailed'));
    };

    const edit = (asset: Asset) => setForm({
        id: asset.id,
        name: asset.name,
        price: String(asset.price),
        purchase_date: asset.purchase_date,
        lifespan_years: String(asset.lifespan_years),
        owner: ownerValue(asset),
        tag: asset.tag_id ?? '',
        newTag: '',
        notes: asset.notes ?? '',
        kind: asset.kind,
        lease_rate: asset.lease_rate != null ? String(asset.lease_rate) : '',
        lease_months: asset.lease_months != null ? String(asset.lease_months) : '',
        lease_final: asset.lease_final != null ? String(asset.lease_final) : ''
    });

    const card = (asset: Asset) => (
        <AssetCard key={asset.id} asset={asset} owner={ownerLabel(asset)} canChange={canChange(asset)}
            expenses={openId === asset.id ? expenses : null}
            onToggleCosts={() => toggle(asset)}
            onEdit={() => edit(asset)}
            onDelete={() => remove(asset)}
            onArchive={(on) => call(() => api.post(`/api/v1/assets/${asset.id}/archive`, { archived_on: on }), t('investments.archiveFailed'))}
            onRestore={() => call(() => api.delete(`/api/v1/assets/${asset.id}/archive`), t('investments.archiveFailed'))} />
    );

    const input = 'w-full p-2 rounded bg-slate-800/50 border border-slate-600 text-white';
    const lease = form?.kind === 'LEASE';

    return (
        <div className="glass-card p-6">
            <div className="flex flex-wrap justify-between items-center gap-3 mb-2">
                <h2 className="text-2xl font-bold">{t('investments.title')}</h2>
                <div className="flex gap-3">
                    <select
                        value={filter}
                        onChange={(e) => setFilter(e.target.value as Filter)}
                        className="p-2 rounded bg-slate-800/50 border border-slate-600 text-white"
                        aria-label={t('investments.show')}
                    >
                        {FILTERS.map(f => <option key={f} value={f}>{t(`investments.filters.${f}`)}</option>)}
                    </select>
                    {!form && user && (
                        <button onClick={() => setForm(emptyForm(user.id))} className="btn-primary text-sm">{t('investments.add')}</button>
                    )}
                </div>
            </div>
            <p className="text-sm text-slate-400 mb-4">{t('investments.intro')}</p>
            {error && <p className="mb-3 text-red-300">{error}</p>}

            {form && (
                <form ref={formRef} onSubmit={save} className="scroll-mt-4 mb-6 p-4 bg-slate-800/30 rounded-lg grid gap-2 md:grid-cols-2">
                    <select className={`${input} md:col-span-2`} value={form.kind} aria-label={t('investments.kind')}
                        onChange={(e) => setForm({ ...form, kind: e.target.value as Asset['kind'] })}>
                        <option value="PURCHASE">{t('investments.kinds.PURCHASE')}</option>
                        <option value="LEASE">{t('investments.kinds.LEASE')}</option>
                    </select>
                    {/* Labels above the fields, so a filled-in field still says what it is */}
                    <label className="text-sm text-slate-400">{t('investments.name')}
                        <input className={input} placeholder={t('investments.namePlaceholder')} value={form.name}
                            onChange={(e) => setForm({ ...form, name: e.target.value })} required />
                    </label>
                    <label className="text-sm text-slate-400">{lease ? t('investments.downPayment') : t('investments.price')}
                        <input className={input} type="number" step="0.01" min="0.01" value={form.price}
                            onChange={(e) => setForm({ ...form, price: e.target.value })} required />
                    </label>
                    <label className="text-sm text-slate-400">{lease ? t('investments.leaseStart') : t('investments.boughtOn')}
                        <input className={input} type="date" value={form.purchase_date}
                            onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} required />
                    </label>
                    <label className="text-sm text-slate-400">{lease ? t('investments.lifespanLease') : t('investments.lifespan')}
                        <input className={input} type="number" min="1" max="100" step="1" value={form.lifespan_years}
                            onChange={(e) => setForm({ ...form, lifespan_years: e.target.value })} required />
                    </label>
                    {lease && (<>
                        <label className="text-sm text-slate-400">{t('investments.leaseRate')}
                            <input className={input} type="number" step="0.01" min="0" value={form.lease_rate} required
                                onChange={(e) => setForm({ ...form, lease_rate: e.target.value })} />
                        </label>
                        <label className="text-sm text-slate-400">{t('investments.leaseMonths')}
                            <input className={input} type="number" step="1" min="1" max="240" value={form.lease_months} required
                                onChange={(e) => setForm({ ...form, lease_months: e.target.value })} />
                        </label>
                        <label className="text-sm text-slate-400">{t('investments.leaseFinal')}
                            <input className={input} type="number" step="0.01" min="0" value={form.lease_final}
                                onChange={(e) => setForm({ ...form, lease_final: e.target.value })} />
                        </label>
                    </>)}
                    <OwnerSelect value={form.owner} onChange={(owner) => setForm({ ...form, owner })} />
                    <div className="flex gap-2">
                        <select className={input} value={form.tag} onChange={(e) => setForm({ ...form, tag: e.target.value })}
                            aria-label={t('investments.tag')}>
                            <option value="">{t('investments.noTag')}</option>
                            {tags.map(tag => <option key={tag.id} value={tag.id}>{tag.icon ? `${tag.icon} ` : ''}{tag.name}</option>)}
                            <option value={NEW_TAG}>{t('investments.newTag')}</option>
                        </select>
                        {form.tag === NEW_TAG && (
                            <input className={input} value={form.newTag} onChange={(e) => setForm({ ...form, newTag: e.target.value })}
                                aria-label={t('investments.newTagName')} placeholder={t('investments.newTagName')} required maxLength={50} />
                        )}
                    </div>
                    <input className={`${input} md:col-span-2`} placeholder={t('investments.notesPlaceholder')} value={form.notes}
                        onChange={(e) => setForm({ ...form, notes: e.target.value })} aria-label={t('investments.notes')} />
                    <div className="flex gap-2 md:col-span-2">
                        <button type="submit" className="btn-primary flex-1">{form.id ? t('common.save') : t('investments.addItem')}</button>
                        <button type="button" onClick={() => setForm(null)} className="px-4 text-slate-400 hover:text-white">{t('common.cancel')}</button>
                    </div>
                </form>
            )}

            {shown.length === 0 ? (
                <p className="text-slate-400 text-center py-8">{t('investments.none')}</p>
            ) : (
                <div className="space-y-3">
                    {active.length > 0 && (
                        <p data-testid="investments-total" className="text-sm">
                            {t('investments.allTotal')}{' · '}<strong>{t('investments.perMonth', { amount: money(all.monthly) })}</strong>
                            {' · '}{t('investments.soFar', { amount: money(all.total) })}
                            {' · '}{t('investments.perYearTotal', { amount: money(all.perYear) })}
                        </p>
                    )}
                    {groups.map(group => (
                        <AssetGroup key={group.id} id={group.id} title={group.title} assets={group.assets}>
                            {[...group.assets].sort((a, b) => a.replacement_due.localeCompare(b.replacement_due)).map(card)}
                        </AssetGroup>
                    ))}
                    {archived.length > 0 && <ArchivedGroup count={archived.length}>{archived.map(card)}</ArchivedGroup>}
                </div>
            )}
        </div>
    );
}
