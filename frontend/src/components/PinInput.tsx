import { useState } from 'react';
import { PIN_LENGTH } from '../pin';

interface PinInputProps {
    id: string;
    value: string;
    onChange: (pin: string) => void;
    onBlur?: () => void;
    placeholder?: string;
    hasError?: boolean;
    autoComplete?: 'current-password' | 'new-password';
}

// Masked PIN field with a show/hide toggle; only accepts digits
export default function PinInput({
    id,
    value,
    onChange,
    onBlur,
    placeholder = '4-digit PIN',
    hasError = false,
    autoComplete = 'current-password',
}: PinInputProps) {
    const [showPin, setShowPin] = useState(false);

    return (
        <div className="relative">
            <input
                id={id}
                type={showPin ? 'text' : 'password'}
                inputMode="numeric"
                autoComplete={autoComplete}
                maxLength={PIN_LENGTH}
                value={value}
                onChange={(e) => {
                    if (/^\d*$/.test(e.target.value)) onChange(e.target.value);
                }}
                onBlur={onBlur}
                placeholder={placeholder}
                aria-invalid={hasError}
                className={`w-full p-3 pr-12 rounded-lg bg-slate-800/50 border text-white tracking-widest placeholder:tracking-normal placeholder-slate-500 focus:outline-none ${
                    hasError ? 'border-red-400 focus:border-red-400' : 'border-slate-600 focus:border-blue-400'
                }`}
            />
            <button
                type="button"
                onClick={() => setShowPin(!showPin)}
                aria-label={showPin ? 'Hide PIN' : 'Show PIN'}
                className="absolute inset-y-0 right-0 px-3 text-lg text-slate-400 hover:text-white"
            >
                {showPin ? '🙈' : '👁️'}
            </button>
        </div>
    );
}
