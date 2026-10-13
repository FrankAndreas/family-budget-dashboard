import { useState } from 'react';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import type { FamilyUser } from '../family';
import PinInput from './PinInput';
import { isValidPin } from '../pin';

type MemberType = 'PARENT' | 'ALLOWANCE_CHILD' | 'DEPENDENT_CHILD';

const MEMBER_TYPES: Record<MemberType, string> = {
    PARENT: 'Parent',
    ALLOWANCE_CHILD: 'Child with own allowance (Jugendlohn)',
    DEPENDENT_CHILD: 'Younger child (no own money, no login)'
};

const describe = (member: FamilyUser) => {
    if (member.role === 'PARENT') return 'Parent';
    return member.has_allowance ? 'Own allowance (Jugendlohn)' : 'No own money: costs are household expenses';
};

// Everyone who logs in has a PIN; younger children don't log in
const hasLogin = (member: FamilyUser) => member.role === 'PARENT' || member.has_allowance;

// Parents only: add family members, reset PINs, and switch children between "dependent" and "own allowance"
export default function FamilyManager() {
    const { user } = useAuth();
    const { users, reload } = useFamily();
    const [error, setError] = useState('');
    const [notice, setNotice] = useState('');

    // Add form
    const [newName, setNewName] = useState('');
    const [newType, setNewType] = useState<MemberType>('DEPENDENT_CHILD');
    const [newPin, setNewPin] = useState('');

    // Member whose PIN is being set (reset, or for a new own allowance), and the PIN
    const [pinMemberId, setPinMemberId] = useState<string | null>(null);
    const [pinAction, setPinAction] = useState<'reset' | 'allowance'>('reset');
    const [memberPin, setMemberPin] = useState('');

    const members = [...users].sort((a, b) =>
        a.role === b.role ? a.username.localeCompare(b.username) : a.role === 'PARENT' ? -1 : 1
    );

    const showResult = (message: string) => {
        setError('');
        setNotice(message);
        reload();
    };

    const handleAdd = async (e: React.FormEvent) => {
        e.preventDefault();
        const name = newName.trim();
        if (newType !== 'DEPENDENT_CHILD' && !isValidPin(newPin)) {
            setError('The PIN must be exactly 4 digits');
            return;
        }

        try {
            if (newType === 'DEPENDENT_CHILD') {
                await api.post('/api/v1/members', { username: name });
            } else {
                await api.post('/api/v1/users', {
                    username: name,
                    pin: newPin,
                    role: newType === 'PARENT' ? 'PARENT' : 'CHILD'
                });
            }
            setNewName('');
            setNewPin('');
            showResult(newType === 'DEPENDENT_CHILD' ? `Added ${name}.` : `Added ${name}. They can now log in with their PIN.`);
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, 'Failed to add family member'));
        }
    };

    const openPinForm = (member: FamilyUser, action: 'reset' | 'allowance') => {
        setPinMemberId(member.id);
        setPinAction(action);
        setMemberPin('');
    };

    const closePinForm = () => {
        setPinMemberId(null);
        setMemberPin('');
    };

    const handlePinSubmit = async (e: React.FormEvent, member: FamilyUser) => {
        e.preventDefault();
        if (!isValidPin(memberPin)) {
            setError('The PIN must be exactly 4 digits');
            return;
        }

        try {
            const update = pinAction === 'allowance' ? { has_allowance: true, pin: memberPin } : { pin: memberPin };
            await api.put(`/api/v1/users/${member.id}`, update);
            closePinForm();
            showResult(pinAction === 'allowance'
                ? `${member.username} now has an own allowance and logs in with the new PIN.`
                : `PIN for ${member.username} changed.`);
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, 'Failed to save the PIN'));
        }
    };

    const handleRemoveAllowance = async (member: FamilyUser) => {
        if (!confirm(`${member.username} will no longer have own money. Their expenses become household expenses. Continue?`)) return;
        try {
            await api.put(`/api/v1/users/${member.id}`, { has_allowance: false });
            showResult(`${member.username} no longer has an own allowance.`);
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, 'Failed to update child'));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-2">Family</h2>
            <p className="text-slate-400 mb-6 text-sm">
                Parents add everyone here; there is no sign-up page. Younger children have no money of their own: their
                costs are household expenses you can tag with them. Once a child gets an own allowance (Jugendlohn), they
                log in with a PIN and manage their own accounts and budgets.
            </p>

            {(error || notice) && (
                <div className={`mb-4 p-3 rounded-lg flex justify-between items-center border ${error
                    ? 'bg-red-500/20 border-red-500/50 text-red-300'
                    : 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    }`}>
                    <span>{error || notice}</span>
                    <button onClick={() => { setError(''); setNotice(''); }} className="hover:text-white" aria-label="Dismiss message">✕</button>
                </div>
            )}

            <div className="space-y-3 mb-8">
                {members.map(member => (
                    <div key={member.id} className="p-4 bg-slate-800/30 rounded-lg">
                        <div className="flex flex-wrap justify-between items-center gap-3">
                            <div>
                                <h3 className="font-semibold">
                                    {member.username}
                                    {member.id === user?.id && <span className="ml-2 text-xs font-normal text-slate-400">(you)</span>}
                                </h3>
                                <p className="text-sm text-slate-400">{describe(member)}</p>
                            </div>
                            {pinMemberId !== member.id && (
                                <div className="flex gap-3 text-sm">
                                    {hasLogin(member) && (
                                        <button onClick={() => openPinForm(member, 'reset')} className="text-slate-400 hover:text-white">
                                            {member.id === user?.id ? 'Change my PIN' : 'Reset PIN'}
                                        </button>
                                    )}
                                    {member.role === 'CHILD' && member.has_allowance && (
                                        <button onClick={() => handleRemoveAllowance(member)} className="text-slate-400 hover:text-white">
                                            Remove allowance
                                        </button>
                                    )}
                                    {member.role === 'CHILD' && !member.has_allowance && (
                                        <button onClick={() => openPinForm(member, 'allowance')} className="btn-primary text-sm">
                                            Give own allowance
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>

                        {pinMemberId === member.id && (
                            <form onSubmit={(e) => handlePinSubmit(e, member)} className="mt-3 flex flex-col gap-2 sm:flex-row">
                                <div className="flex-1">
                                    <label htmlFor={`pin-${member.id}`} className="sr-only">New PIN for {member.username}</label>
                                    <PinInput
                                        id={`pin-${member.id}`}
                                        value={memberPin}
                                        onChange={setMemberPin}
                                        placeholder={pinAction === 'allowance' ? 'PIN for logging in (4 digits)' : 'New PIN (4 digits)'}
                                        autoComplete="new-password"
                                    />
                                </div>
                                <div className="flex gap-2">
                                    <button type="submit" className="btn-primary text-sm" disabled={!isValidPin(memberPin)}>Save</button>
                                    <button type="button" onClick={closePinForm} className="px-3 text-slate-400 hover:text-white text-sm">
                                        Cancel
                                    </button>
                                </div>
                            </form>
                        )}
                    </div>
                ))}
            </div>

            <h3 className="text-lg font-semibold mb-3">Add a family member</h3>
            <form onSubmit={handleAdd} className="space-y-3">
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="new-member-name" className="text-sm font-semibold text-slate-300">Name</label>
                    <input
                        id="new-member-name"
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder="Name they log in with"
                        className="w-full p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white placeholder-slate-500 focus:outline-none focus:border-blue-400"
                        required
                    />
                </div>
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="new-member-type" className="text-sm font-semibold text-slate-300">Type</label>
                    <select
                        id="new-member-type"
                        value={newType}
                        onChange={(e) => setNewType(e.target.value as MemberType)}
                        className="w-full p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white"
                    >
                        {(Object.keys(MEMBER_TYPES) as MemberType[]).map(type => (
                            <option key={type} value={type}>{MEMBER_TYPES[type]}</option>
                        ))}
                    </select>
                </div>
                {newType !== 'DEPENDENT_CHILD' && (
                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="new-member-pin" className="text-sm font-semibold text-slate-300">PIN</label>
                        <PinInput id="new-member-pin" value={newPin} onChange={setNewPin} autoComplete="new-password" />
                        <small className="text-slate-500">Tell them their PIN; they log in with their name and this PIN.</small>
                    </div>
                )}
                <button type="submit" className="btn-primary w-full">+ Add {newType === 'PARENT' ? 'Parent' : 'Child'}</button>
            </form>
        </div>
    );
}
