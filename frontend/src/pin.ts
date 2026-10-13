// PINs are exactly 4 digits (same rule as the backend and the family-chore app)
export const PIN_LENGTH = 4;
export const isValidPin = (pin: string) => new RegExp(`^\\d{${PIN_LENGTH}}$`).test(pin);
