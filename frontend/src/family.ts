// Family model: parents share one household. A child either has an own allowance
// (Jugendlohn: own accounts and budgets, kept separate) or is a dependent whose
// costs are household expenses tagged with them.

export interface FamilyUser {
    id: string;
    username: string;
    role: 'PARENT' | 'CHILD';
    has_allowance: boolean;
    privacy_enabled?: boolean;
}

// A set of accounts and budgets viewed together in Budgets and Analytics
export interface Scope {
    key: string;
    label: string;
    // Owners of the accounts that count in this scope
    userIds: string[];
    // Set when inspecting someone else's budgets (a child with own allowance)
    budgetOwnerId?: string;
}

export const HOUSEHOLD_SCOPE = 'household';

export function buildScopes(me: FamilyUser, users: FamilyUser[]): Scope[] {
    if (me.role !== 'PARENT') {
        return [{ key: me.id, label: 'My Money', userIds: [me.id] }];
    }

    const parents = users.filter(u => u.role === 'PARENT');
    const allowanceChildren = users.filter(u => u.role === 'CHILD' && u.has_allowance);
    return [
        { key: HOUSEHOLD_SCOPE, label: 'Household', userIds: parents.map(p => p.id) },
        ...allowanceChildren.map(child => ({
            key: child.id,
            label: `${child.username} (own allowance)`,
            userIds: [child.id],
            budgetOwnerId: child.id
        }))
    ];
}

// Children without own allowance; household expenses can be tagged with them
export function dependents(users: FamilyUser[]): FamilyUser[] {
    return users.filter(u => u.role === 'CHILD' && !u.has_allowance);
}
