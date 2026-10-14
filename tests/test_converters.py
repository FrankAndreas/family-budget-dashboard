"""The bank and Migros converters in tools/converters (all data invented)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.converters import bank, common, migros  # noqa: E402

IBAN = "CH9300762011623852957"
HEADER = "IBAN;Booked At;Text;Credit/Debit Amount;Balance;Valuta Date"


def line(booked, text, amount, balance):
    return f"{IBAN};{booked} 00:00:00.0;{text};{amount};{balance};{booked} 00:00:00.0"


EXPORT = [
    line(
        "2026-09-07", "Einkauf Bäckerei Muster 06.09.2026, 08:45, Debit Mastercard-Nr. 123456xxxxxx9999", -22.1, 900.0
    ),
    line("2026-09-07", "Dauerauftrag Alex und Sam Muster", -10.0, 922.1),
    line("2026-09-14", "Zahlung TWINT MUSTER, KIM", -8.3, 1000.0),
    line("2026-09-14", "Übertrag von Sparkonto CH56 0483 5012 3456 7800 9", 40.0, 1008.3),
    line("2026-08-25", "Gutschrift ACME AG", 4000.0, 968.3),
    line("2026-08-24", "Gutschrift TWINT MUSTER, ROBIN", 5.0, 30.0),
    line("2026-08-27", "Dauerauftrag Leasing Bank AG", -350.0, 25.0),
    line("2026-08-28", "Zahlung Telco AG", -60.4, 375.0),
    line("2026-08-31", "LSV KRANKENKASSE AG", -400.0, 435.4),
    line("2026-08-31", "LSV Viseca Payment Services SA", -500.0, 835.4),
    line("2026-09-01", "Einkauf TWINT MIGROS M BEISPIEL", -84.3, 1100.0),
    line("2026-09-02", "Einkauf TWINT KIOSK", -3.0, 1097.0),
]

SCHEMA = {
    "properties": {
        "transactions": {
            "items": {
                "properties": {
                    "account": {"enum": ["Household", "Migros"]},
                    "owner": {"enum": ["Alex"]},
                    "for": {"enum": ["Kim"]},
                    "item": {"enum": ["Family car"]},
                }
            }
        }
    },
    "x-category-types": {
        "Groceries": "EXPENSE",
        "Transportation": "EXPENSE",
        "Healthcare": "EXPENSE",
        "Utilities": "EXPENSE",
        "Unsorted": "EXPENSE",
        "Other Expense": "EXPENSE",
        "Salary": "INCOME",
        "Other Income": "INCOME",
        "Reimbursements": "INCOME",
        "Transfer": "TRANSFER",
    },
}

BANK_CONFIG = {
    "bank": {
        "accounts": {"CH93 0076 2011 6238 5295 7": {"account": "Household", "owner": "Alex"}},
        "fallback": {"expense": "Unsorted", "income": "Other Income"},
        "rules": [
            {"match": r"^Einkauf .*\bMIGROS\b", "action": "transfer", "description": "Migros"},
            {"match": "^LSV Viseca", "action": "transfer"},
            {"match": "^Übertrag (von|auf) ", "action": "transfer"},
            {"match": r"^Dauerauftrag Alex und Sam", "action": "transfer"},
            {"match": "^Dauerauftrag Leasing", "category": "Transportation", "item": "Family car"},
            {"match": "^Gutschrift TWINT ", "category": "Reimbursements"},
            {"match": "^Gutschrift ACME", "category": "Salary"},
            {"match": "^LSV KRANKENKASSE", "category": "Healthcare"},
            {"match": "^Zahlung Telco", "category": "Utilities"},
            {"match": "Bäckerei", "category": "Groceries"},
            {"match": "^Zahlung TWINT MUSTER, KIM", "category": "Other Expense", "for": "Kim"},
            {"match": "^Einkauf TWINT KIOSK", "action": "ignore"},
        ],
    }
}


def bank_rows(lines, encoding="utf-8", tmp_path=None):
    path = tmp_path / "export.csv"
    path.write_bytes(("\n".join([HEADER, *lines]) + "\n").encode(encoding))
    return common.read_rows(path, bank.COLUMNS)


@pytest.fixture
def schema():
    return common.Schema(SCHEMA)


def by_ref(result):
    return {row["description"]: row for row in result.rows}


class TestBank:
    @pytest.fixture
    def result(self, tmp_path, schema):
        return bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), BANK_CONFIG, schema)

    def test_card_purchase(self, result):
        row = by_ref(result)["Bäckerei Muster"]
        assert row["date"] == "2026-09-06T08:45:00+02:00"
        assert row["category"] == "Groceries" and row["amount"] == "22.10"
        assert row["account"] == "Household" and row["owner"] == "Alex"
        assert row["direction"] == ""

    def test_card_number_and_iban_removed(self, result):
        texts = " ".join(row["description"] for row in result.rows)
        assert "123456" not in texts and "9999" not in texts
        assert "CH56" not in texts and "0483" not in texts

    def test_transfers(self, result):
        rows = by_ref(result)
        assert rows["Migros"]["category"] == "Transfer" and rows["Migros"]["direction"] == "out"
        assert rows["Migros"]["date"] == "2026-09-01"
        assert rows["Übertrag von Sparkonto"]["direction"] == "in"
        assert rows["Dauerauftrag Alex und Sam Muster"]["direction"] == "out"
        assert rows["LSV Viseca Payment Services SA"]["category"] == "Transfer"
        assert result.transfers == 4

    def test_booked(self, result):
        rows = by_ref(result)
        assert rows["Gutschrift ACME AG"]["category"] == "Salary"
        assert rows["Gutschrift TWINT MUSTER, ROBIN"]["category"] == "Reimbursements"
        assert rows["Dauerauftrag Leasing Bank AG"]["item"] == "Family car"
        assert rows["Zahlung TWINT MUSTER, KIM"]["for"] == "Kim"
        assert all(float(row["amount"]) > 0 for row in result.rows)

    def test_ignored(self, result):
        assert "Einkauf TWINT KIOSK" not in by_ref(result)
        assert [text for _, text, _ in result.ignored] == ["Einkauf TWINT KIOSK"]

    def test_balance_is_latest_booking(self, result):
        # Two lines on 2026-09-14: the first one in the file wins
        assert result.balance == ("2026-09-14", 1000.0)

    def test_reference(self, tmp_path, schema, result):
        refs = [row["reference"] for row in result.rows]
        assert len(set(refs)) == len(refs)
        assert all(ref.startswith("bank:") and len(ref) == 21 for ref in refs)
        again = bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), BANK_CONFIG, schema)
        assert [row["reference"] for row in again.rows] == refs

    def test_same_purchase_twice_distinct(self, tmp_path, schema):
        lines = [
            line("2026-09-02", "Einkauf TWINT MIGROS M BEISPIEL", -5.0, 95.0),
            line("2026-09-02", "Einkauf TWINT MIGROS M BEISPIEL", -5.0, 90.0),
        ]
        result = bank.convert(bank_rows(lines, tmp_path=tmp_path), BANK_CONFIG, schema)
        assert result.rows[0]["reference"] != result.rows[1]["reference"]

    def test_first_match_wins(self, tmp_path, schema):
        config = {"bank": {**BANK_CONFIG["bank"], "rules": [{"match": "TWINT", "category": "Other Expense"}]}}
        config["bank"]["rules"] += BANK_CONFIG["bank"]["rules"]
        result = bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        assert by_ref(result)["Einkauf TWINT MIGROS M BEISPIEL"]["category"] == "Other Expense"

    def test_rule_only_matches_its_sign(self, tmp_path, schema):
        # An expense rule doesn't catch a credit, and sign = "credit" doesn't catch a debit
        rules = [
            {"match": "TWINT", "category": "Groceries"},
            {"match": "Telco", "sign": "credit", "category": "Other Income"},
        ]
        config = {"bank": {**BANK_CONFIG["bank"], "rules": rules}}
        result = bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        rows = by_ref(result)
        assert rows["Gutschrift TWINT MUSTER, ROBIN"]["category"] == "Other Income"
        assert rows["Zahlung Telco AG"]["category"] == "Unsorted"

    def test_fallback_and_unrecognised(self, tmp_path, schema):
        config = {"bank": {**BANK_CONFIG["bank"], "rules": []}}
        result = bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        rows = by_ref(result)
        assert rows["Zahlung Telco AG"]["category"] == "Unsorted"
        assert rows["Gutschrift ACME AG"]["category"] == "Other Income"
        assert len(result.unrecognised) == len(EXPORT)
        assert result.unrecognised[0] == (2, "Einkauf Bäckerei Muster", -22.1)

    def test_zero_amount_skipped(self, tmp_path, schema):
        result = bank.convert(
            bank_rows([line("2026-09-02", "Zahlung Telco AG", 0, 5)], tmp_path=tmp_path), BANK_CONFIG, schema
        )
        assert result.rows == [] and result.skipped == [(2, "Zahlung Telco AG")]

    def test_winter_offset(self, tmp_path, schema):
        lines = [line("2026-12-02", "Einkauf Bäckerei Muster 01.12.2026, 23:30, Debit Mastercard-Nr. 1234xx", -2, 1)]
        result = bank.convert(bank_rows(lines, tmp_path=tmp_path), BANK_CONFIG, schema)
        assert result.rows[0]["date"] == "2026-12-01T23:30:00+01:00"

    def test_windows_1252(self, tmp_path, schema):
        result = bank.convert(bank_rows(EXPORT, encoding="cp1252", tmp_path=tmp_path), BANK_CONFIG, schema)
        assert "Bäckerei Muster" in by_ref(result)

    def test_unknown_iban_stops(self, tmp_path, schema):
        lines = [EXPORT[0].replace(IBAN, "CH4431999123000889012")]
        with pytest.raises(common.Problems) as error:
            bank.convert(bank_rows(lines, tmp_path=tmp_path), BANK_CONFIG, schema)
        assert "line 2: IBAN CH4431999123000889012 is not in [bank.accounts]" in error.value.problems

    def test_bad_amount_stops(self, tmp_path, schema):
        with pytest.raises(common.Problems) as error:
            bank.convert(
                bank_rows([line("2026-09-02", "Zahlung Telco AG", "x", 5)], tmp_path=tmp_path), BANK_CONFIG, schema
            )
        assert "line 2: amount 'x' is not a number" in error.value.problems

    def test_missing_column(self, tmp_path):
        path = tmp_path / "export.csv"
        path.write_text("IBAN;Text\nx;y\n", encoding="utf-8")
        with pytest.raises(common.Problems) as error:
            common.read_rows(path, bank.COLUMNS)
        assert "missing column 'booked at'" in error.value.problems


class TestBankConfig:
    @pytest.mark.parametrize(
        "rule, problem",
        [
            ({"match": "x", "category": "Nope"}, "rule 1: unknown category 'Nope'"),
            ({"match": "x"}, "rule 1: category is required (or action = transfer / ignore)"),
            ({"match": "(", "category": "Groceries"}, "rule 1: invalid match '('"),
            ({"category": "Groceries"}, "rule 1: match is required"),
            (
                {"match": "x", "category": "Groceries", "sign": "credit"},
                "rule 1: Groceries is an expense but sign is credit",
            ),
            ({"match": "x", "category": "Transfer"}, "rule 1: use action = transfer instead of the category Transfer"),
            ({"match": "x", "category": "Groceries", "item": "Boat"}, "rule 1: unknown item 'Boat'"),
            ({"match": "x", "category": "Groceries", "for": "Nobody"}, "rule 1: unknown child 'Nobody'"),
            ({"match": "x", "action": "move"}, "rule 1: action must be book, transfer or ignore"),
        ],
    )
    def test_rule_problems(self, tmp_path, schema, rule, problem):
        config = {"bank": {**BANK_CONFIG["bank"], "rules": [rule]}}
        with pytest.raises(common.Problems) as error:
            bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        assert problem in error.value.problems

    def test_account_and_fallback_problems(self, tmp_path, schema):
        config = {
            "bank": {
                "accounts": {IBAN: {"account": "Savings", "owner": "Nobody"}},
                "fallback": {"expense": "Salary", "income": "Nope"},
                "rules": [],
            }
        }
        with pytest.raises(common.Problems) as error:
            bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        assert set(error.value.problems) >= {
            f"[bank.accounts] {IBAN}: unknown account 'Savings'",
            f"[bank.accounts] {IBAN}: unknown owner 'Nobody'",
            "[bank.fallback] expense: Salary is not an expense category",
            "[bank.fallback] income: unknown category 'Nope'",
        }

    def test_names_ignore_case(self, tmp_path, schema):
        config = {"bank": {**BANK_CONFIG["bank"], "rules": [{"match": "telco", "category": "utilities"}]}}
        result = bank.convert(bank_rows(EXPORT, tmp_path=tmp_path), config, schema)
        assert by_ref(result)["Zahlung Telco AG"]["category"] == "Utilities"


MIGROS_HEADER = "Datum;Zeit;Filiale;Kassennummer;Transaktionsnummer;Artikel;Menge;Aktion;Umsatz"
RECEIPTS = [
    "01.09.2026;17:05:12;MM Beispiel;262;89;Spaghetti;2;0.00;3.80",
    "01.09.2026;17:05:12;MM Beispiel;262;89;Windeln Gr. 4;1;2.00;17.90",
    "01.09.2026;17:05:12;MM Beispiel;262;89;Tomaten;1;0.00;2.60",
    "01.09.2026;18:10:00;Do it + Garden Beispiel;5;12;Blumenerde;1;0.00;9.95",
    "02.09.2026;09:00:00;MM Beispiel;262;90;Brot;1;0.00;3.20",
    "02.09.2026;09:30:00;MM Beispiel;262;91;Leergut;1;0.00;-1.50",
    "03.12.2026;08:00:00;MM Beispiel;262;92;Milch;1;0.00;1.60",
    "03.12.2026;08:00:00;MM Beispiel;262;92;Milch;-1;0.00;-1.60",
]
MIGROS_CONFIG = {
    "migros": {
        "account": "Migros",
        "owner": "Alex",
        "default_category": "Groceries",
        "refund_category": "Reimbursements",
        "branches": [{"match": "Do it|Garden", "category": "Other Expense"}],
        "articles": [{"match": "Windeln", "category": "Other Expense", "for": "Kim"}],
    }
}


def migros_rows(tmp_path, lines=RECEIPTS):
    path = tmp_path / "kassenbeleg.csv"
    path.write_text("\n".join([MIGROS_HEADER, *lines]) + "\n", encoding="utf-8")
    return common.read_rows(path, migros.COLUMNS)


class TestMigros:
    @pytest.fixture
    def result(self, tmp_path, schema):
        return migros.convert(migros_rows(tmp_path), MIGROS_CONFIG, schema)

    def test_one_row_per_receipt_and_category(self, result):
        first = [row for row in result.rows if row["reference"].startswith("migros:2026-09-01:MM Beispiel:262:89:")]
        assert [(r["category"], r["amount"], r["for"]) for r in first] == [
            ("Groceries", "6.40", ""),
            ("Other Expense", "17.90", "Kim"),
        ]
        assert first[0]["date"] == "2026-09-01T17:05:12+02:00"
        assert first[0]["account"] == "Migros" and first[0]["owner"] == "Alex"
        assert first[0]["description"] == "Migros MM Beispiel"

    def test_branch_rule(self, result):
        row = next(r for r in result.rows if "Do it" in r["description"])
        assert row["category"] == "Other Expense" and row["amount"] == "9.95"

    def test_negative_sum_is_a_refund(self, result):
        row = next(r for r in result.rows if ":91:" in r["reference"])
        assert row["category"] == "Reimbursements" and row["amount"] == "1.50"

    def test_zero_sum_skipped(self, result):
        assert not any(":92:" in r["reference"] for r in result.rows)
        assert result.skipped == ["2026-12-03 MM Beispiel 262/92"]

    def test_reference(self, result):
        assert result.rows[0]["reference"] == "migros:2026-09-01:MM Beispiel:262:89:Groceries:"
        assert len({r["reference"] for r in result.rows}) == len(result.rows)

    def test_totals_per_day(self, result):
        assert result.totals == {"2026-09-01": 34.25, "2026-09-02": 1.70, "2026-12-03": 0.0}

    def test_receipt_count(self, result):
        assert result.receipts == 5

    def test_config_problems(self, tmp_path, schema):
        config = {
            "migros": {
                "account": "Coop",
                "default_category": "Salary",
                "refund_category": "Groceries",
                "articles": [{"match": "x", "category": "Nope"}, {"match": "y", "category": "Groceries", "for": "Z"}],
                "branches": [{"match": "["}],
            }
        }
        with pytest.raises(common.Problems) as error:
            migros.convert(migros_rows(tmp_path), config, schema)
        assert set(error.value.problems) >= {
            "[migros] account: unknown account 'Coop'",
            "[migros] default_category: Salary is not an expense category",
            "[migros] refund_category: Groceries is not an income category",
            "[[migros.articles]] 1: unknown category 'Nope'",
            "[[migros.articles]] 2: unknown child 'Z'",
            "[[migros.branches]] 1: invalid match '['",
            "[[migros.branches]] 1: category is required",
        }

    def test_bad_amount(self, tmp_path, schema):
        rows = migros_rows(tmp_path, ["01.09.2026;17:05:12;MM Beispiel;262;89;Brot;1;0.00;abc"])
        with pytest.raises(common.Problems) as error:
            migros.convert(rows, MIGROS_CONFIG, schema)
        assert "line 2: Umsatz 'abc' is not a number" in error.value.problems


class TestCommandLine:
    def test_bank_cli_output_is_accepted_by_the_app(self, tmp_path, client, capsys):
        from helpers import BASE_URL, create_account, register

        headers = register(client, "Alex")
        for name in ("Household", "Migros"):
            create_account(client, headers, name)
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(client.get(f"{BASE_URL}/import/schema", headers=headers).json()))
        config_path = tmp_path / "converter.toml"
        config_path.write_text(
            f'[bank.accounts]\n"{IBAN}" = {{ account = "Household" }}\n'
            '[[bank.rules]]\nmatch = "MIGROS"\naction = "transfer"\n'
            '[[bank.rules]]\nmatch = "Telco"\ncategory = "Utilities"\n',
            encoding="utf-8",
        )
        export = tmp_path / "export.csv"
        export.write_text("\n".join([HEADER, *EXPORT]) + "\n", encoding="utf-8")

        assert bank.main([str(export), "--config", str(config_path), "--schema", str(schema_path)]) == 0
        report = capsys.readouterr().out
        assert "Bank balance on 2026-09-14: 1000.00" in report
        assert "not recognised" in report

        output = tmp_path / "export-import.csv"
        response = client.post(
            f"{BASE_URL}/import/preview", files={"file": ("x.csv", output.read_bytes())}, headers=headers
        )
        assert response.status_code == 200
        assert response.json()["errors"] == 0, response.json()

    def test_cli_problems_write_nothing(self, tmp_path, capsys):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(SCHEMA))
        config_path = tmp_path / "converter.toml"
        config_path.write_text('[[bank.rules]]\nmatch = "x"\ncategory = "Nope"\n', encoding="utf-8")
        export = tmp_path / "export.csv"
        export.write_text("\n".join([HEADER, *EXPORT]) + "\n", encoding="utf-8")
        assert bank.main([str(export), "--config", str(config_path), "--schema", str(schema_path)]) == 1
        assert "unknown category 'Nope'" in capsys.readouterr().out
        assert not (tmp_path / "export-import.csv").exists()

    def test_migros_cli(self, tmp_path, capsys):
        schema_path = tmp_path / "schema.json"
        schema_path.write_text(json.dumps(SCHEMA))
        config_path = tmp_path / "converter.toml"
        config_path.write_text('[migros]\naccount = "Migros"\n', encoding="utf-8")
        receipts = tmp_path / "kassenbeleg.csv"
        receipts.write_text("\n".join([MIGROS_HEADER, *RECEIPTS]) + "\n", encoding="utf-8")
        assert migros.main([str(receipts), "--config", str(config_path), "--schema", str(schema_path)]) == 0
        lines = (tmp_path / "kassenbeleg-import.csv").read_text(encoding="utf-8").splitlines()
        assert lines[0] == ",".join(common.OUTPUT_FIELDS)
        assert "2026-09-01: 34.25" in capsys.readouterr().out
