"""CSV importer: decoding, preview suggestions and mapped parsing.

Every fixture is synthetic and built here; none comes from a real bank export.
"""
import csv as csv_module
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from app.ledger.importers import (
    MAX_FILE_BYTES,
    CsvMapping,
    ImportFileError,
    amounts,
    csv_parser,
    dates,
    decode_bytes,
    decoding,
    detect_file_format,
    detect_format,
    parse_csv,
    preview_csv,
    row_key,
)
from app.ledger.importers.amounts import NumberFormat, parse_amount
from app.ledger.importers.errors import MAX_ISSUES, IssueLog

ACCOUNT = "acct-1"


def mapping(**overrides) -> CsvMapping:
    base = dict(
        delimiter=",", data_start=1, date_column=0, date_format="%Y-%m-%d", description_columns=(1,),
        amount_strategy="signed", amount_column=2,
    )
    return CsvMapping(**{**base, **overrides})


def amounts_of(result) -> list[Decimal]:
    return [item.amount for item in result.transactions]


# --------------------------------------------------------------------------- decoding


def test_decode_utf8_with_and_without_bom_normalizes_newlines():
    plain = decode_bytes(b"a,b\r\nc,d\re,f\n")
    assert plain.text == "a,b\nc,d\ne,f\n" and plain.encoding == "utf-8"
    bom = decode_bytes(b"\xef\xbb\xbfa,b\n")
    assert bom.text == "a,b\n" and bom.encoding == "utf-8"


def test_decode_utf16_with_bom_both_orders():
    text = "Date,Description,Amount\n2026-01-02,Caf" + chr(0xE9) + ",-3.00\n"
    for codec in ("utf-16-le", "utf-16-be"):
        bom = b"\xff\xfe" if codec.endswith("le") else b"\xfe\xff"
        decoded = decode_bytes(bom + text.encode(codec))
        assert decoded.encoding == "utf-16" and decoded.text == text


def test_decode_windows_1252_fallback():
    decoded = decode_bytes(b"Date,Description,Amount\n2026-01-02,Caf\xe9 \x80,-3.00\n")
    assert decoded.encoding == "windows-1252"
    assert "Caf" + chr(0xE9) + " " + chr(0x20AC) in decoded.text


@pytest.mark.parametrize("data,code", [
    (b"", "EMPTY_FILE"),
    (b"  \n\n", "EMPTY_FILE"),
    (b"\xff\xfe\x00\x00a\x00\x00\x00", "UNDECODABLE"),
    (b"a\x00b,c", "UNDECODABLE"),
    (b"\xef\xbb\xbf\xff\xfe", "UNDECODABLE"),
    (b"\xff\xfe\x00\xd8", "UNDECODABLE"),
])
def test_decode_refusals(data, code):
    with pytest.raises(ImportFileError) as caught:
        decode_bytes(data)
    assert caught.value.code == code


def test_decode_size_cap():
    with pytest.raises(ImportFileError) as caught:
        decode_bytes(b"a" * (MAX_FILE_BYTES + 1))
    assert caught.value.code == "FILE_TOO_LARGE" and caught.value.details == {"max_bytes": MAX_FILE_BYTES}


@pytest.mark.parametrize("text,expected", [
    ("OFXHEADER:100\nDATA:OFXSGML\n<OFX>", "ofx"),
    ('<?xml version="1.0"?>\n<?OFX OFXHEADER="200"?><OFX>', "ofx"),
    ("<OFX><SIGNONMSGSRSV1>", "ofx"),
    ("<html><body>", "unknown"),
    ("just words\nno delimiters", "unknown"),
    ("Date;Amount\n2026-01-01;5", "csv"),
    ("Date\tAmount", "csv"),
])
def test_detect_format(text, expected):
    assert detect_format(text) == expected


def test_detect_file_format_decodes_first():
    assert detect_file_format(b"\xef\xbb\xbfDate,Amount\n") == "csv"


def test_non_csv_bytes_refused_by_csv_functions():
    with pytest.raises(ImportFileError) as caught:
        preview_csv(b"OFXHEADER:100\n<OFX>")
    assert caught.value.code == "UNSUPPORTED_FORMAT"


# --------------------------------------------------------------------------- amounts and dates


@pytest.mark.parametrize("text,fmt,value,direction", [
    ("12.50", ".", "12.50", None),
    ("-12.50", ".", "-12.50", None),
    ("+12.5", ".", "12.50", None),
    ("$1,234.56", ".", "1234.56", None),
    ("-$1,234.56", ".", "-1234.56", None),
    ("($1,234.56)", ".", "-1234.56", None),
    ("1,234.56-", ".", "-1234.56", None),
    ("12.50 CR", ".", "12.50", "in"),
    ("12.50DR", ".", "12.50", "out"),
    ("USD 12.00", ".", "12.00", None),
    ("12.00 EUR", ".", "12.00", None),
    ("1.234,56", ",", "1234.56", None),
    ("-1.234,56 " + chr(0x20AC), ",", "-1234.56", None),
    ("1 234,56", ",", "1234.56", None),
    ("1'234.50", ".", "1234.50", None),
    (chr(0x2212) + "7.25", ".", "-7.25", None),
    (".75", ".", "0.75", None),
    ("12.500", ".", "12.50", None),
])
def test_parse_amount_styles(text, fmt, value, direction):
    parsed = parse_amount(text, NumberFormat(fmt))
    assert parsed is not None and parsed.value == Decimal(value) and parsed.direction == direction


@pytest.mark.parametrize("text", ["", "abc", "1.234", "12.3.4", "9" * 41, "1000000000000.00", "CR", "--5", "1\n2"])
def test_parse_amount_rejects(text):
    assert parse_amount(text) is None


def test_number_format_and_style_detection():
    assert amounts.detect_number_format(["1.234,56", "-12,50", "3,00 CR"]).decimal_separator == ","
    assert amounts.detect_number_format(["1,234.56", "-12.50", "1,234"]).decimal_separator == "."
    assert amounts.detect_number_format(["1,234", "1.234"]).decimal_separator == "."
    assert NumberFormat(",").thousands_separator == "."
    styles = amounts.detect_negative_styles(["-1.00", "(2.00)", "3.00-", "4.00 CR", "", "n/a"])
    assert styles == ("minus", "parentheses", "trailing_minus", "cr_dr")
    assert amounts.currency_symbols(["$1.00", chr(0x20AC) + "2", "3"]) == ("$", chr(0x20AC))
    assert amounts.looks_numeric("1.234,56") and not amounts.looks_numeric("Amount")


def test_date_parsing_and_detection():
    assert dates.parse_date("2026-01-05T13:45:00Z", "%Y-%m-%d") == date(2026, 1, 5)
    assert dates.parse_date("01/05/2026 1:45 PM", "%m/%d/%Y") == date(2026, 1, 5)
    assert dates.parse_date("1899-01-01", "%Y-%m-%d") is None
    assert dates.parse_date("", "%Y-%m-%d") is None
    assert dates.parse_date("x" * 50, "%Y-%m-%d") is None
    assert dates.date_format_label("%d.%m.%Y") == "DD.MM.YYYY" and dates.date_format_label("%j") is None
    assert dates.detect_date_formats(["", " "]).candidates == ()
    assert dates.detect_date_formats(["soon", "later"]).suggested is None
    same = dates.detect_date_formats(["01/01/2026", "02/02/2026"])
    assert not same.ambiguous and same.suggested == "%m/%d/%Y"
    textual = dates.detect_date_formats(["05 May 2026", "06 May 2026"])
    assert textual.suggested == "%d %b %Y"


# --------------------------------------------------------------------------- preview


BANK_CSV = (
    "Example Bank statement export\n"
    "Account ending 0000\n"
    "\n"
    "Date,Description,Amount,Balance\n"
    "2026-01-02,COFFEE SHOP,-4.50,995.50\n"
    "2026-01-03,PAYROLL DEPOSIT,\"2,000.00\",2995.50\n"
    "2026-01-04,\"GROCER, INC\",-55.10,2940.40\n"
    "2026-01-05,Mobile deposit,25.00,2965.40\n"
    "2026-01-06,Interest paid,0.40,2965.80\n"
    "2026-01-07,\"Multi\nline payee\",-9.99,2955.81\n"
)


def test_preview_bank_export_with_preamble_and_quotes():
    preview = preview_csv(BANK_CSV.encode())
    assert preview.encoding == "utf-8" and preview.delimiter == ","
    assert preview.header_row == 3 and preview.data_start == 4 and preview.row_count == 6
    assert [column.suggested_role for column in preview.columns] == ["date", "description", "amount", "ignored"]
    assert preview.date_range == (date(2026, 1, 2), date(2026, 1, 7))
    assert not preview.date_ambiguous and preview.date_formats[0].label == "YYYY-MM-DD"
    assert preview.sign is not None and preview.sign.convention == "inflows_positive" and preview.sign.basis == "keywords"
    assert preview.sign.confidence == "high"
    assert preview.negative_styles == ("minus",)
    assert preview.sample_rows[5][1] == "Multi\nline payee"
    suggested = preview.suggested_mapping
    assert suggested is not None and suggested.amount_strategy == "signed" and suggested.description_columns == (1,)
    result = parse_csv(BANK_CSV.encode(), suggested, account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal(v) for v in ("4.50", "-2000.00", "55.10", "-25.00", "-0.40", "9.99")]
    assert result.transactions[5].description == "Multi line payee"
    assert result.row_count == 6 and result.issue_count == 0


def test_preview_card_export_majority_sign():
    rows = "\n".join(f"2026-02-{day:02d},Store {day},{day}.00" for day in range(1, 10))
    inflows = "2026-02-10,Card refund,-3.00\n2026-02-11,Payment thank you,-100.00\n2026-02-12,Refund,-2.00\n"
    preview = preview_csv(f"Transaction Date,Payee,Amount\n{rows}\n{inflows}".encode())
    assert (preview.sign.convention, preview.sign.confidence, preview.sign.basis) == ("inflows_negative", "high", "keywords")
    noisy = "\n".join(f"2026-02-{day:02d},Store {day},{day}.00" for day in range(1, 8))
    preview = preview_csv(f"Date,Name,Amount\n{noisy}\n2026-02-09,Store,-1.00\n2026-02-10,Store,-2.00\n".encode())
    assert (preview.sign.convention, preview.sign.confidence, preview.sign.basis) == ("inflows_negative", "medium", "majority")


@pytest.mark.parametrize("values,expected", [
    (["-1", "-2", "3", "-4"], ("inflows_positive", "medium", "majority")),
    (["-1", "-2", "3", "4", "-5"], ("inflows_positive", "low", "majority")),
    (["1", "2", "-3", "4", "-5"], ("inflows_negative", "low", "majority")),
    (["1", "-2"], ("inflows_positive", "low", "default")),
])
def test_sign_suggestion_majority_levels(values, expected):
    parsed = [parse_amount(value) for value in values]
    suggestion = csv_parser._suggest_sign(["x"] * len(values), parsed)
    assert (suggestion.convention, suggestion.confidence, suggestion.basis) == expected


def test_sign_suggestion_without_signed_amounts_and_roles_without_text():
    assert csv_parser._suggest_sign([], []).basis == "default"
    preview = preview_csv(b"2026-01-01,-5.00\n2026-01-02,-6.00\n")
    assert [c.suggested_role for c in preview.columns] == ["date", "amount"]
    assert preview.suggested_mapping.description_columns == ()


def test_sign_suggestion_ignores_mixed_keywords_and_marked_amounts():
    parsed = [parse_amount(v) for v in ("1", "-1", "1", "-1", "5 CR")]
    suggestion = csv_parser._suggest_sign(["deposit"] * 5, parsed)
    assert suggestion.basis == "default"


def test_preview_ambiguous_dates_never_guess():
    data = b"Date,Description,Amount\n01/02/2026,A,-1.00\n03/04/2026,B,-2.00\n05/06/2026,C,-3.00\n"
    preview = preview_csv(data)
    assert preview.date_ambiguous
    assert [c.label for c in preview.date_formats] == ["MM/DD/YYYY", "DD/MM/YYYY"]
    assert preview.date_formats[0].date_to == date(2026, 5, 6) and preview.date_formats[1].date_to == date(2026, 6, 5)
    assert preview.date_range is None
    assert preview.suggested_mapping is not None and preview.suggested_mapping.date_format is None
    with pytest.raises(ImportFileError) as caught:
        parse_csv(data, preview.suggested_mapping, account_external_id=ACCOUNT)
    assert caught.value.code == "INVALID_MAPPING" and caught.value.details == {"field": "date_format"}
    us = parse_csv(data, replace(preview.suggested_mapping, date_format="%m/%d/%Y"), account_external_id=ACCOUNT)
    day_first = parse_csv(data, replace(preview.suggested_mapping, date_format="%d/%m/%Y"), account_external_id=ACCOUNT)
    assert us.transactions[0].transaction_date == date(2026, 1, 2)
    assert day_first.transactions[0].transaction_date == date(2026, 2, 1)


def test_preview_day_first_resolved_by_a_day_over_twelve():
    preview = preview_csv(b"Date,Description,Amount\n01/02/2026,A,-1.00\n25/02/2026,B,-2.00\n")
    assert not preview.date_ambiguous and preview.suggested_mapping.date_format == "%d/%m/%Y"


def test_preview_european_semicolon_file():
    data = (
        "Buchungstag;Verwendungszweck;Betrag;Waehrung\n"
        "02.01.2026;Supermarkt;-1.234,56;EUR\n"
        "15.01.2026;Gehalt;2.500,00;EUR\n"
        "20.01.2026;Miete;-800,00;EUR\n"
    ).encode("cp1252")
    preview = preview_csv(data)
    assert preview.delimiter == ";" and preview.number_format.decimal_separator == ","
    roles = [column.suggested_role for column in preview.columns]
    assert roles == ["date", "description", "amount", "ignored"]
    suggested = preview.suggested_mapping
    assert suggested.date_format == "%d.%m.%Y" and suggested.decimal_separator == ","
    result = parse_csv(data, replace(suggested, currency_column=3), account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("1234.56"), Decimal("-2500.00"), Decimal("800.00")]
    assert result.currencies == ("EUR",)


def test_preview_split_columns_without_header_names_known():
    data = (
        b"Posting Date,Transaction Date,Details,Memo,Withdrawals,Deposits,Category,Status,Currency\n"
        b"2026-03-02,2026-03-01,Utility Co,Ref 1,120.00,,Bills,Posted,usd\n"
        b"2026-03-03,2026-03-02,Employer,Ref 2,,3000.00,Income,Posted,USD\n"
        b"2026-03-04,2026-03-03,Diner,Ref 3,30.00,,Dining,Pending,USD\n"
        b"2026-03-05,2026-03-04,Diner,Ref 4,15.00,,Dining,Posted,USD\n"
    )
    preview = preview_csv(data)
    roles = [column.suggested_role for column in preview.columns]
    assert roles == ["posted_date", "date", "description", "memo", "debit", "credit", "category", "status", "currency"]
    assert preview.sign is None
    assert preview.category_values == (("Dining", 2), ("Bills", 1), ("Income", 1))
    suggested = preview.suggested_mapping
    assert suggested.amount_strategy == "split" and (suggested.debit_column, suggested.credit_column) == (4, 5)
    result = parse_csv(data, replace(suggested, description_columns=(2, 3)), account_external_id=ACCOUNT)
    first, second, third, _ = result.transactions
    assert first.amount == Decimal("120.00") and first.posted_date == date(2026, 3, 2)
    assert first.transaction_date == date(2026, 3, 1) and first.description == "Utility Co Ref 1"
    assert first.currency == "USD" and first.provider_category == "Bills"
    assert second.amount == Decimal("-3000.00") and third.status == "PENDING" and first.status == "POSTED"


def test_preview_indicator_strategy_suggested():
    data = (
        b"Date,Description,Amount,Type\n"
        b"2026-04-01,Payroll,1500.00,Credit\n"
        b"2026-04-02,Market,42.10,Debit\n"
        b"2026-04-03,Gym,30.00,DEBIT\n"
    )
    preview = preview_csv(data)
    suggested = preview.suggested_mapping
    assert suggested.amount_strategy == "indicator" and suggested.type_column == 3
    assert suggested.debit_values == ("debit",) and suggested.credit_values == ("credit",)
    result = parse_csv(data, suggested, account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("-1500.00"), Decimal("42.10"), Decimal("30.00")]


@pytest.mark.parametrize("header", ["Posting Date", "Posted", "Post Date"])
@pytest.mark.parametrize("cells,fmt,label", [
    (("09/15/2026", "09/20/2026", "09/25/2026"), "%m/%d/%Y", "MM/DD/YYYY"),
    (("15-Sep-2026", "20-Sep-2026", "25-Sep-2026"), "%d-%b-%Y", "DD-Mon-YYYY"),
])
def test_posted_date_is_the_transaction_date_when_the_file_has_no_other(header, cells, fmt, label):
    rows = "".join(f"{cell},Synthetic {i},\"-{i + 1}.00\"\n" for i, cell in enumerate(cells))
    data = f"{header},Memo,Amount\n{rows}".encode()
    preview = preview_csv(data)
    assert [c.suggested_role for c in preview.columns] == ["date", "memo", "amount"]
    assert [c.label for c in preview.date_formats] == [label] and not preview.date_ambiguous
    suggested = preview.suggested_mapping
    assert suggested is not None and (suggested.date_column, suggested.date_format) == (0, fmt)
    # The memo describes rows when no description column exists.
    assert suggested.posted_date_column is None and suggested.description_columns == (1,)
    result = parse_csv(data, suggested, account_external_id=ACCOUNT)
    assert [t.transaction_date for t in result.transactions] == [date(2026, 9, 15), date(2026, 9, 20), date(2026, 9, 25)]
    assert result.transactions[0].description == "Synthetic 0" and result.transactions[0].posted_date is None


def test_posted_date_stays_posted_beside_a_transaction_date():
    data = b"Posted,Date,Description,Amount\n2026-03-02,2026-03-01,A,-1.00\n2026-03-04,2026-03-03,B,-2.00\n"
    suggested = preview_csv(data).suggested_mapping
    assert (suggested.date_column, suggested.posted_date_column) == (1, 0)
    unnamed = b"Posted,When,Description,Amount\n2026-03-02,2026-03-01,A,-1.00\n2026-03-04,2026-03-03,B,-2.00\n"
    assert [c.suggested_role for c in preview_csv(unnamed).columns] == ["posted_date", "date", "description", "amount"]


def test_detect_mapped_dates_reads_the_chosen_column():
    data = b"Transaction Date,Posting Date,Description,Amount\n2026-03-01,03/14/2026,A,-1.00\n2026-03-02,03/15/2026,B,-2.00\n"
    suggested = preview_csv(data).suggested_mapping
    assert suggested.date_column == 0 and suggested.date_format == "%Y-%m-%d"
    moved = csv_parser.detect_mapped_dates(data, replace(suggested, date_column=1))
    assert [c.label for c in moved.candidates] == ["MM/DD/YYYY"] and moved.suggested == "%m/%d/%Y"
    assert csv_parser.detect_mapped_dates(data, replace(suggested, date_column=2)).candidates == ()
    assert csv_parser.detect_mapped_dates(data, replace(suggested, date_column=40)).candidates == ()
    assert csv_parser.detect_mapped_dates(data, replace(suggested, date_column=None)).candidates == ()  # type: ignore[arg-type]


def test_preview_infers_roles_from_content_without_header():
    data = b"2026-05-01,2026-05-02,Coffee house downtown,-4.00,12\n2026-05-03,2026-05-03,Book shop on main,-20.00,8\n"
    preview = preview_csv(data)
    assert preview.header_row is None and preview.data_start == 0
    assert [c.name for c in preview.columns][:2] == ["Column 1", "Column 2"]
    roles = [c.suggested_role for c in preview.columns]
    assert roles == ["date", "posted_date", "description", "amount", "ignored"]


def test_preview_third_date_column_and_missing_pieces():
    data = b"A,B,C,D\n2026-05-01,2026-05-02,2026-05-03,x\n2026-05-02,2026-05-03,2026-05-04,y\n"
    preview = preview_csv(data)
    assert [c.suggested_role for c in preview.columns] == ["date", "posted_date", "ignored", "description"]
    assert preview.suggested_mapping is None and preview.sign is None


def test_preview_refusals():
    with pytest.raises(ImportFileError) as caught:
        preview_csv(b"Date,Amount\n")
    assert caught.value.code == "NO_USABLE_ROWS"
    with pytest.raises(ImportFileError) as caught:
        preview_csv(b"one,\n" + b"\n" * 3)
    assert caught.value.code == "NO_USABLE_ROWS"
    wide = ",".join(f"c{i}" for i in range(csv_parser.MAX_COLUMNS + 1))
    with pytest.raises(ImportFileError) as caught:
        preview_csv((wide + "\n" + wide + "\n").encode())
    assert caught.value.code == "MALFORMED_CSV"


def test_choose_delimiter_requires_columns():
    with pytest.raises(ImportFileError) as caught:
        csv_parser._choose_delimiter("a\nb\n")
    assert caught.value.code == "MALFORMED_CSV"


def test_pipe_and_tab_delimiters():
    for delimiter in ("|", "\t"):
        data = delimiter.join(["Date", "Description", "Amount"]) + "\n" + delimiter.join(["2026-01-01", "A", "-1.00"]) + "\n"
        assert preview_csv(data.encode()).delimiter == delimiter


# --------------------------------------------------------------------------- parse


def test_signed_conventions():
    data = b"Date,Description,Amount\n2026-01-02,Shop,-10.00\n2026-01-03,Refund,4.00\n"
    bank = parse_csv(data, mapping(), account_external_id=ACCOUNT)
    card = parse_csv(data, mapping(sign_convention="inflows_negative"), account_external_id=ACCOUNT)
    assert amounts_of(bank) == [Decimal("10.00"), Decimal("-4.00")]
    assert amounts_of(card) == [Decimal("-10.00"), Decimal("4.00")]
    assert bank.transactions[0].account_external_id == ACCOUNT


def test_parentheses_and_cr_dr_marks_override_convention():
    data = b"Date,Description,Amount\n2026-01-02,Shop,(10.00)\n2026-01-03,Refund,4.00 CR\n2026-01-04,Fee,2.00 DR\n2026-01-05,X,3.00-\n"
    result = parse_csv(data, mapping(sign_convention="inflows_negative"), account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("-10.00"), Decimal("-4.00"), Decimal("2.00"), Decimal("-3.00")]


def test_split_strategy_edge_rows():
    data = (
        b"Date,Description,Debit,Credit\n"
        b"2026-01-02,Shop,-12.00,\n"          # sign inside a debit column is ignored
        b"2026-01-03,Pay,,500.00\n"
        b"2026-01-04,Both,1.00,2.00\n"
        b"2026-01-05,Neither,,\n"
        b"2026-01-06,Zeros,0.00,0.00\n"
        b"2026-01-07,Bad,abc,\n"
        b"2026-01-08,Marked,,5.00 DR\n"
        b"2026-01-09,Zero debit,0.00,7.00\n"
    )
    m = mapping(amount_strategy="split", amount_column=None, debit_column=2, credit_column=3)
    result = parse_csv(data, m, account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("12.00"), Decimal("-500.00"), Decimal("5.00"), Decimal("-7.00")]
    assert [(issue.row, issue.reason) for issue in result.issues] == [
        (4, "debit_and_credit"), (5, "missing_amount"), (6, "zero_amount"), (7, "invalid_amount"),
    ]


def test_indicator_strategy_rows():
    data = (
        b"Date,Description,Amount,Type\n"
        b"2026-01-02,Shop,12.00,D\n"
        b"2026-01-03,Pay,-500.00,C\n"
        b"2026-01-04,Odd,3.00,X\n"
        b"2026-01-05,Marked,4.00 CR,D\n"
    )
    m = mapping(amount_strategy="indicator", type_column=3, debit_values=("d",), credit_values=("C",))
    result = parse_csv(data, m, account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("12.00"), Decimal("-500.00"), Decimal("-4.00")]
    assert [(i.row, i.reason) for i in result.issues] == [(4, "unknown_type")]


def test_malformed_rows_become_issues_without_echoing_content():
    data = (
        b"Date,Description,Amount\n"
        b"2026-01-02,Shop,-1.00\n"
        b"not a date,Secret Payee,-2.00\n"
        b",Missing date,-3.00\n"
        b"2026-01-05,Missing amount,\n"
        b"2026-01-06,Bad amount,12abc\n"
        b"2026-01-07,Zero,0.00\n"
        b"2026-01-08,Extra,-1.00,surplus\n"
        b"2026-01-09,Short\n"
        b"2026-01-10,Fine,-1.50,\n"
        b"Total,,123.00\n"
    )
    result = parse_csv(data, mapping(), account_external_id=ACCOUNT)
    assert amounts_of(result) == [Decimal("1.00"), Decimal("1.50")]
    assert [(i.row, i.reason) for i in result.issues] == [
        (3, "invalid_date"), (4, "missing_date"), (5, "missing_amount"), (6, "invalid_amount"),
        (7, "zero_amount"), (8, "column_count"), (9, "missing_amount"), (11, "invalid_date"),
    ]
    assert result.issue_count == 8
    for issue in result.issues:
        assert "Secret" not in issue.reason


def test_file_without_usable_rows_is_an_error():
    with pytest.raises(ImportFileError) as caught:
        parse_csv(b"Date,Description,Amount\nbad,x,1\n", mapping(), account_external_id=ACCOUNT)
    assert caught.value.code == "NO_USABLE_ROWS" and caught.value.details == {"issue_count": 1}


def test_description_fallbacks_merchant_category_and_currency_defaults():
    data = b"Date,Description,Amount,Merchant,Category,Currency\n2026-01-02,,-1.00,Corner Store,Food,??\n2026-01-03,,-2.00,,Fees,\n2026-01-04,,-3.00,,,cad\n"
    m = mapping(merchant_column=3, category_column=4, currency_column=5, default_currency="USD")
    result = parse_csv(data, m, account_external_id=ACCOUNT)
    first, second, third = result.transactions
    assert first.description == "Corner Store" and first.merchant_name == "Corner Store" and first.currency == "USD"
    assert second.description == "Fees" and second.merchant_name is None
    assert third.description == "" and third.currency == "CAD"
    assert result.currencies == ("CAD", "USD")


def test_long_text_is_truncated_to_column_widths():
    data = f"Date,Description,Amount,Category\n2026-01-02,{'d' * 400},-1.00,{'c' * 150}\n".encode()
    result = parse_csv(data, mapping(category_column=3), account_external_id=ACCOUNT)
    assert len(result.transactions[0].description) == 255 and len(result.transactions[0].provider_category) == 100


def test_duplicate_rows_get_distinct_stable_keys_across_overlapping_files():
    january = (
        b"Date,Description,Amount\n"
        b"2026-01-30,Coffee,-3.00\n"
        b"2026-01-31,Coffee,-3.00\n"
        b"2026-01-31,coffee ,-3.00\n"
        b"2026-02-01,Rent,-900.00\n"
    )
    overlap = (
        b"Date,Description,Amount\n"
        b"2026-01-31,Coffee,-3.00\n"
        b"2026-01-31,Coffee,-3.00\n"
        b"2026-02-01,Rent,-900.00\n"
        b"2026-02-02,Book,-12.00\n"
    )
    first = parse_csv(january, mapping(), account_external_id=ACCOUNT)
    second = parse_csv(overlap, mapping(), account_external_id=ACCOUNT)
    again = parse_csv(january, mapping(), account_external_id=ACCOUNT)
    keys_first = [t.external_id for t in first.transactions]
    keys_second = [t.external_id for t in second.transactions]
    assert keys_first == [t.external_id for t in again.transactions]
    assert len(set(keys_first)) == 4 and first.duplicate_count == 1
    assert keys_first[1:4] == keys_second[0:3]
    assert keys_first[1] == row_key(date(2026, 1, 31), Decimal("3.00"), "COFFEE", 0)
    assert keys_first[2] == row_key(date(2026, 1, 31), Decimal("3.00"), "coffee", 1)


def test_pending_status_values():
    data = b"Date,Description,Amount,Status\n2026-01-02,A,-1.00,Pending\n2026-01-03,B,-1.00,AUTHORIZED\n2026-01-04,C,-1.00,Cleared\n2026-01-05,D,-1.00,\n"
    result = parse_csv(data, mapping(status_column=3), account_external_id=ACCOUNT)
    assert [t.status for t in result.transactions] == ["PENDING", "PENDING", "POSTED", "POSTED"]


def test_invalid_posted_date_is_dropped_not_fatal():
    data = b"Date,Description,Amount,Posted\n2026-01-02,A,-1.00,soon\n"
    result = parse_csv(data, mapping(posted_date_column=3), account_external_id=ACCOUNT)
    assert result.transactions[0].posted_date is None


def test_bom_utf16_and_cp1252_files_parse():
    text = "Date,Description,Amount\n2026-01-02,Caf" + chr(0xE9) + ",-3.00\n"
    for data in (b"\xef\xbb\xbf" + text.encode(), b"\xff\xfe" + text.encode("utf-16-le"), text.encode("cp1252")):
        result = parse_csv(data, mapping(), account_external_id=ACCOUNT)
        assert result.transactions[0].description == "Caf" + chr(0xE9)


def test_crlf_and_quoted_newlines():
    data = b'Date,Description,Amount\r\n2026-01-02,"Line one\r\nline two",-3.00\r\n'
    result = parse_csv(data, mapping(), account_external_id=ACCOUNT)
    assert result.transactions[0].description == "Line one line two"


def test_row_cap(monkeypatch):
    monkeypatch.setattr(csv_parser, "MAX_ROWS", 3)
    data = b"Date,Description,Amount\n" + b"2026-01-02,A,-1.00\n" * 4
    with pytest.raises(ImportFileError) as caught:
        parse_csv(data, mapping(), account_external_id=ACCOUNT)
    assert caught.value.code == "TOO_MANY_ROWS" and caught.value.details == {"max_rows": 3}
    monkeypatch.setattr(csv_parser, "MAX_ROWS", 0)
    with pytest.raises(ImportFileError) as caught:
        csv_parser._records("a,b\n" * 1002, ",")
    assert caught.value.code == "TOO_MANY_ROWS"


def test_issue_log_caps_kept_issues():
    log = IssueLog()
    for row in range(MAX_ISSUES + 5):
        log.add(row, "invalid_date")
    assert log.count == MAX_ISSUES + 5 and len(log.issues) == MAX_ISSUES


def test_unreadable_csv_is_malformed():
    previous = csv_module.field_size_limit(10)
    try:
        with pytest.raises(ImportFileError) as caught:
            csv_parser._records("a,bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n", ",")
    finally:
        csv_module.field_size_limit(previous)
    assert caught.value.code == "MALFORMED_CSV"


# --------------------------------------------------------------------------- mapping validation


@pytest.mark.parametrize("overrides,field_name", [
    ({"delimiter": ":"}, "delimiter"),
    ({"date_format": "%j"}, "date_format"),
    ({"data_start": -1}, "data_start"),
    ({"data_start": True}, "data_start"),
    ({"decimal_separator": "_"}, "decimal_separator"),
    ({"amount_strategy": "guess"}, "amount_strategy"),
    ({"sign_convention": "sideways"}, "sign_convention"),
    ({"amount_column": None}, "amount_column"),
    ({"amount_strategy": "split", "debit_column": 2}, "credit_column"),
    ({"amount_strategy": "indicator", "type_column": 1}, "debit_values"),
    ({"amount_strategy": "indicator", "debit_values": ("d",)}, "type_column"),
    ({"amount_strategy": "indicator", "type_column": 1, "debit_values": (1,)}, "debit_values"),
    ({"description_columns": ()}, "description_columns"),
    ({"description_columns": (9,)}, "description_columns[0]"),
    ({"category_column": 3}, "category_column"),
    ({"default_currency": "usd"}, "default_currency"),
])
def test_invalid_mappings(overrides, field_name):
    data = b"Date,Description,Amount\n2026-01-02,A,-1.00\n"
    with pytest.raises(ImportFileError) as caught:
        parse_csv(data, mapping(**overrides), account_external_id=ACCOUNT)
    assert caught.value.code == "INVALID_MAPPING" and caught.value.details == {"field": field_name}


def test_mapping_round_trips_through_json():
    m = mapping(amount_strategy="indicator", type_column=1, debit_values=("d",), credit_values=("c",), description_columns=(1, 2))
    data = m.to_dict()
    assert data["description_columns"] == [1, 2] and data["debit_values"] == ["d"]
    assert CsvMapping.from_dict(data) == m


@pytest.mark.parametrize("data,code_detail", [
    ({"delimiter": ",", "surprise": 1}, {"fields": ["surprise"]}),
    ({"delimiter": ","}, {}),
    ({**mapping().to_dict(), "description_columns": 5}, {}),
])
def test_mapping_from_dict_refusals(data, code_detail):
    with pytest.raises(ImportFileError) as caught:
        CsvMapping.from_dict(data)
    assert caught.value.code == "INVALID_MAPPING" and caught.value.details == code_detail


def test_decoding_constants_documented():
    assert decoding.MAX_ROWS == 50_000 and decoding.MAX_FILE_BYTES == 10 * 1024 * 1024
