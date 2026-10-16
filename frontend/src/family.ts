import i18n from './i18n';

// Family model: each parent's money is private unless they share it with the other parent
// (view or manage). Costs the parents share go through the common budget. A child either has an
// own allowance (Jugendlohn: own accounts and budgets, shareable with parents like a parent's) or is
// a dependent whose costs are tagged and whom all parents manage.

export interface FamilyUser {
    id: string;
    username: string;
    role: 'PARENT' | 'CHILD';
    has_allowance: boolean;
    privacy_enabled?: boolean;
    is_active?: boolean;
}

export type Access = 'OWN' | 'EDIT' | 'VIEW';

export interface ShareInfo {
    owner_id: string;
    grantee_id: string;
    level: 'NONE' | 'VIEW' | 'EDIT';
}

// A set of accounts and budgets viewed together in Budgets and Analytics
export interface Scope {
    key: string;
    label: string;
    // Owners of the accounts that count in this scope
    userIds: string[];
    // Set when looking at someone else's budgets
    budgetOwnerId?: string;
    access: Access;
}

// What the current user may do with someone's money (mirrors the backend's privacy.access_level)
export function accessTo(me: FamilyUser, ownerId: string, users: FamilyUser[], shares: ShareInfo[]): Access | null {
    if (ownerId === me.id) return 'OWN';
    if (me.role !== 'PARENT') return null;
    const owner = users.find(u => u.id === ownerId);
    if (!owner) return null;
    if (owner.role === 'CHILD' && !owner.has_allowance) return 'EDIT';
    if (owner.role === 'CHILD' && owner.privacy_enabled) return null;
    const level = shares.find(s => s.owner_id === ownerId && s.grantee_id === me.id)?.level;
    if (level === undefined) return owner.role === 'CHILD' ? 'VIEW' : null;
    return level === 'NONE' ? null : level;
}

export const canWrite = (access: Access | null) => access === 'OWN' || access === 'EDIT';

export function buildScopes(me: FamilyUser, users: FamilyUser[], shares: ShareInfo[]): Scope[] {
    if (me.role !== 'PARENT') {
        return [{ key: me.id, label: i18n.t('scopes.myMoney'), userIds: [me.id], access: 'OWN' }];
    }

    const others = users
        .filter(u => u.id !== me.id && (u.role === 'PARENT' || u.has_allowance))
        .map(u => ({ user: u, access: accessTo(me, u.id, users, shares) }))
        .filter((entry): entry is { user: FamilyUser; access: Access } => entry.access !== null);
    return [
        { key: me.id, label: i18n.t('scopes.myFinances'), userIds: [me.id], access: 'OWN' },
        ...others.map(({ user, access }) => ({
            key: user.id,
            label: i18n.t(user.role === 'PARENT' ? 'scopes.parentFinances' : 'scopes.ownAllowance', { name: user.username }),
            userIds: [user.id],
            budgetOwnerId: user.id,
            access
        }))
    ];
}

// Children without own allowance; expenses can be tagged with them
export function dependents(users: FamilyUser[]): FamilyUser[] {
    return users.filter(u => u.role === 'CHILD' && !u.has_allowance);
}
