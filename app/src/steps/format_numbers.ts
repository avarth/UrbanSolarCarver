// Numbers in the interface (UX 9): digits grouped by a narrow no-break space ("31 400"), the unit after a no-break space
// ("31 400 m³"), so neither a number nor its unit is split across lines; percentages whole in the panel.

const DIGIT_GROUP_SEPARATOR = "\u202f";     // narrow no-break space
const UNIT_SEPARATOR = "\u00a0";            // no-break space

/** The digits of a whole number in groups of three: 690807104 as "690 807 104". */
export function groupedDigits(count: number): string {
  return String(count).replace(/\B(?=(\d{3})+(?!\d))/g, DIGIT_GROUP_SEPARATOR);
}

/** *text* followed by its unit, or *text* alone without one. */
export function withUnit(text: string, unit?: string): string {
  return unit ? `${text}${UNIT_SEPARATOR}${unit}` : text;
}

/** The value rounded to *decimals*, its digits grouped, and the unit after it: formatNumber(31400, "m³") is "31 400 m³". */
export function formatNumber(value: number, unit?: string, decimals = 0): string {
  const [whole, fraction] = Math.abs(value).toFixed(decimals).split(".");
  const isNegative = value < 0 && Number(Math.abs(value).toFixed(decimals)) !== 0;     // -0.2 rounds to "0", not "-0"
  const digits = `${isNegative ? "-" : ""}${groupedDigits(Number(whole))}${fraction === undefined ? "" : `.${fraction}`}`;
  return withUnit(digits, unit);
}

/** A percentage rounded to a whole number: "61 %". */
export function formatPercent(percent: number): string {
  return formatNumber(percent, "%");
}

/** A measured value: whole from 100 up, up to two decimals from 1 up, up to three below, digits grouped ("1 250", "1.5", "0.012"). */
export function formattedNumber(value: number): string {
  const magnitude = Math.abs(value);
  const rounded = Number(value.toFixed(magnitude >= 100 ? 0 : magnitude >= 1 ? 2 : 3));
  const [whole, fraction] = String(Math.abs(rounded)).split(".");
  return `${rounded < 0 ? "-" : ""}${groupedDigits(Number(whole))}${fraction === undefined ? "" : `.${fraction}`}`;
}
