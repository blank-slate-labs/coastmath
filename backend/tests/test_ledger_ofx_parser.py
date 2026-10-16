"""OFX/QFX importer: SGML and XML statements, corrections, dates and hostile input.

Every fixture is synthetic and built here; account numbers are placeholders.
"""
from datetime import UTC, date, datetime, time, timedelta, timezone
from decimal import Decimal

import pytest

from app.ledger.importers import (
    ImportFileError,
    decoding,
    ofx_parser,
    parse_ofx,
    parse_ofx_datetime,
    row_key,
)

SGML_HEADER = (
    "OFXHEADER:100\nDATA:OFXSGML\nVERSION:102\nSECURITY:NONE\nENCODING:USASCII\nCHARSET:1252\n"
    "COMPRESSION:NONE\nOLDFILEUID:NONE\nNEWFILEUID:NONE\n\n"
)
SIGNON = (
    "<SIGNONMSGSRSV1><SONRS><STATUS><CODE>0<SEVERITY>INFO</STATUS><DTSERVER>20260201120000"
    "<LANGUAGE>ENG<FI><ORG>Example Credit Union<FID>9999</FI><INTU.BID>00000</SONRS></SIGNONMSGSRSV1>"
)


def trn(fitid: str | None, amount: str, posted: str = "20260105", **extra: str) -> str:
    parts = ["<STMTTRN>", f"<TRNTYPE>{extra.pop('trntype', 'DEBIT')}", f"<DTPOSTED>{posted}", f"<TRNAMT>{amount}"]
    if fitid is not None:
        parts.append(f"<FITID>{fitid}")
    parts += [f"<{key.upper()}>{value}" for key, value in extra.items()]
    return "".join(parts) + "</STMTTRN>\n"


def bank(transactions: str, *, acct: str = "000012345678", acct_type: str = "CHECKING", start: str = "20260101",
         end: str = "20260131", balance: str = "1000.00", currency: str = "USD") -> str:
    return (
        "<STMTTRNRS><TRNUID>1<STATUS><CODE>0<SEVERITY>INFO</STATUS><STMTRS>"
        f"<CURDEF>{currency}<BANKACCTFROM><BANKID>000000000<ACCTID>{acct}<ACCTTYPE>{acct_type}</BANKACCTFROM>"
        f"<BANKTRANLIST><DTSTART>{start}<DTEND>{end}\n{transactions}</BANKTRANLIST>"
        f"<LEDGERBAL><BALAMT>{balance}<DTASOF>20260131170000[-5:EST]</LEDGERBAL></STMTRS></STMTTRNRS>"
    )


def card(transactions: str, *, acct: str = "4000000000001111", balance: str = "-250.75") -> str:
    return (
        "<CCSTMTTRNRS><TRNUID>2<STATUS><CODE>0<SEVERITY>INFO</STATUS><CCSTMTRS><CURDEF>USD"
        f"<CCACCTFROM><ACCTID>{acct}</CCACCTFROM>"
        f"<BANKTRANLIST><DTSTART>20260101<DTEND>20260201000000.000[-5:EST]\n{transactions}</BANKTRANLIST>"
        f"<LEDGERBAL><BALAMT>{balance}<DTASOF>20260131</LEDGERBAL></CCSTMTRS></CCSTMTTRNRS>"
    )


def sgml(*, banks: str = "", cards: str = "", investments: str = "") -> bytes:
    body = "<OFX>" + SIGNON
    if banks:
        body += f"<BANKMSGSRSV1>{banks}</BANKMSGSRSV1>"
    if cards:
        body += f"<CREDITCARDMSGSRSV1>{cards}</CREDITCARDMSGSRSV1>"
    if investments:
        body += f"<INVSTMTMSGSRSV1>{investments}</INVSTMTMSGSRSV1>"
    return (SGML_HEADER + body + "</OFX>").encode()


XML_FILE = """<?xml version="1.0" encoding="UTF-8" standalone="no"?>
<?OFX OFXHEADER="200" VERSION="220" SECURITY="NONE" OLDFILEUID="NONE" NEWFILEUID="NONE"?>
<OFX>
  <SIGNONMSGSRSV1><SONRS><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
    <DTSERVER>20260201</DTSERVER><LANGUAGE>ENG</LANGUAGE></SONRS></SIGNONMSGSRSV1>
  <BANKMSGSRSV1><STMTTRNRS><TRNUID>1</TRNUID><STATUS><CODE>0</CODE><SEVERITY>INFO</SEVERITY></STATUS>
    <STMTRS><CURDEF>CAD</CURDEF>
      <BANKACCTFROM><BANKID>000000000</BANKID><ACCTID>00009876</ACCTID><ACCTTYPE>SAVINGS</ACCTTYPE></BANKACCTFROM>
      <BANKTRANLIST><DTSTART>20260101000000[+1:CET]</DTSTART><DTEND>20260131235959[+1:CET]</DTEND>
        <STMTTRN><TRNTYPE>INT</TRNTYPE><DTPOSTED>20260131</DTPOSTED><TRNAMT>1.25</TRNAMT>
          <FITID>X1</FITID><NAME>Interest &amp; bonus &#x41;&#66;</NAME><MEMO></MEMO></STMTTRN>
        <!-- <STMTTRN><FITID>COMMENTED</FITID></STMTTRN> -->
        <STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260115</DTPOSTED><DTUSER>20260114</DTUSER>
          <TRNAMT>-20.00</TRNAMT><FITID>X2</FITID><PAYEE><NAME>Hardware store</NAME><ADDR1>1 Main</ADDR1></PAYEE>
          <CURRENCY><CURRATE>0.74</CURRATE><CURSYM>usd</CURSYM></CURRENCY></STMTTRN>
      </BANKTRANLIST>
      <LEDGERBAL><BALAMT>5000.00</BALAMT><DTASOF>20260131</DTASOF></LEDGERBAL>
    </STMTRS></STMTTRNRS></BANKMSGSRSV1>
</OFX>
"""


def only(result):
    assert len(result.statements) == 1
    return result.statements[0]


def test_sgml_bank_statement():
    data = sgml(banks=bank(
        trn("T1", "-4.50", "20260105120000[-5:EST]", name="COFFEE SHOP", memo="CARD PURCHASE")
        + trn("T2", "2000.00", "20260110", trntype="DIRECTDEP", name="EMPLOYER PAYROLL")
        + trn("T3", "-100.00", "20260112", trntype="CHECK", checknum="1001")
        + trn("T4", "-5", "20260113", name="Fee", checknum="77", memo="Fee"),
    ))
    result = parse_ofx(data)
    assert result.encoding == "utf-8" and result.unsupported_statement_count == 0
    statement = only(result)
    account = statement.account
    assert statement.kind == "bank"
    assert (account.account_type, account.subtype, account.mask, account.currency) == ("DEPOSITORY", "CHECKING", "5678", "USD")
    assert account.name == "Checking " + chr(0xB7) * 2 + "5678" and account.institution_name == "Example Credit Union"
    assert account.external_id.startswith("ofx-") and "12345678" not in account.external_id
    assert account.balance == Decimal("1000.00")
    assert account.balance_date == datetime(2026, 1, 31, 17, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert (statement.period_start, statement.period_end) == (date(2026, 1, 1), date(2026, 1, 31))
    first, second, third, fourth = statement.transactions
    assert first.external_id == "T1" and first.amount == Decimal("4.50") and first.transaction_date == date(2026, 1, 5)
    assert first.description == "COFFEE SHOP CARD PURCHASE" and first.merchant_name == "COFFEE SHOP"
    assert first.account_external_id == account.external_id and first.currency == "USD" and first.status == "POSTED"
    assert second.amount == Decimal("-2000.00")
    assert third.description == "Check 1001" and third.merchant_name is None
    assert fourth.description == "Check 77 Fee" and fourth.amount == Decimal("5.00")
    assert statement.transaction_types == {"T1": "DEBIT", "T2": "DIRECTDEP", "T3": "CHECK", "T4": "DEBIT"}
    assert statement.issue_count == 0 and statement.derived_id_count == 0


def test_xml_statement_with_entities_payee_comments_and_foreign_currency():
    statement = only(parse_ofx(XML_FILE.encode()))
    account = statement.account
    assert (account.subtype, account.currency, account.balance, account.institution_name) == ("SAVINGS", "CAD", Decimal("5000.00"), None)
    assert account.balance_date == datetime(2026, 1, 31, tzinfo=UTC)
    assert (statement.period_start, statement.period_end) == (date(2026, 1, 1), date(2026, 1, 31))
    interest, hardware = statement.transactions
    assert interest.description == "Interest & bonus AB" and interest.amount == Decimal("-1.25")
    assert hardware.merchant_name == "Hardware store" and hardware.currency == "USD"
    assert hardware.transaction_date == date(2026, 1, 14) and hardware.posted_date == date(2026, 1, 15)
    assert "COMMENTED" not in statement.transaction_types


def test_qfx_with_multiple_accounts_and_credit_card_signs():
    data = sgml(
        banks=bank(trn("B1", "-10.00", name="Shop")) + bank(trn("S1", "5.00", name="Interest"), acct="000099990000", acct_type="MONEYMRKT"),
        cards=card(trn("C1", "-42.00", trntype="DEBIT", name="Restaurant") + trn("C2", "300.00", trntype="CREDIT", name="Payment")),
    )
    result = parse_ofx(data)
    checking, money_market, credit = result.statements
    assert money_market.account.subtype == "MONEY_MARKET" and money_market.account.mask == "0000"
    assert checking.account.external_id != money_market.account.external_id
    assert credit.kind == "credit_card"
    assert (credit.account.account_type, credit.account.subtype, credit.account.mask) == ("CREDIT", "CREDIT_CARD", "1111")
    assert credit.account.balance == Decimal("250.75")  # amount owed
    assert [t.amount for t in credit.transactions] == [Decimal("42.00"), Decimal("-300.00")]
    assert credit.period_end == date(2026, 1, 31)  # midnight DTEND is exclusive


@pytest.mark.parametrize("acct_type,expected", [
    ("SAVINGS", ("DEPOSITORY", "SAVINGS")),
    ("CD", ("DEPOSITORY", "CD")),
    ("CREDITLINE", ("CREDIT", "LINE_OF_CREDIT")),
    ("WHATEVER", ("OTHER", None)),
])
def test_bank_account_type_mapping(acct_type, expected):
    statement = only(parse_ofx(sgml(banks=bank("", acct_type=acct_type, balance="-75.00"))))
    assert (statement.account.account_type, statement.account.subtype) == expected
    owed = expected[0] == "CREDIT"
    assert statement.account.balance == (Decimal("75.00") if owed else Decimal("-75.00"))
    if expected[1] is None:
        assert statement.account.name.startswith("Account ")


def test_empty_statement_is_returned_for_its_coverage():
    statement = only(parse_ofx(sgml(banks=bank(""))))
    assert statement.transactions == () and statement.period_end == date(2026, 1, 31)


@pytest.mark.parametrize("start,end,expected", [
    ("20260101", "20260131", (date(2026, 1, 1), date(2026, 1, 31))),
    ("20260101", "20260201000000", (date(2026, 1, 1), date(2026, 1, 31))),
    ("20260101", "20260201000000.000[0:GMT]", (date(2026, 1, 1), date(2026, 1, 31))),
    ("20260101", "20260131120000[-8:PST]", (date(2026, 1, 1), date(2026, 1, 31))),
    ("20260101120000", "20260101000000", (date(2026, 1, 1), date(2026, 1, 1))),
    ("", "", (None, None)),
    ("garbage", "20260131", (None, date(2026, 1, 31))),
])
def test_period_rules(start, end, expected):
    statement = only(parse_ofx(sgml(banks=bank("", start=start, end=end))))
    assert (statement.period_start, statement.period_end) == expected


def test_corrections_replace_and_delete_in_either_order():
    transactions = (
        trn("C-REP", "-12.00", name="Corrected", correctfitid="ORIG1", correctaction="REPLACE")
        + trn("ORIG1", "-21.00", name="Wrong amount")
        + trn("ORIG2", "-5.00", name="Duplicate charge")
        + trn("C-DEL", "-5.00", correctfitid="ORIG2", correctaction="DELETE")
        + trn("C-OLD", "-1.00", correctfitid="FROM-EARLIER-FILE", correctaction="DELETE")
        + trn("C-BAD", "-1.00", correctfitid="ORIG3", correctaction="MERGE")
        + trn("KEEP", "-3.00", name="Kept")
    )
    statement = only(parse_ofx(sgml(banks=bank(transactions))))
    assert [t.external_id for t in statement.transactions] == ["C-REP", "KEEP"]
    assert statement.transactions[0].amount == Decimal("12.00")
    assert statement.removed_external_ids == ("ORIG1", "ORIG2", "FROM-EARLIER-FILE")
    assert [(i.row, i.reason) for i in statement.issues] == [(6, "invalid_correction")]


def test_row_issues_and_derived_ids():
    transactions = (
        trn("A", "-1.00", "notadate")
        + "<STMTTRN><TRNTYPE>DEBIT<TRNAMT>-1.00<FITID>B</STMTTRN>\n"
        + trn("C", "abc")
        + "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260105<FITID>D</STMTTRN>\n"
        + trn("E", "0.00")
        + trn("F", "-1,000.00")
        + trn("G", "-2.00 CR")
        + trn("H", "-7.00", name="Same")
        + trn("H", "-8.00", name="Again")
        + trn(None, "-9.99", name="No id")
        + trn(None, "-9.99", name="No id")
        + "<STMTTRN><DTPOSTED>20260106<TRNAMT>-1,50<FITID>I</STMTTRN>\n"
    )
    statement = only(parse_ofx(sgml(banks=bank(transactions))))
    assert [(i.row, i.reason) for i in statement.issues] == [
        (1, "invalid_date"), (2, "missing_date"), (3, "invalid_amount"), (4, "missing_amount"),
        (5, "zero_amount"), (6, "invalid_amount"), (7, "invalid_amount"), (9, "duplicate_fitid"),
    ]
    kept = statement.transactions
    assert [t.external_id for t in kept][:1] == ["H"] and kept[0].amount == Decimal("7.00")
    derived = [t.external_id for t in kept[1:3]]
    assert derived == [
        row_key(date(2026, 1, 5), Decimal("9.99"), "No id", 0),
        row_key(date(2026, 1, 5), Decimal("9.99"), "No id", 1),
    ]
    assert statement.derived_id_count == 2
    assert kept[3].amount == Decimal("1.50") and statement.transaction_types["I"] == "OTHER"


def test_missing_optional_fields():
    data = (
        b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKACCTFROM><ACCTID>12</BANKACCTFROM>"
        b"<BANKTRANLIST><STMTTRN><DTPOSTED>20260105<TRNAMT>-1<FITID>Z</STMTTRN></BANKTRANLIST>"
        b"</STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
    )
    statement = only(parse_ofx(data))
    account = statement.account
    assert (account.account_type, account.currency, account.balance, account.balance_date, account.mask) == ("OTHER", None, None, None, "12")
    assert statement.transactions[0].description == "" and statement.transactions[0].currency is None
    assert (statement.period_start, statement.period_end) == (None, None)
    assert account.institution_name is None


def test_no_transaction_list_and_masked_ids():
    data = b"<OFX><CREDITCARDMSGSRSV1><CCSTMTTRNRS><CCSTMTRS><CCACCTFROM><ACCTID>--</CCACCTFROM></CCSTMTRS></CCSTMTTRNRS></CREDITCARDMSGSRSV1></OFX>"
    statement = only(parse_ofx(data))
    assert statement.transactions == () and statement.account.mask is None and statement.account.name == "Credit card"


def test_empty_sgml_leaf_does_not_swallow_siblings():
    data = sgml(banks=bank("<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260105<TRNAMT>-3.00<FITID>E1<MEMO><NAME>After empty memo</STMTTRN>"))
    transaction = only(parse_ofx(data)).transactions[0]
    assert transaction.description == "After empty memo"


def test_payee_used_as_leaf_text():
    data = sgml(banks=bank("<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260105<TRNAMT>-3.00<FITID>P1<PAYEE>Leaf payee\n</STMTTRN>"))
    assert only(parse_ofx(data)).transactions[0].merchant_name == "Leaf payee"


def test_investment_only_file_is_unsupported_and_mixed_file_counts_it():
    investments = "<INVSTMTTRNRS><INVSTMTRS><CURDEF>USD<INVACCTFROM><BROKERID>x<ACCTID>1</INVACCTFROM></INVSTMTRS></INVSTMTTRNRS>"
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(sgml(investments=investments))
    assert caught.value.code == "UNSUPPORTED_STATEMENT"
    mixed = parse_ofx(sgml(banks=bank(""), investments=investments))
    assert mixed.unsupported_statement_count == 1 and len(mixed.statements) == 1


@pytest.mark.parametrize("data,code", [
    (b"Date,Amount\n2026-01-01,1\n", "UNSUPPORTED_FORMAT"),
    (b"OFXHEADER:100\nDATA:OFXSGML\n\nno body here", "MALFORMED_OFX"),
    (b"<OFX><SIGNONMSGSRSV1></SIGNONMSGSRSV1></OFX>", "NO_STATEMENTS"),
    (b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKACCTFROM><BANKID>1</BANKACCTFROM></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>", "MALFORMED_OFX"),
])
def test_file_level_refusals(data, code):
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(data)
    assert caught.value.code == code


def test_hostile_entity_declarations_are_not_expanded():
    data = (
        b'<?xml version="1.0"?>\n<!DOCTYPE OFX [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;">]>\n'
        b'<?OFX OFXHEADER="200"?>'
        b"<OFX><BANKMSGSRSV1><STMTTRNRS><STMTRS><BANKACCTFROM><ACCTID>1234</ACCTID></BANKACCTFROM><BANKTRANLIST>"
        b"<STMTTRN><TRNTYPE>DEBIT</TRNTYPE><DTPOSTED>20260105</DTPOSTED><TRNAMT>-1.00</TRNAMT><FITID>E</FITID>"
        b"<NAME>&lol2; &#0; &#xD800; &#1114112;</NAME></STMTTRN>"
        b"</BANKTRANLIST></STMTRS></STMTTRNRS></BANKMSGSRSV1></OFX>"
    )
    transaction = only(parse_ofx(data)).transactions[0]
    assert transaction.description == "&lol2;"


def test_declarations_and_processing_instructions_inside_the_body_are_skipped():
    data = sgml(banks=bank("<?INTU.PI x?><!SOMETHING>" + trn("PI", "-1.00", name="After PI")))
    assert only(parse_ofx(data)).transactions[0].description == "After PI"


def test_huge_and_unterminated_tags():
    huge_value = "x" * 100_000
    junk_tag = "<" + "A" * 5000 + ">"
    data = sgml(banks=bank(
        trn("H1", "-1.00", name=huge_value)
        + junk_tag + "<<<<<" + "<STMTTRN><TRNTYPE>DEBIT<DTPOSTED>20260106<TRNAMT>-2.00<FITID>H2</STMTTRN>"
        + "<!-- unterminated comment",
    ))
    statement = only(parse_ofx(data))
    assert [t.external_id for t in statement.transactions] == ["H1", "H2"]
    assert len(statement.transactions[0].description) == ofx_parser.DESCRIPTION_LENGTH
    unterminated = sgml(banks=bank(trn("U1", "-1.00"))).replace(b"</OFX>", b"<STMTTRN")
    assert [t.external_id for t in only(parse_ofx(unterminated)).transactions] == ["U1"]
    tail_text = sgml(banks=bank(trn("U2", "-1.00"))) + b" trailing text"
    assert only(parse_ofx(tail_text)).transactions[0].external_id == "U2"


def test_deep_nesting_is_refused():
    data = ("<OFX>" + "<AGG>" * (ofx_parser.MAX_DEPTH + 2) + "</OFX>").encode()
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(data)
    assert caught.value.code == "MALFORMED_OFX" and caught.value.details == {"max_depth": ofx_parser.MAX_DEPTH}


def test_trailing_unknown_open_tag_is_settled():
    data = sgml(banks=bank(trn("T", "-1.00"))).replace(b"</OFX>", b"<TRAILER>")
    assert only(parse_ofx(data)).transactions[0].external_id == "T"


def test_transaction_caps(monkeypatch):
    monkeypatch.setattr(ofx_parser, "MAX_ROWS", 2)
    many = trn("A", "-1.00") + trn("B", "-1.00") + trn("C", "-1.00")
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(sgml(banks=bank(many)))
    assert caught.value.code == "TOO_MANY_ROWS"
    two_files = sgml(banks=bank(trn("A", "-1.00") + trn("B", "-1.00")) + bank(trn("C", "-1.00"), acct="9"))
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(two_files)
    assert caught.value.code == "TOO_MANY_ROWS" and caught.value.details == {"max_rows": 2}


def test_windows_1252_ofx():
    data = sgml(banks=bank(trn("W", "-1.00", name="Caf\xe9"))).replace(b"Caf\xc3\xa9", b"Caf\xe9")
    result = parse_ofx(data)
    assert result.encoding == "windows-1252" and result.statements[0].transactions[0].description == "Caf" + chr(0xE9)


@pytest.mark.parametrize("text,expected_date,expected_time,offset", [
    ("20260105", date(2026, 1, 5), None, None),
    ("202601051230", date(2026, 1, 5), time(12, 30), None),
    ("20260105123045.123", date(2026, 1, 5), time(12, 30, 45, 123000), None),
    ("20260105233000[-5:EST]", date(2026, 1, 5), time(23, 30), timedelta(hours=-5)),
    ("20260105000000[+5:30:IST]", date(2026, 1, 5), time(0), timedelta(hours=5, minutes=30)),
    ("20260105000000[-3.5:NST]", date(2026, 1, 5), time(0), timedelta(hours=-3, minutes=-30)),
    ("20260105000000[0]", date(2026, 1, 5), time(0), timedelta(0)),
    ("20260105000000[+9]", date(2026, 1, 5), time(0), timedelta(hours=9)),
])
def test_ofx_datetimes_keep_their_calendar_date(text, expected_date, expected_time, offset):
    stamp = parse_ofx_datetime(text)
    assert stamp is not None
    assert (stamp.date, stamp.time, stamp.offset) == (expected_date, expected_time, offset)


@pytest.mark.parametrize("text", [None, "", "2026", "20261301", "20260105250000", "20260105000000[+15:X]", "20260105000000[+5:75:X]"])
def test_invalid_ofx_datetimes(text):
    assert parse_ofx_datetime(text) is None


def test_midnight_and_as_datetime():
    stamp = parse_ofx_datetime("20260201000000[-5:EST]")
    assert stamp.is_midnight and stamp.as_datetime() == datetime(2026, 2, 1, tzinfo=timezone(timedelta(hours=-5)))
    assert not parse_ofx_datetime("20260201").is_midnight


def test_size_cap_applies_to_ofx():
    with pytest.raises(ImportFileError) as caught:
        parse_ofx(b"<OFX>" + b" " * decoding.MAX_FILE_BYTES)
    assert caught.value.code == "FILE_TOO_LARGE"
