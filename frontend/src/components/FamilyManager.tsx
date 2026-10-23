import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import api, { errorMessage } from '../api';
import { useAuth } from '../AuthContext';
import { useFamily } from '../useFamily';
import type { FamilyUser } from '../family';
import PinInput from './PinInput';
import RemoveMember from './RemoveMember';
import EmailAddresses from './EmailAddresses';
import type { PersonEmail } from '../inbox';
import { isValidPin } from '../pin';

type MemberType = 'PARENT' | 'ALLOWANCE_CHILD' | 'DEPENDENT_CHILD';

// Labels: family.types.<type> in the locale files
const MEMBER_TYPES: MemberType[] = ['PARENT', 'ALLOWANCE_CHILD', 'DEPENDENT_CHILD'];

// Everyone who logs in has a PIN; younger children don't log in
const hasLogin = (member: FamilyUser) => member.role === 'PARENT' || member.has_allowance;

// Parents only: add family members, reset PINs, and switch children between "dependent" and "own allowance"
export default function FamilyManager() {
    const { t } = useTranslation();
    const { user, login, refreshUser } = useAuth();
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

    // Member being removed (form that decides where their items go)
    const [removeMemberId, setRemoveMemberId] = useState<string | null>(null);

    // Addresses receipt mails are taken from (issue #57)
    const [emails, setEmails] = useState<PersonEmail[]>([]);
    const loadEmails = useCallback(() => {
        api.get('/api/v1/emails')
            .then(response => setEmails(response.data))
            .catch(err => setError(errorMessage(err, t('emails.failed'))));
    }, [t]);
    useEffect(loadEmails, [loadEmails]);

    // Member being renamed, and the new name
    const [renameMemberId, setRenameMemberId] = useState<string | null>(null);
    const [newMemberName, setNewMemberName] = useState('');

    const describe = (member: FamilyUser) => {
        if (member.role === 'PARENT') return t('family.parent');
        return member.has_allowance ? t('family.ownAllowance') : t('family.noOwnMoney');
    };

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
            setError(t('family.pinDigits'));
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
            showResult(t(newType === 'DEPENDENT_CHILD' ? 'family.added' : 'family.addedWithLogin', { name }));
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, t('family.addFailed')));
        }
    };

    const openRemoveForm = (member: FamilyUser) => {
        closePinForm();
        closeRenameForm();
        setRemoveMemberId(member.id);
    };

    const openRenameForm = (member: FamilyUser) => {
        closePinForm();
        setRemoveMemberId(null);
        setRenameMemberId(member.id);
        setNewMemberName(member.username);
    };

    const closeRenameForm = () => {
        setRenameMemberId(null);
        setNewMemberName('');
    };

    const handleRename = async (e: React.FormEvent, member: FamilyUser) => {
        e.preventDefault();
        const name = newMemberName.trim();
        if (name === member.username) {
            closeRenameForm();
            return;
        }

        try {
            await api.put(`/api/v1/users/${member.id}`, { username: name });
            closeRenameForm();
            showResult(t(hasLogin(member) ? 'family.renamedWithLogin' : 'family.renamed', { from: member.username, to: name }));
            // The header greets the logged-in user by name
            if (member.id === user?.id) await refreshUser();
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, t('family.renameFailed')));
        }
    };

    const openPinForm = (member: FamilyUser, action: 'reset' | 'allowance') => {
        closeRenameForm();
        setRemoveMemberId(null);
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
            setError(t('family.pinDigits'));
            return;
        }

        try {
            const update = pinAction === 'allowance' ? { has_allowance: true, pin: memberPin } : { pin: memberPin };
            await api.put(`/api/v1/users/${member.id}`, update);
            // A new PIN ends all logins of that person; your own: log in again here with the new PIN
            if (member.id === user?.id) await login(member.username, memberPin);
            closePinForm();
            showResult(t(pinAction === 'allowance' ? 'family.allowanceGiven' : 'family.pinChanged', { name: member.username }));
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, t('family.pinFailed')));
        }
    };

    const handleRemoveAllowance = async (member: FamilyUser) => {
        if (!confirm(t('family.confirmRemoveAllowance', { name: member.username }))) return;
        try {
            await api.put(`/api/v1/users/${member.id}`, { has_allowance: false });
            showResult(t('family.allowanceRemoved', { name: member.username }));
        } catch (err) {
            setNotice('');
            setError(errorMessage(err, t('family.updateFailed')));
        }
    };

    return (
        <div className="glass-card p-6">
            <h2 className="text-2xl font-bold mb-2">{t('family.title')}</h2>
            <p className="text-slate-400 mb-6 text-sm">{t('family.intro')}</p>

            {(error || notice) && (
                <div className={`mb-4 p-3 rounded-lg flex justify-between items-center border ${error
                    ? 'bg-red-500/20 border-red-500/50 text-red-300'
                    : 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                    }`}>
                    <span>{error || notice}</span>
                    <button onClick={() => { setError(''); setNotice(''); }} className="hover:text-white" aria-label={t('family.dismiss')}>✕</button>
                </div>
            )}

            <div className="space-y-3 mb-8">
                {members.map(member => (
                    <div key={member.id} className="p-4 bg-slate-800/30 rounded-lg">
                        <div className="flex flex-wrap justify-between items-center gap-3">
                            <div>
                                <h3 className="font-semibold">
                                    {member.username}
                                    {member.id === user?.id && <span className="ml-2 text-xs font-normal text-slate-400">{t('family.you')}</span>}
                                </h3>
                                <p className="text-sm text-slate-400">{describe(member)}</p>
                            </div>
                            {pinMemberId !== member.id && renameMemberId !== member.id && removeMemberId !== member.id && (
                                <div className="flex gap-3 text-sm">
                                    <button onClick={() => openRenameForm(member)} className="text-slate-400 hover:text-white">
                                        {t('family.rename')}
                                    </button>
                                    {hasLogin(member) && (
                                        <button onClick={() => openPinForm(member, 'reset')} className="text-slate-400 hover:text-white">
                                            {member.id === user?.id ? t('family.changeMyPin') : t('family.resetPin')}
                                        </button>
                                    )}
                                    {member.role === 'CHILD' && member.has_allowance && (
                                        <button onClick={() => handleRemoveAllowance(member)} className="text-slate-400 hover:text-white">
                                            {t('family.removeAllowance')}
                                        </button>
                                    )}
                                    {member.role === 'CHILD' && !member.has_allowance && (
                                        <button onClick={() => openPinForm(member, 'allowance')} className="btn-primary text-sm">
                                            {t('family.giveAllowance')}
                                        </button>
                                    )}
                                    {member.id !== user?.id && (
                                        <button onClick={() => openRemoveForm(member)} className="text-slate-400 hover:text-red-400">
                                            {t('family.remove')}
                                        </button>
                                    )}
                                </div>
                            )}
                        </div>

                        <EmailAddresses member={member} addresses={emails.filter(e => e.user_id === member.id)}
                            onChanged={loadEmails} />

                        {removeMemberId === member.id && (
                            <RemoveMember
                                member={member}
                                onDone={(message) => { setRemoveMemberId(null); showResult(message); }}
                                onCancel={() => setRemoveMemberId(null)}
                            />
                        )}

                        {renameMemberId === member.id && (
                            <form onSubmit={(e) => handleRename(e, member)} className="mt-3 flex flex-col gap-2 sm:flex-row">
                                <label htmlFor={`name-${member.id}`} className="sr-only">{t('family.newNameFor', { name: member.username })}</label>
                                <input
                                    id={`name-${member.id}`}
                                    type="text"
                                    value={newMemberName}
                                    onChange={(e) => setNewMemberName(e.target.value)}
                                    autoFocus
                                    required
                                    className="flex-1 p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white focus:outline-none focus:border-blue-400"
                                />
                                <div className="flex gap-2">
                                    <button type="submit" className="btn-primary text-sm" disabled={!newMemberName.trim()}>{t('common.save')}</button>
                                    <button type="button" onClick={closeRenameForm} className="px-3 text-slate-400 hover:text-white text-sm">
                                        {t('common.cancel')}
                                    </button>
                                </div>
                            </form>
                        )}

                        {pinMemberId === member.id && (
                            <form onSubmit={(e) => handlePinSubmit(e, member)} className="mt-3 flex flex-col gap-2 sm:flex-row">
                                <div className="flex-1">
                                    <label htmlFor={`pin-${member.id}`} className="sr-only">{t('family.newPinFor', { name: member.username })}</label>
                                    <PinInput
                                        id={`pin-${member.id}`}
                                        value={memberPin}
                                        onChange={setMemberPin}
                                        placeholder={pinAction === 'allowance' ? t('family.pinForLogin') : t('family.newPin')}
                                        autoComplete="new-password"
                                    />
                                </div>
                                <div className="flex gap-2">
                                    <button type="submit" className="btn-primary text-sm" disabled={!isValidPin(memberPin)}>{t('common.save')}</button>
                                    <button type="button" onClick={closePinForm} className="px-3 text-slate-400 hover:text-white text-sm">
                                        {t('common.cancel')}
                                    </button>
                                </div>
                            </form>
                        )}
                    </div>
                ))}
            </div>

            <h3 className="text-lg font-semibold mb-3">{t('family.addMember')}</h3>
            <form onSubmit={handleAdd} className="space-y-3">
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="new-member-name" className="text-sm font-semibold text-slate-300">{t('family.name')}</label>
                    <input
                        id="new-member-name"
                        type="text"
                        value={newName}
                        onChange={(e) => setNewName(e.target.value)}
                        placeholder={t('family.namePlaceholder')}
                        className="w-full p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white placeholder-slate-500 focus:outline-none focus:border-blue-400"
                        required
                    />
                </div>
                <div className="flex flex-col gap-1.5">
                    <label htmlFor="new-member-type" className="text-sm font-semibold text-slate-300">{t('family.type')}</label>
                    <select
                        id="new-member-type"
                        value={newType}
                        onChange={(e) => setNewType(e.target.value as MemberType)}
                        className="w-full p-3 rounded-lg bg-slate-800/50 border border-slate-600 text-white"
                    >
                        {MEMBER_TYPES.map(type => (
                            <option key={type} value={type}>{t(`family.types.${type}`)}</option>
                        ))}
                    </select>
                </div>
                {newType !== 'DEPENDENT_CHILD' && (
                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="new-member-pin" className="text-sm font-semibold text-slate-300">{t('family.pin')}</label>
                        <PinInput id="new-member-pin" value={newPin} onChange={setNewPin} autoComplete="new-password" />
                        <small className="text-slate-500">{t('family.pinHint')}</small>
                    </div>
                )}
                <button type="submit" className="btn-primary w-full">{newType === 'PARENT' ? t('family.addParent') : t('family.addChild')}</button>
            </form>
        </div>
    );
}
