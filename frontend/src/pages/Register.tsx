import { useState } from 'react';
import { useAuth } from '../AuthContext';
import { errorMessage } from '../api';
import { useNavigate } from 'react-router-dom';

export default function Register() {
    const [username, setUsername] = useState('');
    const [pin, setPin] = useState('');
    const [role, setRole] = useState<'PARENT' | 'CHILD'>('PARENT');
    const [error, setError] = useState('');
    const { register } = useAuth();
    const navigate = useNavigate();

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (pin.length < 4) {
            setError("PIN must be at least 4 digits");
            return;
        }
        try {
            await register(username, pin, role);
            navigate('/');
        } catch (err) {
            setError(errorMessage(err, 'Registration failed'));
        }
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4">
            <div className="glass-card p-8 w-full max-w-sm text-center">
                <h2 className="text-2xl font-bold mb-6 text-white">Create Account</h2>

                {error && <p className="text-red-400 mb-4">{error}</p>}

                <form onSubmit={handleSubmit} className="flex flex-col gap-4">
                    <input
                        type="text"
                        placeholder="Username"
                        value={username}
                        onChange={(e) => setUsername(e.target.value)}
                        className="w-full p-3 rounded bg-slate-800/50 border border-slate-600 text-white placeholder-slate-400 focus:outline-none focus:border-blue-400"
                    />

                    <input
                        type="password"
                        placeholder="PIN (4+ digits)"
                        value={pin}
                        onChange={(e) => {
                            if (/^\d*$/.test(e.target.value)) {
                                setPin(e.target.value)
                            }
                        }}
                        maxLength={6}
                        className="w-full p-3 rounded bg-slate-800/50 border border-slate-600 text-white placeholder-slate-400 focus:outline-none focus:border-blue-400 text-center text-lg tracking-widest"
                    />

                    <div className="flex gap-4 justify-center my-2">
                        <label className={`flex-1 p-2 rounded cursor-pointer border ${role === 'PARENT' ? 'bg-blue-500/20 border-blue-400' : 'border-slate-700'}`}>
                            <input type="radio" name="role" value="PARENT" checked={role === 'PARENT'} onChange={() => setRole('PARENT')} className="hidden" />
                            Parent
                        </label>
                        <label className={`flex-1 p-2 rounded cursor-pointer border ${role === 'CHILD' ? 'bg-indigo-500/20 border-indigo-400' : 'border-slate-700'}`}>
                            <input type="radio" name="role" value="CHILD" checked={role === 'CHILD'} onChange={() => setRole('CHILD')} className="hidden" />
                            Child
                        </label>
                    </div>

                    <button
                        type="submit"
                        className="btn-primary w-full mt-2"
                        disabled={!username || pin.length < 4}
                    >
                        Register & Login
                    </button>
                </form>

                <p className="mt-4 text-sm text-slate-400">
                    Already have an account? <a href="/login" className="text-blue-400 hover:text-blue-300">Login</a>
                </p>
            </div>
        </div>
    );
}
