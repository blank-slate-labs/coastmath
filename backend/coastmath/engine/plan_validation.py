"""Shared financial input constraints for persisted, stateless and engine callers."""

from coastmath.engine.account_types import ROTH_TYPES, TRADITIONAL_RETIREMENT_TYPES

CASH_TRANSFER_SOURCES = frozenset({'checking', 'savings'})
CASH_TRANSFER_TARGETS = CASH_TRANSFER_SOURCES | {'taxable_brokerage'}
#: Brokerage-like holdings whose sale realizes gain against tracked basis.
SALE_TRANSFER_SOURCES = frozenset({'taxable_brokerage', 'cryptocurrency'})
_CONTRIBUTION_MESSAGE = (
    'Transfers support checking, savings or brokerage sales and retirement distributions '
    'into cash or brokerage accounts, and same-owner rollovers between traditional retirement accounts. '
)


def transfer_error(
    source_type: str | None,
    target_type: str | None,
    same_account: bool = False,
    *,
    source_owner: str | None = None,
    target_owner: str | None = None,
    source_inherited: bool = False,
    target_inherited: bool = False,
) -> str | None:
    """Why a transfer between two accounts is not allowed, or None.

    Moving money out of a brokerage or retirement account is a sale or a
    distribution and is taxed as one. Moving it between two traditional
    retirement accounts of one owner is a rollover and is tax-neutral. Money
    never enters a contribution-limited account through a transfer: that is a
    contribution and uses a contribution allocation rule so annual limits apply.
    """
    if same_account or source_type is None or target_type is None:
        return 'Transfers require two different accounts in this plan.'
    if target_type in CASH_TRANSFER_TARGETS and (
            source_type in CASH_TRANSFER_SOURCES or source_type in SALE_TRANSFER_SOURCES
            or source_type in TRADITIONAL_RETIREMENT_TYPES or source_type in ROTH_TYPES):
        return None
    if source_type in TRADITIONAL_RETIREMENT_TYPES and target_type in TRADITIONAL_RETIREMENT_TYPES:
        if source_inherited or target_inherited:
            return ('Transfers support same-owner rollovers of the owner\'s own accounts; '
                    'an inherited account cannot be rolled over.')
        if source_owner != target_owner:
            return 'Transfers support rollovers only between accounts of the same owner.'
        return None
    if source_type in TRADITIONAL_RETIREMENT_TYPES and target_type in ROTH_TYPES:
        return ('Transfers cannot move a traditional account into a Roth account. '
                'Use a Roth conversion, which is taxed as a conversion.')
    if source_type in ROTH_TYPES and target_type in ROTH_TYPES | TRADITIONAL_RETIREMENT_TYPES:
        return ('Transfers support distributions from a Roth account into cash or brokerage accounts only; '
                'Roth-to-Roth rollovers and Roth-to-traditional moves are not modeled.')
    if target_type in TRADITIONAL_RETIREMENT_TYPES | ROTH_TYPES | {'hsa', 'five_twenty_nine'}:
        return ('Transfers cannot fund a retirement, HSA or education account from cash or brokerage: '
                'that is a contribution, so use an allocation rule that applies the annual limits.')
    return _CONTRIBUTION_MESSAGE + 'Use a withdrawal for HSA or education account spending.'


def validate_transfer_rules(priorities, accounts) -> None:
    for priority in priorities:
        if priority.priority_type != 'transfer':
            continue
        source = accounts.get(priority.source_account_id)
        target = accounts.get(priority.target_account_id)
        error = transfer_error(
            source.account_type if source else None, target.account_type if target else None,
            priority.source_account_id == priority.target_account_id,
            source_owner=getattr(source, 'owner', None), target_owner=getattr(target, 'owner', None),
            source_inherited=getattr(source, 'inherited_year', None) is not None,
            target_inherited=getattr(target, 'inherited_year', None) is not None,
        )
        if error:
            raise ValueError(f'Allocation rule {priority.priority_rank}: {error}')


def conversion_error(source, target) -> str | None:
    if (source is None or target is None
            or source.account_type not in TRADITIONAL_RETIREMENT_TYPES
            or target.account_type not in ROTH_TYPES
            or source.owner != target.owner):
        return 'Roth conversions require a traditional retirement source and a Roth destination for the same owner.'
    return None


def validate_roth_conversion_rules(priorities, accounts) -> None:
    for priority in priorities:
        if priority.priority_type == 'roth_conversion':
            error = conversion_error(accounts.get(priority.source_account_id), accounts.get(priority.target_account_id))
            if error:
                raise ValueError(f'Allocation rule {priority.priority_rank}: {error}')


def validate_account_history(accounts, start_year):
    """Opening tax history must precede the projection, not create future basis."""
    for aid, account in accounts.items():
        roth = getattr(account, 'roth_settings', None)
        if hasattr(roth, 'model_dump'):
            roth = roth.model_dump()
        if roth:
            first = roth.get('first_contribution_year')
            if (first is not None and first > start_year) or any(c['year'] > start_year for c in roth.get('conversions', [])):
                raise ValueError(f'{account.name or aid}: Roth opening history cannot include future contribution or conversion years; use an allocation rule for future funding.')
        inheritance = getattr(account, 'inheritance_settings', None)
        if hasattr(inheritance, 'model_dump'):
            inheritance = inheritance.model_dump()
        if inheritance and inheritance.get('beneficiary_is_minor_child') and account.beneficiary_type != 'edb':
            raise ValueError(f'{account.name or aid}: the minor-child rule requires an eligible designated beneficiary.')
