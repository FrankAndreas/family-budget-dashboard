import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../AuthContext';
import { errorMessage, errorStatus } from '../api';
import PinInput from '../components/PinInput';
import { isValidPin } from '../pin';

export default function Login() {
    const { login } = useAuth();
    const navigate = useNavigate();
    const [username, setUsername] = useState('');
    const [pin, setPin] = useState('');
    const [usernameError, setUsernameError] = useState('');
    const [pinError, setPinError] = useState('');
    const [error, setError] = useState('');
    const [loading, setLoading] = useState(false);
    // Field errors only show once the user has tried to log in
    const [submitted, setSubmitted] = useState(false);

    const validate = () => {
        const nameMissing = !username.trim();
        const pinInvalid = !isValidPin(pin);
        setUsernameError(nameMissing ? 'Please enter your name' : '');
        setPinError(!pin ? 'Please enter your PIN' : pinInvalid ? 'The PIN has 4 digits' : '');
        return !nameMissing && !pinInvalid;
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSubmitted(true);
        if (!validate()) return;

        setError('');
        setLoading(true);
        try {
            await login(username.trim(), pin);
            navigate('/');
        } catch (err) {
            // 403 means the account was deactivated; anything else is a wrong name or PIN
            setError(errorStatus(err) === 403 ? errorMessage(err, 'This account has been deactivated') : 'Wrong name or PIN');
            setPin('');
        } finally {
            setLoading(false);
        }
    };

    const revalidate = () => {
        if (submitted) validate();
    };

    return (
        <div className="flex min-h-screen items-center justify-center p-4">
            <div className="glass-card w-full max-w-sm p-8">
                <div className="mb-8 text-center">
                    <h1 className="bg-gradient-to-r from-cyan-400 to-fuchsia-400 bg-clip-text text-3xl font-bold text-transparent">
                        Family Budget
                    </h1>
                    <p className="mt-2 text-slate-400">Log in with your name and PIN</p>
                </div>

                <form onSubmit={handleSubmit} noValidate className="flex flex-col gap-5">
                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="username" className="text-sm font-semibold text-slate-300">Name</label>
                        <input
                            id="username"
                            type="text"
                            autoComplete="username"
                            autoFocus
                            value={username}
                            onChange={(e) => {
                                setUsername(e.target.value);
                                if (usernameError) setUsernameError('');
                            }}
                            onBlur={revalidate}
                            placeholder="Your name"
                            aria-invalid={!!usernameError}
                            className={`w-full rounded-lg border bg-slate-800/50 p-3 text-white placeholder-slate-500 focus:outline-none ${
                                usernameError ? 'border-red-400' : 'border-slate-600 focus:border-blue-400'
                            }`}
                        />
                        {usernameError && <small className="text-red-400">{usernameError}</small>}
                    </div>

                    <div className="flex flex-col gap-1.5">
                        <label htmlFor="pin" className="text-sm font-semibold text-slate-300">PIN</label>
                        <PinInput
                            id="pin"
                            value={pin}
                            onChange={(value) => {
                                setPin(value);
                                if (pinError) setPinError('');
                            }}
                            onBlur={revalidate}
                            hasError={!!pinError}
                        />
                        {pinError && <small className="text-red-400">{pinError}</small>}
                    </div>

                    {error && (
                        <div role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-center text-sm text-red-300">
                            {error}
                        </div>
                    )}

                    <button type="submit" className="btn-primary w-full py-3 text-lg" disabled={loading}>
                        {loading ? 'Logging in…' : 'Log in'}
                    </button>
                </form>

                <div className="mt-6 space-y-2 border-t border-slate-700 pt-4 text-center text-sm text-slate-400">
                    <p>New here? A parent adds family members in Settings → Family.</p>
                    <p>
                        First start? Log in as <strong className="text-slate-300">Admin</strong> with the PIN shown in the
                        backend log, then change it.
                    </p>
                </div>
            </div>
        </div>
    );
}
