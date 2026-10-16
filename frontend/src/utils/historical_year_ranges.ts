/** Describe each continuous segment in replay order, including repeated history. */
export function historicalYearRanges(years: number[]): string {
  if (!years.length) return "None";
  const ranges: string[] = [];
  let start = years[0];
  let end = start;
  const append = () => ranges.push(start === end ? String(start) : `${start}–${end}`);
  for (const year of years.slice(1)) {
    if (year !== end + 1) {
      append();
      start = year;
    }
    end = year;
  }
  append();
  return ranges.join(", then ");
}
