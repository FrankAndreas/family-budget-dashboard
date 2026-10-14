# Converters for bank and Migros exports

Two small scripts turn exports into the app's [import format](../../docs/import-format.md). The app then
shows a preview and books the rows. They need Python 3.11 or newer and nothing else, so they run on a PC
or on the NAS.

| Script | Input | Output |
|---|---|---|
| `bank.py` | A bank account's CSV export: `IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date` | One row per booking, categorised by your rules |
| `migros.py` | The Migros receipt export ("Kassenbeleg"): `Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz` | One row per receipt and category on a "Migros" account |

## Set-up (once)

1. In the app, create the accounts the converters book on, e.g. "Household" and "Migros" (a plain account
   that works as a clearing account).
2. In **Settings → Data Management**, download **JSON Schema (for AI tools)** and save it, e.g. as
   `import-schema.json`. Download it again after adding accounts, children or investments.
3. Copy `converter.example.toml` to `converter.toml`, then fill in your IBANs, account names and rules.
   `converter.toml` and the `*-import.csv` files are git-ignored. Keep them out of the repository, because
   they contain your IBANs and bookings.

## Use

```sh
python3 tools/converters/bank.py   ~/Downloads/export.csv      --config converter.toml --schema import-schema.json
python3 tools/converters/migros.py ~/Downloads/kassenbeleg.csv --config converter.toml --schema import-schema.json
```

Each writes `<input>-import.csv` next to the input (`--output` to choose) and prints a report. Upload the
file in **Settings → Data Management → Import transactions**, check the preview and import.

If the config or the input has a problem (an unknown name, an invalid rule, an unreadable line), the
converter lists every problem and writes nothing.

## Bank converter

- **Rules** in `[[bank.rules]]`: the first match wins, and `match` is a regular expression, ignoring case. See
  the example file for every option. A booking rule only catches lines that fit its category: an expense
  category only debits, an income category only credits.
- **Card purchases** (`Einkauf <merchant> 06.09.2026, 08:45, Debit Mastercard-Nr. …`) get the purchase date
  and time from the text, and the merchant as their description. Card numbers and IBANs are never written.
- **Transfers** (`action = "transfer"`) are booked with the category Transfer and `direction` `out`/`in`. The
  other account's side comes from that account's own export: the joint account, or the Migros receipts.
- **Unrecognised lines** get `[bank.fallback]` (default: Unsorted / Other Income) and are listed in the report.
  Correct them in the app after importing, and add a rule so the next export is recognised.
- **References** are a hash of the line, so importing an overlapping export again only shows duplicates.
- **Balance check:** the report gives the bank's balance after the latest booking. Once everything is
  imported, the account in the app should show the same.

## Migros converter

- A receipt is the group of lines with the same date, branch, till and transaction number.
- Each article's category is chosen in this order:
  1. the first matching `[[migros.articles]]` rule, which can also set `for`;
  2. otherwise the first `[[migros.branches]]` rule;
  3. otherwise `default_category`.
- The amounts are the `Umsatz` values, taken as already discounted.
- A receipt and category with a negative total (returns, deposit) is booked as income in `refund_category`.
  A total of 0 is skipped.
- **Totals per day** in the report can be compared with the Migros transfers from the bank. The Migros
  account should end near 0. A lost receipt, a purchase without the Cumulus card, or a gift card leaves a
  difference: book it by hand on the Migros account (e.g. Groceries for a missing receipt).
- Changing the rules and converting the same receipts again gives them new references. The preview then
  doesn't recognise them as already imported, so convert only new receipts.
