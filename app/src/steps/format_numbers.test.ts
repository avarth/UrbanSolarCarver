import { expect, test } from "vitest";
import { formatNumber, formatPercent, formattedNumber, groupedDigits } from "./format_numbers";

const THIN = "\u202f";       // narrow no-break space, between groups of digits
const NBSP = "\u00a0";       // no-break space, before the unit

test("numbers use narrow no-break spaces", () => {
  expect(formatNumber(31400, "m³")).toBe(`31${THIN}400${NBSP}m³`);
});

test("a number is rounded to the decimals asked for, its digits grouped from 1 000 up", () => {
  expect(formatNumber(4820)).toBe(`4${THIN}820`);
  expect(formatNumber(999)).toBe("999");
  expect(formatNumber(1_500_000_000)).toBe(`1${THIN}500${THIN}000${THIN}000`);
  expect(formatNumber(1.25, "m", 2)).toBe(`1.25${NBSP}m`);
  expect(formatNumber(1234.56, "m²", 1)).toBe(`1${THIN}234.6${NBSP}m²`);
  expect(formatNumber(-1200, "°C")).toBe(`-1${THIN}200${NBSP}°C`);
  expect(formatNumber(-0.2)).toBe("0");
});

test("percentages are whole numbers in the panel", () => {
  expect(formatPercent(61.4)).toBe(`61${NBSP}%`);
  expect(formatPercent(61.5)).toBe(`62${NBSP}%`);
});

test("counts and measured values group their digits the same way", () => {
  expect(groupedDigits(690807104)).toBe(`690${THIN}807${THIN}104`);
  expect([1250.4, 1.5, 0.0123, 20, -100, 1000].map(formattedNumber)).toEqual([`1${THIN}250`, "1.5", "0.012", "20", "-100", `1${THIN}000`]);
});
