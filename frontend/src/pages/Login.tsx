import { useState } from 'react';
import { useAuth } from '../AuthContext';
import { errorMessage, errorStatus } from '../api';
import { useNavigate } from 'react-router-dom';

// Must match the PIN rules on the Register page (4-6 digits)
const MIN_PIN_LENGTH = 4;
const MAX_PIN_LENGTH = 6;

export default function Login() {
    const [username, setUsername] = useState('');
    const [pin, setPin] = useState('');
    const [error, setError] = useState('');
    const { login } = useAuth();
    const navigate = useNavigate();

    const handlePinClick = (num: string) => {
        if (pin.length < MAX_PIN_LENGTH) {
            setPin(prev => prev + num);
        }
    };

    const handleDelete = () => {
        setPin(prev => prev.slice(0, -1));
    };

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        try {
            await login(username, pin);
            navigate('/');
        } catch (err) {
            // 403 means the account was deactivated; show the server's reason
            setError(errorStatus(err) === 403 ? errorMessage(err, 'This account has been deactivated') : 'Invalid username or PIN');
            setPin('');
        }
    };

    return (
        <div className="flex flex-col items-center justify-center min-h-screen p-4">
            <div className="glass-card p-8 w-full max-w-sm text-center">
                <h2 className="text-2xl font-bold mb-6 text-white">Welcome Back</h2>

                {error && <p className="text-red-400 mb-4">{error}</p>}

                <input
                    type="text"
                    placeholder="Username"
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full mb-6 p-3 rounded bg-slate-800/50 border border-slate-600 text-white placeholder-slate-400 focus:outline-none focus:border-blue-400"
                />

                <div className="mb-6 flex justify-center gap-2 h-12">
                    {Array.from({ length: Math.max(MIN_PIN_LENGTH, pin.length) }, (_, i) => (
                        <div
                            key={i}
                            className={`w-4 h-4 rounded-full border border-slate-400 ${i < pin.length ? 'bg-blue-400 border-blue-400' : 'bg-transparent'
                                }`}
                        />
                    ))}
                </div>

                <div className="grid grid-cols-3 gap-4 mb-6">
                    {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((num) => (
                        <button
                            key={num}
                            onClick={() => handlePinClick(num.toString())}
                            className="w-16 h-16 rounded-full glass-card hover:bg-slate-700/50 flex items-center justify-center text-xl font-bold transition-all active:scale-95 mx-auto"
                        >
                            {num}
                        </button>
                    ))}
                    <div className="w-16 h-16" /> {/* Spacer */}
                    <button
                        onClick={() => handlePinClick('0')}
                        className="w-16 h-16 rounded-full glass-card hover:bg-slate-700/50 flex items-center justify-center text-xl font-bold transition-all active:scale-95 mx-auto"
                    >
                        0
                    </button>
                    <button
                        onClick={handleDelete}
                        className="w-16 h-16 rounded-full glass-card hover:bg-slate-700/50 flex items-center justify-center text-xl font-bold transition-all active:scale-95 mx-auto text-red-300"
                    >
                        ⌫
                    </button>
                </div>

                <button
                    onClick={handleSubmit}
                    className="btn-primary w-full"
                    disabled={!username || pin.length < MIN_PIN_LENGTH}
                >
                    Login
                </button>

                <p className="mt-4 text-sm text-slate-400">
                    First time? <a href="/register" className="text-blue-400 hover:text-blue-300">Create Account</a>
                </p>
            </div>
        </div>
    );
}
