import { moneyLabel } from "@/utils/format";
import MoneyInput from "@/components/money_input";
import {
  AMOUNT_FREQUENCIES,
  AMOUNT_LABELS,
  FREQUENCY_LABELS,
  HOURLY_WEEKS_PER_YEAR,
  maxEntry,
  type AmountEntry,
  type AmountFrequency,
} from "@/utils/amount_frequency";

interface IncomeAmountFieldsProps {
  /** Pay entered as a rate and weekly hours rather than an amount. */
  hourlyPay: boolean;
  onHourlyChange: (hourly: boolean) => void;
  hourlyRate: string;
  onHourlyRateChange: (rate: string) => void;
  hoursPerWeek: string;
  onHoursPerWeekChange: (hours: string) => void;
  /** Annual amount implied by the current entry. */
  annualAmount: number;
  frequency: AmountFrequency;
  onFrequencyChange: (frequency: AmountFrequency) => void;
  /** The amount shown in the current unit. */
  displayedAmount: string;
  /** A typed amount in the current unit. */
  onAmountInput: (value: string) => void;
  /** Replaces the amount entry, as when hourly pay converts back to an annual amount. */
  onAmountChange: (entry: AmountEntry) => void;
  /** A one-time payment is always entered as an annual amount. */
  once: boolean;
}

/** Gross amount or hourly rate and the unit it is entered in. */
export function IncomeAmountFields({
  hourlyPay,
  onHourlyChange,
  hourlyRate,
  onHourlyRateChange,
  hoursPerWeek,
  onHoursPerWeekChange,
  annualAmount,
  frequency,
  onFrequencyChange,
  displayedAmount,
  onAmountInput,
  onAmountChange,
  once,
}: IncomeAmountFieldsProps) {
  return (
    <>
      {hourlyPay ? (
        <>
          <label>
            {moneyLabel("Hourly rate ($)")}
            <MoneyInput
              required
              min="0"
              step="any"
              value={hourlyRate}
              onValueChange={onHourlyRateChange}
            />
          </label>
          <label>
            Hours per week
            <input
              type="number"
              required
              min="0"
              max="168"
              step="any"
              value={hoursPerWeek}
              onChange={(e) => onHoursPerWeekChange(e.target.value)}
            />
          </label>
          <p className="muted" data-testid="hourly-annual">
            {Number.isFinite(annualAmount) && annualAmount > 0
              ? `${annualAmount.toLocaleString(undefined, { style: "currency", currency: "USD" })} a year (${HOURLY_WEEKS_PER_YEAR} paid weeks)`
              : `Rate × hours × ${HOURLY_WEEKS_PER_YEAR} weeks a year`}
          </p>
        </>
      ) : (
        <div>
          <label>
            {moneyLabel(AMOUNT_LABELS[frequency])}
            <MoneyInput
              required
              min="0"
              max={maxEntry(frequency)}
              step="any"
              aria-describedby="income_amount_gross"
              value={displayedAmount}
              onValueChange={onAmountInput}
            />
          </label>
          <span
            id="income_amount_gross"
            style={{ display: "block", fontSize: 12, color: "var(--text-tertiary)" }}
          >
            Gross, before tax.
          </span>
        </div>
      )}

      <label>
        Amount frequency
        <select
          value={once ? "annual" : hourlyPay ? "hourly" : frequency}
          disabled={once}
          onChange={(e) => {
            if (e.target.value === "hourly") {
              // Start the rate from the current amount when none was entered yet.
              const hours = Number(hoursPerWeek);
              if (
                hourlyRate.trim() === "" &&
                Number.isFinite(annualAmount) &&
                annualAmount > 0 &&
                hours > 0
              ) {
                onHourlyRateChange(
                  String(Math.round((annualAmount / (hours * HOURLY_WEEKS_PER_YEAR)) * 100) / 100),
                );
              }
              onHourlyChange(true);
              return;
            }
            if (hourlyPay && Number.isFinite(annualAmount))
              onAmountChange({ value: String(annualAmount), frequency: "annual" });
            onHourlyChange(false);
            onFrequencyChange(e.target.value as AmountFrequency);
          }}
        >
          {AMOUNT_FREQUENCIES.map((unit) => (
            <option key={unit} value={unit}>
              {FREQUENCY_LABELS[unit]}
            </option>
          ))}
          <option value="hourly">Hourly (rate × hours)</option>
        </select>
      </label>
    </>
  );
}
