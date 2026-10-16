import { moneyLabel } from "@/utils/format";
import { useState } from "react";
import type {
  RealAsset,
  RealAssetCreate,
  Account,
  AssetTaxTreatment,
  RentalPropertyClass,
} from "@/types/plan";
import MoneyInput from "@/components/money_input";

// Stored rates are decimals; the form edits percentages.
const pct = (value: number | null | undefined) =>
  value == null ? "" : String(Number((value * 100).toFixed(6)));
const text = (value: number | null | undefined) => (value == null ? "" : String(value));
const num = (value: string) => (value === "" ? null : Number(value));
const rate = (value: string) => (value === "" ? null : Number(value) / 100);

function MonthSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label>
      {label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {Array.from({ length: 12 }, (_, i) => (
          <option key={i} value={i + 1}>
            {i + 1}
          </option>
        ))}
      </select>
    </label>
  );
}

interface RealAssetFormProps {
  initial?: RealAsset;
  accounts: Account[];
  onSubmit: (data: RealAssetCreate) => void;
  onCancel: () => void;
}

export default function RealAssetForm({
  initial,
  accounts,
  onSubmit,
  onCancel,
}: RealAssetFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [currentValue, setCurrentValue] = useState(initial?.current_value?.toString() ?? "0");
  const [adjustedBasis, setAdjustedBasis] = useState(initial?.adjusted_basis?.toString() ?? "");
  const [saleYear, setSaleYear] = useState(initial?.sale_year?.toString() ?? "");
  const [saleMonth, setSaleMonth] = useState(initial?.sale_month ?? 1);
  const [annualAppreciationRate, setAnnualAppreciationRate] = useState(
    initial ? String(initial.annual_appreciation_rate * 100) : "3",
  );
  const [isPrimaryResidence, setIsPrimaryResidence] = useState(
    initial?.is_primary_residence ?? false,
  );
  const [taxTreatment, setTaxTreatment] = useState<AssetTaxTreatment>(
    initial ? (initial.tax_treatment ?? "unspecified") : "personal_use",
  );
  const [autoLiquidateOnDepletion, setAutoLiquidateOnDepletion] = useState(
    initial?.auto_liquidate_on_depletion ?? false,
  );
  const [liquidationTargetAccountId, setLiquidationTargetAccountId] = useState(
    initial?.liquidation_target_account_id ?? "",
  );
  const [annualPropertyTax, setAnnualPropertyTax] = useState(
    initial?.annual_property_tax?.toString() ?? "0",
  );
  const [annualMaintenance, setAnnualMaintenance] = useState(
    initial?.annual_maintenance?.toString() ?? "0",
  );

  const [plannedPurchase, setPlannedPurchase] = useState(initial?.purchase_year != null);
  const [purchase, setPurchase] = useState({
    year: text(initial?.purchase_year),
    month: text(initial?.purchase_month ?? 1),
    price: text(initial?.purchase_price),
    closing: text(initial?.closing_costs),
    downMode: initial?.down_payment_amount != null ? "amount" : "percent",
    down:
      initial?.down_payment_amount != null
        ? text(initial.down_payment_amount)
        : pct(initial?.down_payment_rate),
    account: initial?.purchase_funding_account_id ?? "",
    loanRate: text(initial?.purchase_loan_rate),
    loanMonths: text(initial?.purchase_loan_term_months),
  });
  const [sellingCostRate, setSellingCostRate] = useState(pct(initial?.selling_cost_rate));
  const [residence, setResidence] = useState({
    ownedYear: text(initial?.owned_since_year),
    ownedMonth: text(initial?.owned_since_month),
    usedYear: text(initial?.primary_residence_since_year),
    usedMonth: text(initial?.primary_residence_since_month),
  });
  const [rental, setRental] = useState({
    income: text(initial?.rental_income),
    growth: pct(initial?.rental_income_growth_rate),
    expenseMode: initial?.rental_expense_rate != null ? "percent" : "amount",
    expenses:
      initial?.rental_expense_rate != null
        ? pct(initial.rental_expense_rate)
        : text(initial?.rental_expenses),
    vacancy: pct(initial?.vacancy_rate),
    propertyClass: (initial?.rental_property_class ?? "residential") as RentalPropertyClass,
    land: pct(initial?.land_value_rate),
    building: text(initial?.building_basis),
    prior: text(initial?.prior_depreciation),
    suspended: text(initial?.suspended_passive_loss),
    active: initial?.rental_active_participation ?? true,
    qbi: initial?.qbi_eligible ?? false,
  });
  // Mixed use: a main home with a rented part keeps rental tax treatment.
  const [mixedUse, setMixedUse] = useState(
    (initial?.is_primary_residence ?? false) && initial?.tax_treatment === "rental",
  );
  const [rentalShare, setRentalShare] = useState(pct(initial?.rental_use_rate));
  const [shareSteps, setShareSteps] = useState(
    (initial?.rental_use_schedule ?? []).map((step) => ({
      year: String(step.year),
      share: pct(step.rate),
    })),
  );
  const [error, setError] = useState<string | null>(null);
  const isRental = isPrimaryResidence ? mixedUse : taxTreatment === "rental";

  const [costRates, setCostRates] = useState({
    property_tax_rate:
      initial?.property_tax_rate == null ? "" : String(initial.property_tax_rate * 100),
    maintenance_rate:
      initial?.maintenance_rate == null ? "" : String(initial.maintenance_rate * 100),
    insurance_rate: initial?.insurance_rate == null ? "" : String(initial.insurance_rate * 100),
  });

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const steps = isRental
      ? shareSteps
          .filter((step) => step.year !== "" && step.share !== "")
          .map((step) => ({ year: Number(step.year), rate: Number(step.share) / 100 }))
      : [];
    if (
      isPrimaryResidence &&
      mixedUse &&
      !(rate(rentalShare) != null && rate(rentalShare)! < 1) &&
      !steps.some((step) => step.rate < 1)
    ) {
      setError("Enter the rented share of your home, below 100%.");
      return;
    }
    const buying = plannedPurchase && purchase.year !== "";
    const loan = buying && purchase.loanRate !== "" && purchase.loanMonths !== "";
    const data: RealAssetCreate = {
      name,
      // A planned purchase is valued at its price in today's dollars.
      current_value:
        buying && purchase.price !== "" ? Number(purchase.price) : Number(currentValue),
      adjusted_basis: adjustedBasis === "" ? null : Number(adjustedBasis),
      sale_year: saleYear === "" ? null : Number(saleYear),
      sale_month: saleMonth,
      annual_appreciation_rate: Number(annualAppreciationRate) / 100,
      is_primary_residence: isPrimaryResidence,
      tax_treatment: isPrimaryResidence ? (mixedUse ? "rental" : "personal_use") : taxTreatment,
      auto_liquidate_on_depletion: autoLiquidateOnDepletion,
      liquidation_target_account_id: liquidationTargetAccountId ? liquidationTargetAccountId : null,
      property_tax_rate:
        costRates.property_tax_rate === "" ? null : Number(costRates.property_tax_rate) / 100,
      maintenance_rate:
        costRates.maintenance_rate === "" ? null : Number(costRates.maintenance_rate) / 100,
      insurance_rate:
        costRates.insurance_rate === "" ? null : Number(costRates.insurance_rate) / 100,
      annual_property_tax: Number(annualPropertyTax),
      annual_maintenance: Number(annualMaintenance),
      purchase_year: buying ? Number(purchase.year) : null,
      purchase_month: buying ? Number(purchase.month || 1) : null,
      purchase_price: buying ? num(purchase.price) : null,
      closing_costs: buying ? num(purchase.closing) : null,
      down_payment_amount: loan && purchase.downMode === "amount" ? num(purchase.down) : null,
      down_payment_rate: loan && purchase.downMode === "percent" ? rate(purchase.down) : null,
      purchase_funding_account_id: buying && purchase.account ? purchase.account : null,
      purchase_loan_rate: loan ? Number(purchase.loanRate) : null,
      purchase_loan_term_months: loan ? Number(purchase.loanMonths) : null,
      selling_cost_rate: rate(sellingCostRate),
      owned_since_year: isPrimaryResidence ? num(residence.ownedYear) : null,
      owned_since_month:
        isPrimaryResidence && residence.ownedYear ? num(residence.ownedMonth) : null,
      primary_residence_since_year: isPrimaryResidence ? num(residence.usedYear) : null,
      primary_residence_since_month:
        isPrimaryResidence && residence.usedYear ? num(residence.usedMonth) : null,
      rental_income: isRental ? num(rental.income) : null,
      rental_income_growth_rate: isRental ? rate(rental.growth) : null,
      rental_expenses: isRental && rental.expenseMode === "amount" ? num(rental.expenses) : null,
      rental_expense_rate:
        isRental && rental.expenseMode === "percent" ? rate(rental.expenses) : null,
      vacancy_rate: isRental ? rate(rental.vacancy) : null,
      rental_property_class: isRental ? rental.propertyClass : null,
      land_value_rate: isRental ? rate(rental.land) : null,
      building_basis: isRental ? num(rental.building) : null,
      prior_depreciation: isRental ? num(rental.prior) : null,
      suspended_passive_loss: isRental ? num(rental.suspended) : null,
      rental_active_participation: isRental ? rental.active : true,
      qbi_eligible: isRental && rental.qbi,
      rental_use_rate: isRental ? rate(rentalShare) : null,
      rental_use_schedule: steps.length ? steps : null,
    };
    onSubmit(data);
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 8,
        padding: 12,
        border: "1px solid var(--surface-border)",
        borderRadius: 4,
      }}
    >
      <label>
        Name
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="checkbox"
          checked={plannedPurchase}
          onChange={(e) => setPlannedPurchase(e.target.checked)}
        />
        Planned purchase
      </label>
      {plannedPurchase ? (
        <fieldset style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <legend>Purchase</legend>
          <label>
            Purchase year
            <input
              type="number"
              min="1900"
              max="2200"
              value={purchase.year}
              onChange={(e) => setPurchase({ ...purchase, year: e.target.value })}
              required
            />
          </label>
          <MonthSelect
            label="Purchase month"
            value={purchase.month}
            onChange={(month) => setPurchase({ ...purchase, month })}
          />
          <label>
            {moneyLabel("Purchase price in today's dollars ($)")}
            <MoneyInput
              min="0.01"
              step="0.01"
              value={purchase.price}
              onValueChange={(price) => setPurchase({ ...purchase, price })}
              required
            />
            <small>Grows with the appreciation rate until the purchase.</small>
          </label>
          <label>
            {moneyLabel("Closing costs ($)")}
            <MoneyInput
              min="0"
              step="0.01"
              value={purchase.closing}
              onValueChange={(closing) => setPurchase({ ...purchase, closing })}
            />
            <small>Added to the tax basis.</small>
          </label>
          <label>
            Pay from
            <select
              value={purchase.account}
              onChange={(e) => setPurchase({ ...purchase, account: e.target.value })}
            >
              <option value="">Withdrawal order</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            Loan rate (%, blank for no loan)
            <input
              type="number"
              min="0"
              max="100"
              step="0.001"
              value={purchase.loanRate}
              onChange={(e) => setPurchase({ ...purchase, loanRate: e.target.value })}
            />
          </label>
          {purchase.loanRate !== "" && (
            <>
              <label>
                Loan term (months)
                <input
                  type="number"
                  min="1"
                  max="600"
                  step="1"
                  value={purchase.loanMonths}
                  onChange={(e) => setPurchase({ ...purchase, loanMonths: e.target.value })}
                  required
                />
              </label>
              <label>
                Down payment
                <select
                  aria-label="Down payment basis"
                  value={purchase.downMode}
                  onChange={(e) => setPurchase({ ...purchase, downMode: e.target.value })}
                >
                  <option value="percent">% of price</option>
                  <option value="amount">{moneyLabel("$ (today's dollars)")}</option>
                </select>
                {purchase.downMode === "amount" ? (
                  <MoneyInput
                    min="0"
                    step="0.01"
                    aria-label="Down payment value"
                    value={purchase.down}
                    onValueChange={(down) => setPurchase({ ...purchase, down })}
                  />
                ) : (
                  <input
                    type="number"
                    min="0"
                    step="0.01"
                    aria-label="Down payment value"
                    value={purchase.down}
                    onChange={(e) => setPurchase({ ...purchase, down: e.target.value })}
                  />
                )}
              </label>
            </>
          )}
          <small>
            Without a loan the full price is paid at purchase. Before the purchase the property has
            no value, costs or income.
          </small>
        </fieldset>
      ) : (
        <label>
          {moneyLabel("Current value ($)")}
          <MoneyInput
            value={currentValue}
            onValueChange={setCurrentValue}
            min="0.01"
            step="0.01"
            required
            style={{ display: "block", width: "100%" }}
          />
        </label>
      )}

      <label>
        Annual appreciation rate (%)
        <input
          type="number"
          step="0.1"
          value={annualAppreciationRate}
          onChange={(e) => setAnnualAppreciationRate(e.target.value)}
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        {moneyLabel("Adjusted tax basis ($)")}
        <MoneyInput min="0" step="0.01" value={adjustedBasis} onValueChange={setAdjustedBasis} />
        <small>Blank basis uses starting market value.</small>
      </label>
      <label>
        Planned sale year (optional)
        <input
          type="number"
          min="1900"
          max="2200"
          value={saleYear}
          onChange={(e) => setSaleYear(e.target.value)}
        />
      </label>
      {saleYear && (
        <label>
          Sale month
          <select value={saleMonth} onChange={(e) => setSaleMonth(Number(e.target.value))}>
            {Array.from({ length: 12 }, (_, i) => (
              <option key={i} value={i + 1}>
                {i + 1}
              </option>
            ))}
          </select>
          <small>Sale is modeled at the start of this month.</small>
        </label>
      )}
      <label>
        Selling costs (% of sale price)
        <input
          type="number"
          min="0"
          max="100"
          step="0.01"
          value={sellingCostRate}
          onChange={(e) => setSellingCostRate(e.target.value)}
        />
        <small>Commissions and fees reduce the gain and the cash received.</small>
      </label>

      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="checkbox"
          checked={isPrimaryResidence}
          onChange={(e) => setIsPrimaryResidence(e.target.checked)}
        />
        Primary residence
      </label>

      {isPrimaryResidence && (
        <fieldset style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <legend>Home sale exclusion</legend>
          <small>
            The exclusion needs at least 2 years of ownership and use as your main home in the 5
            years before the sale. Blank dates assume the test is met
            {plannedPurchase ? "; a planned purchase uses its purchase date" : ""}.
          </small>
          <label>
            Owned since (year)
            <input
              type="number"
              min="1900"
              max="2200"
              value={residence.ownedYear}
              onChange={(e) => setResidence({ ...residence, ownedYear: e.target.value })}
            />
          </label>
          <MonthSelect
            label="Owned since (month)"
            value={residence.ownedMonth}
            onChange={(ownedMonth) => setResidence({ ...residence, ownedMonth })}
          />
          <label>
            Main home since (year)
            <input
              type="number"
              min="1900"
              max="2200"
              value={residence.usedYear}
              onChange={(e) => setResidence({ ...residence, usedYear: e.target.value })}
            />
            <small>Blank uses the ownership date.</small>
          </label>
          <MonthSelect
            label="Main home since (month)"
            value={residence.usedMonth}
            onChange={(usedMonth) => setResidence({ ...residence, usedMonth })}
          />
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={mixedUse}
              onChange={(e) => setMixedUse(e.target.checked)}
            />
            Part of the home is rented out
          </label>
          {mixedUse && (
            <small>
              The rented share is a rental: its part of the rent, costs, interest and depreciation
              goes on Schedule E. Your share keeps its itemized property tax and mortgage interest.
              On sale, only your share of the gain can be excluded, and depreciation taken is always
              taxed.
            </small>
          )}
        </fieldset>
      )}

      {!isPrimaryResidence && (
        <>
          <label>
            Sale tax treatment
            <select
              value={taxTreatment}
              onChange={(e) => setTaxTreatment(e.target.value as AssetTaxTreatment)}
            >
              <option value="unspecified">Needs review</option>
              <option value="personal_use">Personal use (home, vehicle or other property)</option>
              <option value="investment">Investment capital asset</option>
              <option value="rental">Rental property</option>
            </select>
          </label>
          <small>
            {taxTreatment === "unspecified"
              ? "Until reviewed, gains are taxed and losses are not deducted."
              : taxTreatment === "personal_use"
                ? "Losses not deductible; gains taxable. Vehicles get no residence exclusion."
                : taxTreatment === "investment"
                  ? "Gains and losses taxed as capital gains. Choose Rental property for rent, depreciation and depreciation recapture."
                  : "Rent is taxed after expenses and depreciation, with the passive loss limits. On sale, gain up to the depreciation taken is taxed at no more than 25%."}
          </small>
        </>
      )}

      {isRental && (
        <fieldset style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <legend>Rental</legend>
          <label>
            Rented share of the property (%)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={rentalShare}
              onChange={(e) => setRentalShare(e.target.value)}
            />
            <small>
              Blank for 100%. Below 100% makes it mixed use: enter rent and expenses as if the whole
              property were rented. They, depreciation, property tax, upkeep and loan interest are
              scaled by this share.
            </small>
          </label>
          <fieldset style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <legend>Rented share by year (optional)</legend>
            {shareSteps.map((step, index) => (
              <div
                key={index}
                style={{ display: "flex", gap: 8, alignItems: "end", flexWrap: "wrap" }}
              >
                <label>
                  From year
                  <input
                    type="number"
                    min="1900"
                    max="2200"
                    value={step.year}
                    onChange={(e) =>
                      setShareSteps(
                        shareSteps.map((row, i) =>
                          i === index ? { ...row, year: e.target.value } : row,
                        ),
                      )
                    }
                  />
                </label>
                <label>
                  Rented share (%)
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="0.1"
                    value={step.share}
                    onChange={(e) =>
                      setShareSteps(
                        shareSteps.map((row, i) =>
                          i === index ? { ...row, share: e.target.value } : row,
                        ),
                      )
                    }
                  />
                </label>
                <button
                  type="button"
                  onClick={() => setShareSteps(shareSteps.filter((_, i) => i !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
            <button
              type="button"
              onClick={() => setShareSteps([...shareSteps, { year: "", share: "" }])}
            >
              Add a year
            </button>
            <small>Each change applies from its year until the next one.</small>
          </fieldset>
          <label>
            {moneyLabel("Annual rent ($, today's dollars)")}
            <MoneyInput
              min="0"
              step="0.01"
              value={rental.income}
              onValueChange={(income) => setRental({ ...rental, income })}
            />
          </label>
          <label>
            Rent growth (%/yr, blank for inflation)
            <input
              type="number"
              min="-100"
              max="100"
              step="0.1"
              value={rental.growth}
              onChange={(e) => setRental({ ...rental, growth: e.target.value })}
            />
          </label>
          <label>
            Vacancy (% of rent)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={rental.vacancy}
              onChange={(e) => setRental({ ...rental, vacancy: e.target.value })}
            />
          </label>
          <label>
            Operating expenses
            <select
              aria-label="Operating expenses basis"
              value={rental.expenseMode}
              onChange={(e) => setRental({ ...rental, expenseMode: e.target.value })}
            >
              <option value="amount">{moneyLabel("$ per year (today's dollars)")}</option>
              <option value="percent">% of collected rent</option>
            </select>
            {rental.expenseMode === "amount" ? (
              <MoneyInput
                min="0"
                step="0.01"
                aria-label="Operating expenses value"
                value={rental.expenses}
                onValueChange={(expenses) => setRental({ ...rental, expenses })}
              />
            ) : (
              <input
                type="number"
                min="0"
                step="0.01"
                aria-label="Operating expenses value"
                value={rental.expenses}
                onChange={(e) => setRental({ ...rental, expenses: e.target.value })}
              />
            )}
            <small>
              Management, repairs and other costs beyond the property tax and upkeep below.
            </small>
          </label>
          <label>
            Property type
            <select
              value={rental.propertyClass}
              onChange={(e) =>
                setRental({ ...rental, propertyClass: e.target.value as RentalPropertyClass })
              }
            >
              <option value="residential">Residential (27.5-year depreciation)</option>
              <option value="nonresidential">Nonresidential (39-year depreciation)</option>
            </select>
          </label>
          <label>
            Land value (% of cost)
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={rental.land}
              onChange={(e) => setRental({ ...rental, land: e.target.value })}
            />
            <small>Land is not depreciated. Or enter the building basis instead.</small>
          </label>
          <label>
            {moneyLabel("Building basis ($)")}
            <MoneyInput
              min="0"
              step="0.01"
              value={rental.building}
              onValueChange={(building) => setRental({ ...rental, building })}
            />
          </label>
          {!plannedPurchase && (
            <>
              <label>
                {moneyLabel("Depreciation already taken ($)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={rental.prior}
                  onValueChange={(prior) => setRental({ ...rental, prior })}
                />
              </label>
              <label>
                {moneyLabel("Suspended passive losses carried in ($)")}
                <MoneyInput
                  min="0"
                  step="0.01"
                  value={rental.suspended}
                  onValueChange={(suspended) => setRental({ ...rental, suspended })}
                />
              </label>
            </>
          )}
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={rental.active}
              onChange={(e) => setRental({ ...rental, active: e.target.checked })}
            />
            I actively participate (up to $25,000 of losses deductible)
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input
              type="checkbox"
              checked={rental.qbi}
              onChange={(e) => setRental({ ...rental, qbi: e.target.checked })}
            />
            Operated as a trade or business (qualified business income)
          </label>
        </fieldset>
      )}

      <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <input
          type="checkbox"
          checked={autoLiquidateOnDepletion}
          onChange={(e) => setAutoLiquidateOnDepletion(e.target.checked)}
        />
        Auto-liquidate on depletion
      </label>

      {(autoLiquidateOnDepletion || saleYear) && (
        <label>
          Liquidation target account
          <select
            value={liquidationTargetAccountId}
            onChange={(e) => setLiquidationTargetAccountId(e.target.value)}
            required
            style={{ display: "block", width: "100%" }}
          >
            <option value="">— Select account —</option>
            {accounts
              .filter((a) => ["checking", "savings", "taxable_brokerage"].includes(a.account_type))
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
      )}

      <label>
        {moneyLabel("Annual property tax ($)")}
        <MoneyInput
          value={annualPropertyTax}
          onValueChange={setAnnualPropertyTax}
          min="0"
          step="0.01"
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <label>
        {moneyLabel("Annual maintenance ($)")}
        <MoneyInput
          value={annualMaintenance}
          onValueChange={setAnnualMaintenance}
          min="0"
          step="0.01"
          style={{ display: "block", width: "100%" }}
        />
      </label>

      <p style={{ fontSize: 12 }}>
        Tax and maintenance rates replace fixed amounts. Insurance is additional.
      </p>
      {(["property_tax_rate", "maintenance_rate", "insurance_rate"] as const).map((key, i) => (
        <label key={key}>
          {["Property tax", "Maintenance", "Insurance"][i]} (% of value)
          <input
            type="number"
            min="0"
            max="100"
            step="0.01"
            value={costRates[key]}
            onChange={(e) => setCostRates({ ...costRates, [key]: e.target.value })}
          />
        </label>
      ))}
      {error && (
        <div role="alert" style={{ color: "var(--color-danger)", fontSize: 13 }}>
          {error}
        </div>
      )}
      <div style={{ display: "flex", gap: 8 }}>
        <button type="submit">{initial ? "Update" : "Add"} real asset</button>
        <button type="button" onClick={onCancel} data-sample-view>
          Cancel
        </button>
      </div>
    </form>
  );
}
